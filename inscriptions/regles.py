"""Règles métier pures (sans base ni réseau), testables isolément.

Références : section « Fonctionnement attendu » du cahier des charges.
"""
import re
from datetime import datetime, timezone

AGE_MAX = 35
RE_NPI = re.compile(r"^\d{10}$")


class Refus(Exception):
    """Refus d'inscription, avec le code HTTP à renvoyer au candidat."""

    def __init__(self, code_http, message):
        super().__init__(message)
        self.code_http = code_http
        self.message = message


def npi_valide(npi):
    return bool(RE_NPI.match(npi))


def age_au_31_decembre(naissance, annee):
    """Âge en années révolues au 31 décembre de `annee`.

    Au 31 décembre, l'anniversaire de l'année est forcément passé : l'âge est la
    différence des années. INC-205 : l'ancien calcul (jours / 365) ignorait les
    années bissextiles et comparait un âge décimal (35,55 > 35).
    """
    return annee - naissance.year


def age_valide(naissance, date_epreuve):
    return age_au_31_decembre(naissance, date_epreuve.year) <= AGE_MAX


def instant_utc(texte):
    """Instant stocké en base (UTC, sans fuseau) -> datetime UTC avec fuseau."""
    return datetime.fromisoformat(texte).replace(tzinfo=timezone.utc)


def inscriptions_closes(cloture_utc, maintenant):
    """Vrai si l'instant `maintenant` est postérieur à la clôture (clôture incluse).

    INC-204 : l'ancien code comparait l'heure locale du serveur (Bénin, UTC+1) à une
    valeur stockée en UTC, d'où une fermeture une heure trop tôt. On compare ici deux
    instants avec fuseau ; une heure « naïve » est refusée pour ne pas réintroduire
    le bug.
    """
    if maintenant.tzinfo is None:
        raise ValueError("maintenant doit porter un fuseau horaire")
    return maintenant.astimezone(timezone.utc) > cloture_utc
