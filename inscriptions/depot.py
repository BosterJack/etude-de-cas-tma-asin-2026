"""Accès à la base (SQLite) : connexion, schéma et requêtes."""
import sqlite3
from datetime import timezone
from pathlib import Path

STATUT_VALIDEE = "validee"
STATUT_EN_ATTENTE = "en_attente_verification"

SCHEMA = Path(__file__).with_name("schema.sql")


def connexion(chemin_db):
    # isolation_level=None : les transactions sont pilotées explicitement (BEGIN IMMEDIATE).
    cnx = sqlite3.connect(chemin_db, timeout=30, isolation_level=None, check_same_thread=False)
    cnx.row_factory = sqlite3.Row
    cnx.execute("PRAGMA foreign_keys = ON")
    cnx.execute("PRAGMA busy_timeout = 30000")
    return cnx


def initialiser(chemin_db):
    cnx = connexion(chemin_db)
    try:
        cnx.execute("PRAGMA journal_mode = WAL")  # lectures non bloquées par les écritures
        cnx.executescript(SCHEMA.read_text(encoding="utf-8"))
    finally:
        cnx.close()


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
    return cnx.execute("SELECT COUNT(*) FROM inscriptions WHERE centre_id = ?", (centre_id,)).fetchone()[0]


def dernier_numero(cnx, centre_id):
    return cnx.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(numero_table, 3) AS INTEGER)), 0) FROM inscriptions WHERE centre_id = ?",
        (centre_id,),
    ).fetchone()[0]


def ajouter_candidat(cnx, npi, identite, naissance, maintenant):
    cnx.execute(
        """INSERT INTO candidats (npi, nom, prenoms, date_naissance, cree_le)
           VALUES (?, ?, ?, ?, ?) ON CONFLICT (npi) DO NOTHING""",
        (npi, identite.get("nom", ""), identite.get("prenoms", ""), naissance.isoformat(), horodatage_utc(maintenant)),
    )


def ajouter_inscription(cnx, concours_id, centre_id, npi, numero, statut, maintenant):
    cur = cnx.execute(
        """INSERT INTO inscriptions (concours_id, centre_id, npi, numero_table, statut, cree_le)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (concours_id, centre_id, npi, numero, statut, horodatage_utc(maintenant)),
    )
    return cur.lastrowid


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
