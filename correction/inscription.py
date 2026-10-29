"""Enregistrement d'une inscription (POST /api/inscriptions), corrigé.

Différences avec le déroulement d'origine :
- âge en années révolues au 31 décembre (INC-205), et non plus jours / 365 ;
- clôture comparée en UTC des deux côtés (INC-204) ;
- appel d'identité AVANT la transaction et borné à 5 s (INC-206) : une lenteur du
  service ne tient plus aucun verrou et ne bloque plus le candidat ;
- étapes 4, 5, 6 et 8 dans une seule transaction en écriture exclusive
  (BEGIN IMMEDIATE) : les contrôles et le calcul du numéro voient un état qui ne
  peut pas changer avant l'enregistrement (INC-201, INC-202, INC-203) ;
- index uniques en base comme filet de sécurité (schema.sql).
"""
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import identite

AGE_MAX = 35
STATUT_VALIDEE = "validee"
STATUT_EN_ATTENTE = "en_attente_verification"
STATUT_ANNULEE = "annulee"

RE_NPI = re.compile(r"^\d{10}$")
SCHEMA = Path(__file__).with_name("schema.sql")


class Refus(Exception):
    def __init__(self, code_http, message):
        super().__init__(message)
        self.code_http = code_http
        self.message = message


# --- Règles métier ----------------------------------------------------------

def age_au_31_decembre(naissance, annee):
    """Âge en années révolues au 31 décembre : l'anniversaire de l'année est forcément passé."""
    return annee - naissance.year


def age_valide(naissance, date_epreuve):
    return age_au_31_decembre(naissance, date_epreuve.year) <= AGE_MAX


def parse_utc(texte):
    """Instant stocké en base (UTC, sans fuseau) -> datetime UTC."""
    return datetime.fromisoformat(texte).replace(tzinfo=timezone.utc)


def inscriptions_closes(cloture_utc, maintenant):
    """Les inscriptions restent ouvertes jusqu'à l'instant de clôture inclus.

    `maintenant` doit porter un fuseau : on compare deux instants, jamais une heure
    locale du serveur avec une valeur UTC.
    """
    if maintenant.tzinfo is None:
        raise ValueError("maintenant doit être un datetime avec fuseau")
    return maintenant.astimezone(timezone.utc) > cloture_utc


# --- Base -------------------------------------------------------------------

def connexion(chemin_db):
    cnx = sqlite3.connect(chemin_db, timeout=30, isolation_level=None, check_same_thread=False)
    cnx.row_factory = sqlite3.Row
    cnx.execute("PRAGMA foreign_keys = ON")
    cnx.execute("PRAGMA busy_timeout = 30000")
    return cnx


def initialiser(chemin_db):
    cnx = connexion(chemin_db)
    try:
        cnx.execute("PRAGMA journal_mode = WAL")
        cnx.executescript(SCHEMA.read_text(encoding="utf-8"))
    finally:
        cnx.close()


def _horodatage(maintenant):
    return maintenant.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _controle_doublons(cnx, npi, concours):
    """Étape 4 : déjà inscrit à ce concours, ou à un concours du même jour."""
    deja = cnx.execute(
        """SELECT c.id, c.date_epreuve FROM inscriptions i JOIN concours c ON c.id = i.concours_id
           WHERE i.npi = ? AND i.statut <> ? AND (c.id = ? OR c.date_epreuve = ?)""",
        (npi, STATUT_ANNULEE, concours["id"], concours["date_epreuve"]),
    ).fetchall()
    if any(r["id"] == concours["id"] for r in deja):
        raise Refus(409, "Vous êtes déjà inscrit à ce concours.")
    if deja:
        raise Refus(409, "Vous êtes déjà inscrit à un concours dont l'épreuve a lieu le même jour.")


def _controle_capacite(cnx, centre):
    """Étape 5 : capacité du centre, tous concours confondus."""
    n = cnx.execute(
        "SELECT COUNT(*) FROM inscriptions WHERE centre_id = ? AND statut <> ?", (centre["id"], STATUT_ANNULEE)
    ).fetchone()[0]
    if n >= centre["capacite"]:
        raise Refus(409, "Ce centre d'examen est complet.")


def _prochain_numero(cnx, centre):
    """Étape 6 : plus grand numéro du centre + 1, calculé sous verrou d'écriture."""
    n = cnx.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(numero_table, 3) AS INTEGER)), 0) FROM inscriptions WHERE centre_id = ?",
        (centre["id"],),
    ).fetchone()[0]
    return f"{centre['code']}-{n + 1:04d}"


