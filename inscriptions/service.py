"""Enregistrement d'une inscription (POST /api/inscriptions), corrigé.

Changements par rapport au déroulement d'origine (dossier technique, étapes 1 à 8) :

- étape 7 (identité) déplacée AVANT la transaction et bornée à 5 s : une lenteur
  du service ne tient plus aucun verrou et ne bloque plus le candidat (INC-206) ;
- étapes 4, 5, 6 et 8 dans UNE transaction en écriture exclusive (BEGIN IMMEDIATE) :
  contrôles et calcul du numéro voient un état qui ne peut plus changer avant
  l'enregistrement (INC-201, INC-202, INC-203) ;
- index uniques en base en filet de sécurité (schema.sql) ;
- règles d'âge et de clôture corrigées (regles.py, INC-204 et INC-205).

Équivalent PostgreSQL (production) : `SELECT … FROM centres WHERE id = $1 FOR UPDATE`
(capacité et numéro) et `pg_advisory_xact_lock(npi)` (doublon et même jour), dans
la même transaction, avec les mêmes index uniques.
"""
import sqlite3
from datetime import date, datetime, timezone

from . import client_identite, depot, regles
from .regles import Refus


def _verifier_doublons(cnx, npi, concours):
    """Étape 4 : une seule inscription par concours, pas deux concours le même jour."""
    conflits = depot.inscriptions_conflictuelles(cnx, npi, concours)
    if any(r["id"] == concours["id"] for r in conflits):
        raise Refus(409, "Vous êtes déjà inscrit à ce concours.")
    if conflits:
        raise Refus(409, "Vous êtes déjà inscrit à un concours dont l'épreuve a lieu le même jour.")


def _verifier_capacite(cnx, centre):
    """Étape 5 : capacité du centre, tous concours confondus."""
    if depot.nombre_inscrits(cnx, centre["id"]) >= centre["capacite"]:
        raise Refus(409, "Ce centre d'examen est complet.")


def _lire_demande(demande):
    """Étape 1 : contrôle de forme du NPI et de la date de naissance."""
    npi = str(demande.get("npi", ""))
    if not regles.npi_valide(npi):
        raise Refus(400, "Le NPI doit comporter exactement 10 chiffres.")
    try:
        naissance = date.fromisoformat(str(demande.get("date_naissance", "")))
    except ValueError:
        raise Refus(400, "Date de naissance invalide (format attendu : AAAA-MM-JJ).")
    return npi, naissance


def inscrire(chemin_db, demande, identite, maintenant=None):
    """Enregistre une inscription et retourne son résumé ; lève Refus sinon.

    `identite` : un ClientIdentite (injecté pour les tests).
    `maintenant` : instant avec fuseau (injecté pour les tests), par défaut l'heure UTC.
    """
    maintenant = maintenant or datetime.now(timezone.utc)
    npi, naissance = _lire_demande(demande)

    cnx = depot.connexion(chemin_db)
    try:
        concours = depot.concours_par_code(cnx, demande.get("concours"))
        centre = depot.centre_par_code(cnx, demande.get("centre"))
        if concours is None:
            raise Refus(400, "Concours inconnu.")
        if centre is None:
            raise Refus(400, "Centre d'examen inconnu.")

        # Étapes 2 et 3
        if regles.inscriptions_closes(regles.instant_utc(concours["cloture"]), maintenant):
            raise Refus(409, "Inscriptions closes pour ce concours.")
        if not regles.age_valide(naissance, date.fromisoformat(concours["date_epreuve"])):
            raise Refus(409, "Âge limite dépassé : 35 ans au 31 décembre de l'année du concours.")

        # Pré-contrôle sans verrou : évite un appel d'identité inutile. Refait sous verrou plus bas.
        _verifier_doublons(cnx, npi, concours)
        _verifier_capacite(cnx, centre)

        # Étape 7, hors transaction et bornée à 5 s
        etat, fiche = identite.verifier(npi)
        if etat == client_identite.INCONNU:
            raise Refus(409, "NPI inconnu du service d'identification.")
        statut = depot.STATUT_VALIDEE if etat == client_identite.CONNU else depot.STATUT_EN_ATTENTE

        # Étapes 4, 5, 6 et 8 dans une transaction exclusive
        cnx.execute("BEGIN IMMEDIATE")
        try:
            _verifier_doublons(cnx, npi, concours)
            _verifier_capacite(cnx, centre)
            numero = f"{centre['code']}-{depot.dernier_numero(cnx, centre['id']) + 1:04d}"
            if fiche is not None:
                depot.ajouter_candidat(cnx, npi, fiche, naissance, maintenant)
            # Identité non vérifiée : le candidat sera créé par la reprise des inscriptions en attente.
            inscription_id = depot.ajouter_inscription(
                cnx, concours["id"], centre["id"], npi, numero, statut, maintenant
            )
            cnx.execute("COMMIT")
        except sqlite3.IntegrityError:
            cnx.execute("ROLLBACK")
            # N'arrive que si un autre programme écrit sans verrou : la base a refusé le doublon.
            raise Refus(409, "Inscription en conflit avec une inscription existante.")
        except BaseException:
            cnx.execute("ROLLBACK")
            raise

        return {"id": inscription_id, "numero_table": numero, "statut": statut,
                "concours": concours["code"], "centre": centre["code"], "npi": npi}
    finally:
        cnx.close()


def lister_inscrits(chemin_db, code_centre, code_concours):
    cnx = depot.connexion(chemin_db)
    try:
        return [dict(r) for r in depot.inscrits_du_centre(cnx, code_centre, code_concours)]
    finally:
        cnx.close()
