"""Analyse du journal de production de la plateforme d'inscription.

Usage :
    python analyse/analyse_journal.py <chemin_du_journal>

Le journal est en UTC ; tous les résultats sont affichés en heure du Bénin (UTC+1).
Rappel du format : une ligne est écrite à la FIN d'une requête, avec sa durée.
L'heure de début d'une requête vaut donc « heure de la ligne - durée ».
"""
import io
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote_plus

HEURE_DU_BENIN = timezone(timedelta(hours=1))
SEUIL_LENTEUR_MS = 5000
AGE_MAX = 35

# Référentiel des concours, recopié de la table `concours` de l'export.
# La clôture est en UTC : 22:59 UTC = 23:59 heure du Bénin.
DATE_EPREUVE = {
    "DOUANES": date(2026, 12, 12),
    "IMPOTS": date(2026, 12, 12),
    "TRESOR": date(2026, 12, 19),
}
CLOTURE_UTC = {
    "DOUANES": datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc),
    "IMPOTS": datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc),
    "TRESOR": datetime(2026, 11, 20, 22, 59, tzinfo=timezone.utc),
}


# ---------------------------------------------------------------------------
# Lecture du journal
# ---------------------------------------------------------------------------

@dataclass
class Requete:
    """Une requête reçue par l'API (ligne « <ip> <méthode> <chemin> -> <statut> »)."""
    fin: datetime
    id: str
    ip: str
    methode: str
    chemin: str
    statut: int
    duree_ms: int
    champs: dict = field(default_factory=dict)  # concours=…, npi=…, numero=…, erreur=…

    @property
    def debut(self):
        return self.fin - timedelta(milliseconds=self.duree_ms)

    @property
    def est_inscription(self):
        return self.methode == "POST" and self.chemin == "/api/inscriptions"

    @property
    def acceptee(self):
        return self.statut == 201

    @property
    def erreur(self):
        return self.champs.get("erreur", "")


@dataclass
class AppelIdentite:
    """Un appel au service d'identification (ligne « appel identite GET /identite/<npi> »)."""
    fin: datetime
    id_requete: str
    npi: str
    statut: int
    duree_ms: int

    @property
    def debut(self):
        return self.fin - timedelta(milliseconds=self.duree_ms)


ENTETE = re.compile(r"^(\S+)\s+(?:INFO|WARN|ERROR)\s+\[req:([0-9a-f]+)\]\s+(.*)$")
APPEL_IDENTITE = re.compile(r"^appel identite GET /identite/(\S+) -> (\d+) \((\d+) ms\)$")
REQUETE = re.compile(r"^(\S+) ([A-Z]+) (\S+) -> (\d+) \((\d+) ms\) ?(.*)$")
ERREUR = re.compile(r'erreur="(.*)"$')
CLE_VALEUR = re.compile(r"(\w+)=(\S+)")


def lire_champs(texte):
    """Lit les paires « cle=valeur » de fin de ligne.

    Le champ erreur est toujours le dernier ; on le traite à part car son
    message peut contenir des espaces et des guillemets.
    """
    champs = {}
    erreur = ERREUR.search(texte)
    if erreur:
        champs["erreur"] = erreur.group(1)
        texte = texte[:erreur.start()]
    for cle, valeur in CLE_VALEUR.findall(texte):
        champs[cle] = valeur
    return champs


def lire_journal(chemin):
    """Retourne (requêtes, appels au service d'identification, numéros des lignes non reconnues)."""
    requetes = []
    appels = []
    non_reconnues = []

    with open(chemin, encoding="utf-8") as fichier:
        for numero_ligne, ligne in enumerate(fichier, start=1):
            entete = ENTETE.match(ligne.strip())
            if not entete:
                non_reconnues.append(numero_ligne)
                continue
            horodatage, id_requete, message = entete.groups()
            fin = datetime.fromisoformat(horodatage.replace("Z", "+00:00"))

            appel = APPEL_IDENTITE.match(message)
            if appel:
                npi, statut, duree = appel.groups()
                appels.append(AppelIdentite(fin, id_requete, npi, int(statut), int(duree)))
                continue

            requete = REQUETE.match(message)
            if requete:
                ip, methode, chemin_url, statut, duree, reste = requete.groups()
                requetes.append(Requete(fin, id_requete, ip, methode, chemin_url, int(statut), int(duree),
                                        lire_champs(reste)))
                continue

            non_reconnues.append(numero_ligne)

    return requetes, appels, non_reconnues


def inscriptions(requetes):
    return [r for r in requetes if r.est_inscription]


def inscriptions_acceptees(requetes):
    return [r for r in requetes if r.est_inscription and r.acceptee]