# --- Inscription ------------------------------------------------------------

def inscrire(chemin_db, demande, client_identite, maintenant=None):
    """Enregistre une inscription. Retourne un dict ; lève Refus(code_http, message)."""
    maintenant = maintenant or datetime.now(timezone.utc)

    # 1. Contrôle de forme
    npi = str(demande.get("npi", ""))
    if not RE_NPI.match(npi):
        raise Refus(400, "Le NPI doit comporter exactement 10 chiffres.")
    try:
        naissance = date.fromisoformat(str(demande.get("date_naissance", "")))
    except ValueError:
        raise Refus(400, "Date de naissance invalide (AAAA-MM-JJ).")

    cnx = connexion(chemin_db)
    try:
        concours = cnx.execute("SELECT * FROM concours WHERE code = ?", (demande.get("concours"),)).fetchone()
        centre = cnx.execute("SELECT * FROM centres WHERE code = ?", (demande.get("centre"),)).fetchone()
        if concours is None:
            raise Refus(400, "Concours inconnu.")
        if centre is None:
            raise Refus(400, "Centre d'examen inconnu.")

        # 2. Clôture (INC-204) et 3. âge (INC-205)
        if inscriptions_closes(parse_utc(concours["cloture"]), maintenant):
            raise Refus(409, "Inscriptions closes pour ce concours.")
        if not age_valide(naissance, date.fromisoformat(concours["date_epreuve"])):
            raise Refus(409, "Âge limite dépassé : 35 ans au 31 décembre de l'année du concours.")

        # Pré-contrôle sans verrou : évite un appel d'identité inutile (il sera refait sous verrou).
        _controle_doublons(cnx, npi, concours)
        _controle_capacite(cnx, centre)

        # 7. Identité, hors transaction et bornée à 5 s (INC-206)
        etat, ident = client_identite.verifier(npi)
        if etat == identite.INCONNU:
            raise Refus(409, "NPI inconnu du service d'identification.")
        statut = STATUT_VALIDEE if etat == identite.CONNU else STATUT_EN_ATTENTE

        # 4, 5, 6, 8 : une seule transaction ; BEGIN IMMEDIATE prend le verrou d'écriture
        # tout de suite, donc deux inscriptions ne peuvent pas lire le même état.
        cnx.execute("BEGIN IMMEDIATE")
        try:
            _controle_doublons(cnx, npi, concours)
            _controle_capacite(cnx, centre)
            numero = _prochain_numero(cnx, centre)
            if ident is not None:
                cnx.execute(
                    """INSERT INTO candidats (npi, nom, prenoms, date_naissance, cree_le)
                       VALUES (?, ?, ?, ?, ?) ON CONFLICT (npi) DO NOTHING""",
                    (npi, ident.get("nom", ""), ident.get("prenoms", ""), naissance.isoformat(), _horodatage(maintenant)),
                )
            # Candidat non vérifié : il sera créé par la reprise des « en attente ».
            cur = cnx.execute(
                """INSERT INTO inscriptions (concours_id, centre_id, npi, numero_table, statut, cree_le)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (concours["id"], centre["id"], npi, numero, statut, _horodatage(maintenant)),
            )
            cnx.execute("COMMIT")
        except sqlite3.IntegrityError:
            cnx.execute("ROLLBACK")
            # Ne peut arriver que si un autre programme écrit sans verrou : la base refuse le doublon.
            raise Refus(409, "Inscription en conflit avec une inscription existante.")
        except BaseException:
            cnx.execute("ROLLBACK")
            raise
        return {"id": cur.lastrowid, "numero_table": numero, "statut": statut,
                "concours": concours["code"], "centre": centre["code"], "npi": npi}
    finally:
        cnx.close()


def lister_inscrits(chemin_db, code_centre, code_concours):
    """INC-207 : une seule requête avec jointure (au lieu d'une requête par inscrit), sur index."""
    cnx = connexion(chemin_db)
    try:
        return [dict(r) for r in cnx.execute(
            """SELECT i.numero_table, i.npi, i.statut, ca.nom, ca.prenoms, ca.date_naissance
               FROM inscriptions i
               JOIN centres ce ON ce.id = i.centre_id
               JOIN concours co ON co.id = i.concours_id
               LEFT JOIN candidats ca ON ca.npi = i.npi
               WHERE ce.code = ? AND co.code = ? AND i.statut <> ?
               ORDER BY i.numero_table""",
            (code_centre, code_concours, STATUT_ANNULEE),
        )]
    finally:
        cnx.close()
