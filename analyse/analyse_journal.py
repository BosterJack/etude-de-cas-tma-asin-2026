#!/usr/bin/env python3
"""Analyse du journal de production de la plateforme d'inscription aux concours.

Usage :
    python analyse/analyse_journal.py <chemin_du_journal> [--json]

Bibliothèque standard uniquement (Python 3.8+). Le journal est en UTC ; tous les
résultats sont affichés en heure du Bénin (UTC+1, sans heure d'été).
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from urllib.parse import unquote_plus

BENIN = timezone(timedelta(hours=1), "Bénin")
SEUIL_IDENTITE_MS = 5000
AGE_MAX = 35

# Référentiel des concours (source : base_inscriptions.sql, table concours).
# La clôture est stockée en UTC : 22:59 UTC = 23:59 heure du Bénin.
CONCOURS = {
    "DOUANES": {"date_epreuve": date(2026, 12, 12), "cloture_utc": datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc)},
    "IMPOTS": {"date_epreuve": date(2026, 12, 12), "cloture_utc": datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc)},
    "TRESOR": {"date_epreuve": date(2026, 12, 19), "cloture_utc": datetime(2026, 11, 20, 22, 59, tzinfo=timezone.utc)},
}

RE_LIGNE = re.compile(r"^(?P<ts>\S+)\s+(?P<niveau>INFO|WARN|ERROR)\s+\[req:(?P<req>[0-9a-f]+)\]\s+(?P<reste>.*)$")
RE_IDENTITE = re.compile(r"^appel identite GET /identite/(?P<npi>\S+) -> (?P<statut>\d+) \((?P<ms>\d+) ms\)$")
RE_REQUETE = re.compile(
    r"^(?P<ip>\S+) (?P<methode>[A-Z]+) (?P<chemin>\S+) -> (?P<statut>\d+) \((?P<ms>\d+) ms\)(?: (?P<extra>.*))?$"
)
RE_ERREUR = re.compile(r'erreur="(?P<msg>.*)"$')
RE_CLE_VALEUR = re.compile(r'(\w+)=("[^"]*"|\S+)')
RE_LISTE = re.compile(r"^/api/centres/(?P<centre>[^/]+)/inscrits\?concours=(?P<concours>\w+)")
RE_SQL_SUSPECT = re.compile(r"'|--|;|\b(union|select|or|and|drop|insert|update|delete|sleep)\b", re.I)


def heure_benin(instant):
    return instant.astimezone(BENIN).strftime("%d/%m/%Y %H:%M:%S")


def parse_instant(texte):
    return datetime.fromisoformat(texte.replace("Z", "+00:00"))


def parse_extra(extra):
    """Paires cle=valeur en fin de ligne ; 'erreur' est toujours en dernier et peut contenir des guillemets."""
    champs = {}
    if not extra:
        return champs
    m = RE_ERREUR.search(extra)
    if m:
        champs["erreur"] = m.group("msg")
        extra = extra[: m.start()]
    for cle, valeur in RE_CLE_VALEUR.findall(extra):
        champs[cle] = valeur.strip('"')
    return champs


def lire_journal(chemin):
    """Retourne (requetes, appels_identite, lignes_ignorees)."""
    requetes, appels, ignorees = [], [], []
    with open(chemin, encoding="utf-8") as f:
        for num, ligne in enumerate(f, 1):
            ligne = ligne.rstrip("\r\n")
            if not ligne.strip():
                continue
            m = RE_LIGNE.match(ligne)
            if not m:
                ignorees.append(num)
                continue
            fin = parse_instant(m.group("ts"))
            reste = m.group("reste")
            mi = RE_IDENTITE.match(reste)
            if mi:
                ms = int(mi.group("ms"))
                appels.append({
                    "ligne": num, "req": m.group("req"), "niveau": m.group("niveau"),
                    "npi": mi.group("npi"), "statut": int(mi.group("statut")), "ms": ms,
                    "fin": fin, "debut": fin - timedelta(milliseconds=ms),
                })
                continue
            mr = RE_REQUETE.match(reste)
            if mr:
                ms = int(mr.group("ms"))
                requetes.append({
                    "ligne": num, "req": m.group("req"), "niveau": m.group("niveau"),
                    "ip": mr.group("ip"), "methode": mr.group("methode"), "chemin": mr.group("chemin"),
                    "statut": int(mr.group("statut")), "ms": ms,
                    "fin": fin, "debut": fin - timedelta(milliseconds=ms),
                    **parse_extra(mr.group("extra")),
                })
                continue
            ignorees.append(num)
    return requetes, appels, ignorees


def inscriptions(requetes):
    return [r for r in requetes if r["methode"] == "POST" and r["chemin"] == "/api/inscriptions"]


# 1. Numéros de table attribués plusieurs fois (INC-201)
def numeros_en_double(requetes):
    par_numero = defaultdict(list)
    for r in inscriptions(requetes):
        if r["statut"] == 201 and "numero" in r:
            par_numero[r["numero"]].append(r)
    return {n: lst for n, lst in sorted(par_numero.items()) if len(lst) > 1}


# 2. Inscriptions en double : même NPI inscrit plusieurs fois au même concours (INC-203)
def inscriptions_en_double(requetes):
    par_cle = defaultdict(list)
    for r in inscriptions(requetes):
        if r["statut"] == 201:
            par_cle[(r["npi"], r["concours"])].append(r)
    return {k: sorted(lst, key=lambda r: r["debut"]) for k, lst in sorted(par_cle.items()) if len(lst) > 1}


# 2 bis. Même NPI inscrit à deux concours du même jour (règle également violée par la concurrence)
def inscriptions_meme_jour(requetes):
    par_cle = defaultdict(dict)
    for r in inscriptions(requetes):
        if r["statut"] == 201 and r.get("concours") in CONCOURS:
            jour = CONCOURS[r["concours"]]["date_epreuve"]
            par_cle[(r["npi"], jour)].setdefault(r["concours"], r)
    return {k: v for k, v in sorted(par_cle.items()) if len(v) > 1}


# 3. Lenteur du service d'identification (INC-206)
def periode_identite_lente(appels, requetes):
    lents = [a for a in appels if a["ms"] >= SEUIL_IDENTITE_MS]
    if not lents:
        return None
    par_req = {r["req"]: r for r in requetes}
    touchees = {a["req"] for a in lents}
    debut = min(a["debut"] for a in lents)
    fin = max(a["fin"] for a in lents)
    par_type = defaultdict(int)
    for req in touchees:
        r = par_req.get(req)
        par_type[type_requete(r) if r else "inconnu"] += 1
    # Requêtes bloquées pendant la période (toutes routes) : en cours pendant la fenêtre et >= 5 s
    bloquees = [r for r in requetes if r["ms"] >= SEUIL_IDENTITE_MS and r["debut"] < fin and r["fin"] > debut]
    return {
        "debut": debut, "fin": fin, "duree": fin - debut,
        "nb_appels_lents": len(lents), "nb_requetes_touchees": len(touchees),
        "par_type": dict(par_type), "ms_max": max(a["ms"] for a in lents),
        "ms_moyen": round(mean(a["ms"] for a in lents)),
        "nb_requetes_5s_toutes_routes": len(bloquees),
        "inscriptions_pendant": [r for r in inscriptions(requetes) if r["req"] in touchees and r["statut"] == 201],
    }


def type_requete(r):
    if r["methode"] == "POST" and r["chemin"] == "/api/inscriptions":
        return "POST /api/inscriptions"
    if r["chemin"].endswith("/convocation"):
        return "GET /api/inscriptions/{id}/convocation"
    if RE_LISTE.match(r["chemin"]):
        return "GET /api/centres/{code}/inscrits"
    return f"{r['methode']} {r['chemin'].split('?')[0]}"


# 4. Refus à tort pour clôture (INC-204) : refus « closes » alors que la clôture réelle n'est pas passée
def refus_cloture_a_tort(requetes):
    resultat = defaultdict(list)
    for r in inscriptions(requetes):
        if "Inscriptions closes" not in r.get("erreur", ""):
            continue
        c = CONCOURS.get(r.get("concours"))
        if c and r["debut"] <= c["cloture_utc"]:
            resultat[r["concours"]].append(r)
    return dict(resultat)


def refus_cloture_legitimes(requetes):
    return [r for r in inscriptions(requetes)
            if "Inscriptions closes" in r.get("erreur", "")
            and r["debut"] > CONCOURS[r["concours"]]["cloture_utc"]]


# 5. Refus à tort pour l'âge (INC-205) : âge en années révolues au 31/12 de l'année du concours
def age_au_31_decembre(naissance, annee):
    # Au 31 décembre, l'anniversaire de l'année est toujours passé : âge = différence des années.
    return annee - naissance.year


def refus_age_a_tort(requetes):
    resultat = []
    toutes = inscriptions(requetes)
    for r in toutes:
        if "Âge limite" not in r.get("erreur", "") or "naissance" not in r:
            continue
        naissance = date.fromisoformat(r["naissance"])
        annee = CONCOURS[r["concours"]]["date_epreuve"].year
        age = age_au_31_decembre(naissance, annee)
        if age <= AGE_MAX:
            fin_dec = date(annee, 12, 31)
            calcul_bug = (fin_dec - naissance).days / 365
            inscrit_ensuite = any(x["statut"] == 201 and x["npi"] == r["npi"] and x["concours"] == r["concours"]
                                  and x["fin"] > r["fin"] for x in toutes)
            resultat.append({**r, "age": age, "calcul_bug": calcul_bug, "inscrit_ensuite": inscrit_ensuite})
    return resultat


# 6. Liste des inscrits par centre (INC-207)
def stats_liste_inscrits(requetes):
    par_centre = defaultdict(list)
    for r in requetes:
        m = RE_LISTE.match(r["chemin"]) if r["methode"] == "GET" else None
        if m:
            par_centre[m.group("centre")].append(r)
    stats = {}
    for centre, lst in sorted(par_centre.items()):
        lignes = [int(r["lignes"]) for r in lst if "lignes" in r]
        stats[centre] = {
            "nb": len(lst), "moy_ms": round(mean(r["ms"] for r in lst)), "max_ms": max(r["ms"] for r in lst),
            "max_lignes": max(lignes) if lignes else None,
            "ms_par_ligne": round(sum(r["ms"] for r in lst) / sum(lignes), 1) if lignes and sum(lignes) else None,
        }
    return stats


# Bonus : recherches suspectes (injection SQL), puis toute l'activité des IP concernées
def recherches_suspectes(requetes):
    resultat = []
    for r in requetes:
        if not r["chemin"].startswith("/api/inscrits/recherche"):
            continue
        nom = unquote_plus(r["chemin"].split("nom=", 1)[1]) if "nom=" in r["chemin"] else ""
        if RE_SQL_SUSPECT.search(nom) or r["statut"] >= 500:
            resultat.append({**r, "nom_decode": nom})
    return resultat


def activite_ips(requetes, ips):
    return [r for r in requetes if r["ip"] in ips]


def fmt_ms(ms):
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms} ms"


def rapport_texte(chemin, requetes, appels, ignorees):
    out = []
    p = out.append
    titre = lambda t: (p(""), p("=" * 78), p(t), p("=" * 78))

    toutes = sorted(requetes + appels, key=lambda x: x["fin"])
    p(f"Journal analysé : {chemin}")
    p(f"Période couverte (heure du Bénin) : {heure_benin(toutes[0]['fin'])} -> {heure_benin(toutes[-1]['fin'])}")
    p(f"Requêtes : {len(requetes)} ; appels au service d'identification : {len(appels)} ; lignes non reconnues : {len(ignorees)}")
    ins = inscriptions(requetes)
    p(f"POST /api/inscriptions : {len(ins)} dont {sum(r['statut'] == 201 for r in ins)} acceptées (201)")

    titre("1. Numéros de table attribués plusieurs fois (INC-201, INC-202)")
    doubles = numeros_en_double(requetes)
    nb_surnum = sum(len(v) - 1 for v in doubles.values())
    p(f"{len(doubles)} numéros attribués plusieurs fois, soit {nb_surnum} attributions en trop.")
    for numero, lst in doubles.items():
        p(f"  {numero} x{len(lst)}")
        for r in lst:
            p(f"    {heure_benin(r['fin'])}  npi={r['npi']}  {r['concours']:<7}  durée {fmt_ms(r['ms'])}  [req:{r['req']}]")

    titre("2. Inscriptions en double (même NPI, même concours) (INC-203)")
    dbl = inscriptions_en_double(requetes)
    p(f"{len(dbl)} candidats inscrits plusieurs fois au même concours, soit {sum(len(v) - 1 for v in dbl.values())} inscriptions en trop.")
    for (npi, concours), lst in dbl.items():
        ecart = (lst[1]["debut"] - lst[0]["debut"]).total_seconds()
        p(f"  npi={npi} {concours} : {', '.join(r['numero'] for r in lst)}  (2e envoi {ecart:.0f} s après le 1er)")
        for r in lst:
            p(f"    {heure_benin(r['fin'])}  {r['numero']}  durée {fmt_ms(r['ms'])}  ip={r['ip']}  [req:{r['req']}]")
    mj = inscriptions_meme_jour(requetes)
    p(f"Inscrits à deux concours du même jour malgré la règle : {len(mj)}")
    for (npi, jour), par_c in mj.items():
        p(f"  npi={npi} épreuve du {jour:%d/%m/%Y} : " + ", ".join(f"{c} {r['numero']} ({heure_benin(r['fin'])})" for c, r in par_c.items()))

    titre("3. Service d'identification >= 5 s (INC-206)")
    per = periode_identite_lente(appels, requetes)
    if per:
        p(f"Période : du {heure_benin(per['debut'])} au {heure_benin(per['fin'])} (durée {str(per['duree']).split('.')[0]})")
        p(f"Appels lents : {per['nb_appels_lents']} (moyenne {fmt_ms(per['ms_moyen'])}, max {fmt_ms(per['ms_max'])})")
        p(f"Requêtes touchées : {per['nb_requetes_touchees']}")
        for t, n in sorted(per["par_type"].items(), key=lambda x: -x[1]):
            p(f"  {n:>4}  {t}")
        p(f"Requêtes de 5 s ou plus toutes routes confondues dans la période : {per['nb_requetes_5s_toutes_routes']}")
        p(f"Inscriptions enregistrées pendant la période : {len(per['inscriptions_pendant'])} "
          f"(dont numéros en double : {sum(1 for r in per['inscriptions_pendant'] if r['numero'] in doubles)})")
    else:
        p("Aucun appel lent.")

    titre("4. Refus à tort pour clôture (INC-204)")
    rc = refus_cloture_a_tort(requetes)
    for concours, lst in rc.items():
        c = CONCOURS[concours]
        p(f"{concours} (clôture réelle {heure_benin(c['cloture_utc'])}) : {len(lst)} refus à tort, "
          f"{len({r['npi'] for r in lst})} candidats distincts")
        p(f"  premier : {heure_benin(min(r['debut'] for r in lst))}, dernier : {heure_benin(max(r['debut'] for r in lst))}")
        npis = {r["npi"] for r in lst}
        deja = {npi for npi in npis
                if any(x["statut"] == 201 and x["npi"] == npi and x["concours"] == concours for x in ins)}
        p(f"  dont {len(deja)} candidats déjà inscrits plus tôt (simple nouvel envoi, sans préjudice)")
        p(f"  => {len(npis - deja)} candidats privés d'inscription "
          f"({sum(1 for r in lst if r['npi'] not in deja)} refus)")
    if not rc:
        p("Aucun refus à tort.")
    p(f"Refus « clos » légitimes (après la clôture réelle) : {len(refus_cloture_legitimes(requetes))}")

    titre("5. Refus à tort pour l'âge (INC-205)")
    ra = refus_age_a_tort(requetes)
    p(f"{len(ra)} refus à tort, {len({r['npi'] for r in ra})} candidats distincts "
      f"(âge réel <= {AGE_MAX} ans au 31/12, mais jours/365 > {AGE_MAX}).")
    for r in sorted(ra, key=lambda r: r["fin"]):
        p(f"  {heure_benin(r['fin'])}  npi={r['npi']}  né le {date.fromisoformat(r['naissance']):%d/%m/%Y}  {r['concours']:<7} "
          f"âge {r['age']} ans (calcul bugué {r['calcul_bug']:.3f})  inscrit ensuite : {'oui' if r['inscrit_ensuite'] else 'non'}")

    titre("6. Liste des inscrits par centre (INC-207)")
    p(f"{'Centre':<7}{'appels':>7}{'moyenne':>10}{'max':>10}{'max lignes':>12}{'ms/ligne':>10}")
    for centre, s in stats_liste_inscrits(requetes).items():
        p(f"{centre:<7}{s['nb']:>7}{fmt_ms(s['moy_ms']):>10}{fmt_ms(s['max_ms']):>10}{s['max_lignes'] or '-':>12}{s['ms_par_ligne'] or '-':>10}")
    p("La durée croît avec le nombre de lignes : une requête par inscrit (N+1), sans index.")

    titre("Bonus : recherches suspectes (/api/inscrits/recherche)")
    rs = recherches_suspectes(requetes)
    if not rs:
        p("Rien de suspect.")
    ips = sorted({r["ip"] for r in rs})
    p(f"{len(rs)} requêtes suspectes depuis {', '.join(ips)}. Activité complète de ces IP :")
    for r in activite_ips(requetes, set(ips)):
        nom = unquote_plus(r["chemin"].split("nom=", 1)[1]) if "nom=" in r["chemin"] else r["chemin"]
        p(f"  {heure_benin(r['fin'])}  ip={r['ip']}  {r['methode']} statut={r['statut']}  lignes={r.get('lignes', '-')}  {nom!r}")
        if r.get("erreur"):
            p(f"      erreur : {r['erreur']}")
    exfil = [r for r in rs if int(r.get("lignes", 0) or 0) > 50]
    if exfil:
        p(f"Lignes renvoyées au-delà de la limite de 50 : {max(int(r['lignes']) for r in exfil)} "
          f"(requête UNION sur candidats : NPI, nom, date de naissance).")
    return "\n".join(out)


def rapport_json(requetes, appels):
    def ser(o):
        if isinstance(o, datetime):
            return o.astimezone(BENIN).isoformat()
        if isinstance(o, (date, timedelta)):
            return str(o)
        raise TypeError(type(o))

    per = periode_identite_lente(appels, requetes)
    data = {
        "numeros_en_double": {k: [r["npi"] for r in v] for k, v in numeros_en_double(requetes).items()},
        "inscriptions_en_double": [{"npi": k[0], "concours": k[1], "numeros": [r["numero"] for r in v]}
                                   for k, v in inscriptions_en_double(requetes).items()],
        "identite_lente": per and {k: v for k, v in per.items() if k != "inscriptions_pendant"},
        "refus_cloture_a_tort": {k: len(v) for k, v in refus_cloture_a_tort(requetes).items()},
        "refus_age_a_tort": [{"npi": r["npi"], "naissance": r["naissance"], "concours": r["concours"]}
                             for r in refus_age_a_tort(requetes)],
        "liste_inscrits": stats_liste_inscrits(requetes),
        "recherches_suspectes": [{"ip": r["ip"], "fin": r["fin"], "nom": r["nom_decode"], "lignes": r.get("lignes")}
                                 for r in recherches_suspectes(requetes)],
    }
    return json.dumps(data, default=ser, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("journal", help="chemin du journal de production")
    parser.add_argument("--json", action="store_true", help="sortie JSON au lieu du rapport texte")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    requetes, appels, ignorees = lire_journal(args.journal)
    print(rapport_json(requetes, appels) if args.json else rapport_texte(args.journal, requetes, appels, ignorees))


if __name__ == "__main__":
    main()
