"""Accès à la base : SQLite (sans installation) ou PostgreSQL (comme en production).

Le service ne voit qu'une `Connexion`, avec les mêmes requêtes pour les deux bases.
Seule différence de fond : la façon de verrouiller pendant une inscription
(`verrouiller_pour_inscription`).
"""
import sqlite3
from datetime import timezone
from pathlib import Path

STATUT_VALIDEE = "validee"
STATUT_EN_ATTENTE = "en_attente_verification"

DOSSIER = Path(__file__).parent


class Connexion:
    """Connexion commune aux deux bases. Les requêtes s'écrivent avec des « ? »."""

    def __init__(self, brute, postgres):
        self.brute = brute
        self.postgres = postgres

    def execute(self, sql, parametres=()):
        if self.postgres:
            sql = sql.replace("?", "%s")  # psycopg attend %s
        return self.brute.execute(sql, parametres)

    def executer_script(self, sql):
        if self.postgres:
            self.brute.execute(sql)
        else:
            self.brute.executescript(sql)

    def verrouiller_pour_inscription(self, centre_id, npi):
        """Ouvre la transaction d'inscription et prend les verrous nécessaires.

        SQLite : BEGIN IMMEDIATE prend tout de suite le verrou d'écriture de la base.
        PostgreSQL : on verrouille la ligne du centre (capacité et numéro de table) et
        le NPI (doublon et concours du même jour). Les autres centres restent libres.
        """
        if self.postgres:
            self.execute("BEGIN")
            self.execute("SELECT id FROM centres WHERE id = ? FOR UPDATE", (centre_id,))
            self.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (npi,))
        else:
            self.execute("BEGIN IMMEDIATE")

    def close(self):
        self.brute.close()


class BaseSQLite:
    def __init__(self, chemin):
        self.chemin = chemin
        self.ErreurIntegrite = sqlite3.IntegrityError

    def connexion(self):
        # isolation_level=None : les transactions sont ouvertes explicitement.
        brute = sqlite3.connect(self.chemin, timeout=30, isolation_level=None, check_same_thread=False)
        brute.row_factory = sqlite3.Row
        brute.execute("PRAGMA foreign_keys = ON")
        brute.execute("PRAGMA busy_timeout = 30000")
        return Connexion(brute, postgres=False)

    def initialiser(self):
        cnx = self.connexion()
        try:
            cnx.execute("PRAGMA journal_mode = WAL")  # les lectures ne sont pas bloquées par les écritures
            cnx.executer_script((DOSSIER / "schema.sql").read_text(encoding="utf-8"))
        finally:
            cnx.close()


class BasePostgres:
    def __init__(self, url):
        import psycopg  # pyright: ignore[reportMissingImports]  (installé dans l'image Docker)

        self.url = url
        self.psycopg = psycopg
        self.ErreurIntegrite = psycopg.IntegrityError

    def connexion(self):
        from psycopg.rows import dict_row  # pyright: ignore[reportMissingImports]

        # autocommit : chaque lecture hors transaction est autonome ; les transactions
        # sont ouvertes explicitement par verrouiller_pour_inscription.
        brute = self.psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        return Connexion(brute, postgres=True)

    def initialiser(self):
        cnx = self.connexion()
        try:
            cnx.executer_script((DOSSIER / "schema_postgres.sql").read_text(encoding="utf-8"))
        finally:
            cnx.close()


def ouvrir_base(adresse):
    """« postgresql://… » pour PostgreSQL, sinon un chemin de fichier SQLite."""
    if adresse.startswith("postgresql://"):
        return BasePostgres(adresse)
    return BaseSQLite(adresse)


# ---------------------------------------------------------------------------
# Requêtes
# ---------------------------------------------------------------------------

def horodatage_utc(instant):
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def concours_par_code(cnx, code):
    return cnx.execute("SELECT * FROM concours WHERE code = ?", (code,)).fetchone()


def centre_par_code(cnx, code):
    return cnx.execute("SELECT * FROM centres WHERE code = ?", (code,)).fetchone()


def inscriptions_conflictuelles(cnx, npi, concours):
    """Inscriptions du NPI au même concours ou à un concours du même jour."""
    return cnx.execute(
        """SELECT c.id FROM inscriptions i JOIN concours c ON c.id = i.concours_id
           WHERE i.npi = ? AND (c.id = ? OR c.date_epreuve = ?)""",
        (npi, concours["id"], concours["date_epreuve"]),
    ).fetchall()


def nombre_inscrits(cnx, centre_id):
    return cnx.execute("SELECT COUNT(*) AS n FROM inscriptions WHERE centre_id = ?", (centre_id,)).fetchone()["n"]


def dernier_numero(cnx, centre_id):
    return cnx.execute(
        """SELECT COALESCE(MAX(CAST(SUBSTR(numero_table, 3) AS INTEGER)), 0) AS n
           FROM inscriptions WHERE centre_id = ?""",
        (centre_id,),
    ).fetchone()["n"]


def ajouter_candidat(cnx, npi, identite, naissance, maintenant):
    cnx.execute(
        """INSERT INTO candidats (npi, nom, prenoms, date_naissance, cree_le)
           VALUES (?, ?, ?, ?, ?) ON CONFLICT (npi) DO NOTHING""",
        (npi, identite.get("nom", ""), identite.get("prenoms", ""), naissance.isoformat(), horodatage_utc(maintenant)),
    )


def ajouter_inscription(cnx, concours_id, centre_id, npi, numero, statut, maintenant):
    return cnx.execute(
        """INSERT INTO inscriptions (concours_id, centre_id, npi, numero_table, statut, cree_le)
           VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
        (concours_id, centre_id, npi, numero, statut, horodatage_utc(maintenant)),
    ).fetchone()["id"]


def inscrits_du_centre(cnx, code_centre, code_concours):
    """INC-207 : une seule requête avec jointures, appuyée sur un index (au lieu d'une requête par inscrit)."""
    return cnx.execute(
        """SELECT i.numero_table, i.npi, i.statut, ca.nom, ca.prenoms, ca.date_naissance
           FROM inscriptions i
           JOIN centres ce ON ce.id = i.centre_id
           JOIN concours co ON co.id = i.concours_id
           LEFT JOIN candidats ca ON ca.npi = i.npi
           WHERE ce.code = ? AND co.code = ?
           ORDER BY i.numero_table""",
        (code_centre, code_concours),
    ).fetchall()