# ---------------------------------------------------------------------------
# Les questions du sujet
# ---------------------------------------------------------------------------

def numeros_en_double(requetes):
    """Numéros de table attribués plusieurs fois (INC-201) : {numéro: [inscriptions]}."""
    par_numero = defaultdict(list)
    for r in inscriptions_acceptees(requetes):
        par_numero[r.champs["numero"]].append(r)
    return {numero: liste for numero, liste in sorted(par_numero.items()) if len(liste) > 1}


def inscriptions_en_double(requetes):
    """Même NPI inscrit plusieurs fois au même concours (INC-203) : {(npi, concours): [inscriptions]}."""
    par_candidat = defaultdict(list)
    for r in inscriptions_acceptees(requetes):
        par_candidat[(r.champs["npi"], r.champs["concours"])].append(r)
    return {cle: sorted(liste, key=lambda r: r.debut)
            for cle, liste in sorted(par_candidat.items()) if len(liste) > 1}


@dataclass
class PeriodeLente:
    debut: datetime
    fin: datetime
    appels_lents: list
    requetes_touchees: list


def periode_identite_lente(appels, requetes):
    """Période où le service d'identification a mis 5 s ou plus (INC-206), ou None.

    La période va du DÉBUT du premier appel lent à la FIN du dernier.
    """
    appels_lents = [a for a in appels if a.duree_ms >= SEUIL_LENTEUR_MS]
    if not appels_lents:
        return None
    ids_touches = {a.id_requete for a in appels_lents}
    return PeriodeLente(
        debut=min(a.debut for a in appels_lents),
        fin=max(a.fin for a in appels_lents),
        appels_lents=appels_lents,
        requetes_touchees=[r for r in requetes if r.id in ids_touches],
    )


def refus_cloture_a_tort(requetes):
    """Refus « Inscriptions closes » alors que la clôture réelle n'était pas passée (INC-204)."""
    return [r for r in inscriptions(requetes)
            if "Inscriptions closes" in r.erreur
            and r.debut <= CLOTURE_UTC[r.champs["concours"]]]


def age_au_31_decembre(naissance, annee):
    # Au 31 décembre, l'anniversaire de l'année est passé : l'âge est la différence des années.
    return annee - naissance.year


def refus_age_a_tort(requetes):
    """Refus « Âge limite » de candidats qui ont au plus 35 ans au 31/12 (INC-205)."""
    refus = []
    for r in inscriptions(requetes):
        if "Âge limite" not in r.erreur:
            continue
        naissance = date.fromisoformat(r.champs["naissance"])
        annee_concours = DATE_EPREUVE[r.champs["concours"]].year
        if age_au_31_decembre(naissance, annee_concours) <= AGE_MAX:
            refus.append(r)
    return refus


@dataclass
class DureeListe:
    nb_appels: int
    moyenne_ms: int
    max_ms: int
    max_lignes: int


def durees_liste_inscrits(requetes):
    """Durée moyenne et maximale de la liste des inscrits, par centre (INC-207)."""
    par_centre = defaultdict(list)
    for r in requetes:
        route = re.match(r"^/api/centres/(\w)/inscrits", r.chemin)
        if r.methode == "GET" and route:
            par_centre[route.group(1)].append(r)

    resultat = {}
    for centre, liste in sorted(par_centre.items()):
        durees = [r.duree_ms for r in liste]
        resultat[centre] = DureeListe(
            nb_appels=len(liste),
            moyenne_ms=round(sum(durees) / len(durees)),
            max_ms=max(durees),
            max_lignes=max(int(r.champs.get("lignes", 0)) for r in liste),
        )
    return resultat


MOTIF_INJECTION_SQL = re.compile(r"'|--|;|\b(union|select|or|drop)\b", re.IGNORECASE)


def recherches_suspectes(requetes):
    """Bonus : recherches par nom qui contiennent du SQL ou ont provoqué une erreur 500."""
    suspectes = []
    for r in requetes:
        if not r.chemin.startswith("/api/inscrits/recherche?nom="):
            continue
        nom = unquote_plus(r.chemin.split("nom=", 1)[1])
        if MOTIF_INJECTION_SQL.search(nom) or r.statut >= 500:
            suspectes.append(r)
    return suspectes


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------

def en_heure_du_benin(instant):
    return instant.astimezone(HEURE_DU_BENIN).strftime("%d/%m/%Y %H:%M:%S")


def en_secondes(ms):
    return f"{ms / 1000:.1f} s"


def titre(texte):
    print()
    print("=" * 78)
    print(texte)
    print("=" * 78)


def afficher_rapport(chemin, requetes, appels, non_reconnues):
    print(f"Journal : {chemin}")
    print(f"{len(requetes)} requêtes, {len(appels)} appels au service d'identification, "
          f"{len(non_reconnues)} lignes non reconnues")
    print("Toutes les heures sont en heure du Bénin (UTC+1).")

    titre("1. Numéros de table attribués plusieurs fois (INC-201)")
    doublons = numeros_en_double(requetes)
    attributions_en_trop = sum(len(liste) - 1 for liste in doublons.values())
    print(f"{len(doublons)} numéros, {attributions_en_trop} attributions en trop.")
    for numero, liste in doublons.items():
        print(f"  {numero} attribué {len(liste)} fois :")
        for r in liste:
            print(f"    {en_heure_du_benin(r.fin)}  npi={r.champs['npi']}  {r.champs['concours']}  "
                  f"durée {en_secondes(r.duree_ms)}  [req:{r.id}]")

    titre("2. Inscriptions en double (INC-203)")
    doubles = inscriptions_en_double(requetes)
    print(f"{len(doubles)} candidats inscrits deux fois au même concours.")
    for (npi, concours), liste in doubles.items():
        ecart = (liste[1].debut - liste[0].debut).total_seconds()
        print(f"  npi={npi}  {concours}  {liste[0].champs['numero']}  "
              f"1er envoi {en_heure_du_benin(liste[0].debut)}, 2e envoi {ecart:.0f} s après  ip={liste[0].ip}")

    titre("3. Service d'identification à 5 s ou plus (INC-206)")
    periode = periode_identite_lente(appels, requetes)
    if periode is None:
        print("Aucun appel lent.")
    else:
        durees = [a.duree_ms for a in periode.appels_lents]
        print(f"Du {en_heure_du_benin(periode.debut)} au {en_heure_du_benin(periode.fin)}")
        print(f"Requêtes touchées : {len(periode.requetes_touchees)}")
        print(f"  dont inscriptions : {sum(1 for r in periode.requetes_touchees if r.est_inscription)}")
        print(f"  dont convocations : {sum(1 for r in periode.requetes_touchees if r.chemin.endswith('/convocation'))}")
        print(f"Durée des appels lents : moyenne {en_secondes(sum(durees) / len(durees))}, "
              f"max {en_secondes(max(durees))}")

    titre("4. Refus à tort le soir de la clôture du Trésor (INC-204)")
    refus = [r for r in refus_cloture_a_tort(requetes) if r.champs["concours"] == "TRESOR"]
    print(f"{len(refus)} refus à tort, pour {len({r.champs['npi'] for r in refus})} candidats.")
    if refus:
        print(f"Du {en_heure_du_benin(min(r.debut for r in refus))} au {en_heure_du_benin(max(r.debut for r in refus))}"
              f" (clôture réelle : {en_heure_du_benin(CLOTURE_UTC['TRESOR'])})")
    deja_inscrits = {r.champs["npi"] for r in inscriptions_acceptees(requetes) if r.champs["concours"] == "TRESOR"}
    prives = {r.champs["npi"] for r in refus} - deja_inscrits
    print(f"Candidats privés d'inscription (hors ceux déjà inscrits plus tôt) : {len(prives)}")

    titre("5. Candidats refusés à tort pour l'âge (INC-205)")
    refus_age = refus_age_a_tort(requetes)
    print(f"{len(refus_age)} candidats (35 ans au plus au 31/12, refusés par le calcul jours / 365).")
    for r in refus_age:
        print(f"  {en_heure_du_benin(r.fin)}  npi={r.champs['npi']}  né le {r.champs['naissance']}  "
              f"{r.champs['concours']}")

    titre("6. Liste des inscrits par centre (INC-207)")
    print(f"{'Centre':<8}{'Appels':>8}{'Moyenne':>10}{'Maximum':>10}{'Lignes max':>12}")
    for centre, d in durees_liste_inscrits(requetes).items():
        print(f"{centre:<8}{d.nb_appels:>8}{en_secondes(d.moyenne_ms):>10}{en_secondes(d.max_ms):>10}"
              f"{d.max_lignes:>12}")

    titre("Bonus : recherches suspectes")
    suspectes = recherches_suspectes(requetes)
    ips = {r.ip for r in suspectes}
    for r in requetes:
        if r.ip in ips:
            nom = unquote_plus(r.chemin.split("nom=", 1)[-1])
            print(f"  {en_heure_du_benin(r.fin)}  ip={r.ip}  statut={r.statut}  "
                  f"lignes={r.champs.get('lignes', '-')}  nom={nom!r}")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")  # accents lisibles dans la console Windows
    requetes, appels, non_reconnues = lire_journal(sys.argv[1])
    afficher_rapport(sys.argv[1], requetes, appels, non_reconnues)


if __name__ == "__main__":
    main()
