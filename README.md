# Étude de cas TMA : inscriptions aux concours administratifs

Intervention de tierce maintenance applicative sur la plateforme d'inscription aux concours
(DOUANES, IMPOTS, TRESOR). Le travail suit cet ordre : prioriser, établir les faits,
trouver les causes, corriger, réparer les données, rendre compte.

**Prérequis : Python 3.8 ou plus, et rien d'autre** (bibliothèque standard uniquement,
SQLite inclus). Toutes les commandes se lancent depuis la racine du dépôt.

## Lire dans cet ordre

| # | Document | Contenu |
|---|---|---|
| 1 | [INTERVENTION.md](INTERVENTION.md) | Priorisation (premier commit), puis mise à jour après analyse |
| 2 | [analyse/resultats.txt](analyse/resultats.txt) | Sortie du programme d'analyse du journal |
| 3 | [docs/causes-racines.md](docs/causes-racines.md) | Cause de chaque incident et liens entre eux |
| 4 | [docs/rapport-incident-INC-206.md](docs/rapport-incident-INC-206.md) | Rapport d'incident |
| 5 | [docs/decision-lokossa.md](docs/decision-lokossa.md) | INC-202 : liste et décision à demander |
| 6 | [docs/incident-securite-recherche.md](docs/incident-securite-recherche.md) | Bonus : injection SQL et vol de données |

## Les chiffres clés (heure du Bénin)

| Question | Résultat |
|---|---|
| Numéros de table attribués plusieurs fois | 10 numéros (22 attributions en trop), dont P-0464 |
| Inscriptions en double | 7 candidats |
| Service d'identification ≥ 5 s | 19/11 de 09:09:48 à 09:39:49 ; 60 requêtes touchées |
| Refus à tort à la clôture du Trésor | 147 refus, soit 94 candidats privés d'inscription |
| Refus à tort pour l'âge | 36 candidats |
| Liste des inscrits | Cotonou : 25,4 s en moyenne, 46,5 s au maximum ; ~18,5 ms par ligne partout |
| Non signalé | Injection SQL le 20/11 à 04:13 : 18 535 candidats extraits |

## 1. Analyser le journal

```bash
python analyse/analyse_journal.py donnees/journal_production.log
```

Points de méthode :
- Le journal est en UTC ; tout est converti en heure du Bénin (UTC+1).
- Une ligne est écrite à la **fin** de la requête : son début vaut « heure − durée ». La
  période de lenteur commence donc au début du premier appel lent, pas à sa ligne.
- Un refus « clos » est à tort si la requête a commencé avant la clôture réelle
  (22:59 UTC, soit 23:59 au Bénin).
- Un refus pour l'âge est à tort si l'âge en années révolues au 31/12 est d'au plus 35 ans.

## 2. Lancer les tests

```bash
python -m unittest discover -s tests -t . -v
```

38 tests, environ 40 s :

| Fichier | Ce qu'il vérifie |
|---|---|
| `tests/test_regles.py` | Âge (INC-205), clôture et fuseaux (INC-204), format du NPI |
| `tests/test_service.py` | Enregistrement, refus, service d'identification lent ou injoignable (INC-206), liste de 5 000 inscrits en moins de 2 s (INC-207) |
| `tests/test_concurrence.py` | **Requêtes simultanées via l'API HTTP** : capacité jamais dépassée, numéros uniques, double clic, deux concours du même jour |
| `tests/test_reprise_donnees.py` | Le script SQL appliqué à l'export : résultat, **rejouabilité**, contraintes actives, aucune suppression à Lokossa |
| `tests/test_analyse_journal.py` | Les chiffres de l'analyse sur le journal fourni |

## 3. Réparer les données

```bash
# PostgreSQL (production) : après sauvegarde, inscriptions suspendues
psql -v ON_ERROR_STOP=1 -d inscriptions -f sql/reprise_donnees.sql

# Essai sur l'export avec SQLite
python -c "import sqlite3; c = sqlite3.connect('essai.db'); c.executescript(open('donnees/base_inscriptions.sql', encoding='utf-8').read()); c.executescript(open('sql/reprise_donnees.sql', encoding='utf-8').read())"
```

Le script :
1. archive puis supprime les 7 inscriptions en double ;
2. renumérote les 15 inscriptions dont le numéro était déjà pris ;
3. pose les contraintes d'unicité et l'index de la liste ;
4. prépare la liste de Lokossa, **sans rien supprimer**.

Tout se fait dans une transaction. Les tables `reprise_*` gardent la trace de chaque
changement et servent de liste des personnes à prévenir. On peut le relancer sans risque.

## 4. Lancer l'API corrigée (facultatif)

```bash
python -m inscriptions.api --db inscriptions.db --identite http://<service-identification> --port 8000
```

## Architecture

```
├── INTERVENTION.md            priorisation
├── analyse/
│   ├── analyse_journal.py     programme d'analyse du journal
│   └── resultats.txt          sa sortie sur le journal fourni
├── inscriptions/              correction (étapes 4 à 8 de POST /api/inscriptions)
│   ├── regles.py              règles métier pures : âge, clôture, NPI
│   ├── client_identite.py     appel au service d'identification, borné à 5 s
│   ├── depot.py               accès SQL
│   ├── service.py             enregistrement transactionnel d'une inscription
│   ├── api.py                 API HTTP minimale
│   └── schema.sql             schéma avec contraintes et index
├── sql/reprise_donnees.sql    reprise des données, rejouable
├── tests/                     tests unitaires, de concurrence, de reprise, d'analyse
├── docs/                      causes, rapport d'incident, décision Lokossa, sécurité
└── donnees/                   journal et export fournis
```

## Choix techniques

- **Pourquoi le correctif tient sous concurrence.** L'appel d'identité, qui est lent, se
  fait **avant** la transaction. Les étapes 4, 5, 6 et 8 se font ensuite dans une
  transaction `BEGIN IMMEDIATE`, qui prend le verrou d'écriture dès le début : deux
  inscriptions ne peuvent plus lire le même maximum de numéro ni le même nombre
  d'inscrits. Les index uniques sont un filet de sécurité si un autre programme écrivait
  sans passer par ce code.
- **Équivalent PostgreSQL (production).** Dans la même transaction :
  `SELECT … FROM centres WHERE id = $1 FOR UPDATE` (capacité et numéro) et
  `pg_advisory_xact_lock(<npi>)` (doublon et même jour), avec les mêmes index uniques.
  Le verrou porte sur le centre, pas sur toute la base : les centres ne se bloquent pas
  entre eux.
- **Délai de 5 s sur la durée totale de l'appel.** Le `timeout` d'une bibliothèque HTTP
  ne borne en général que chaque lecture réseau. L'appel tourne donc dans un thread
  attendu au plus 5 s.
- **Inscription « en attente de vérification ».** Le numéro de table est attribué et la
  place est comptée. La ligne `candidats` est créée plus tard, à la vérification.
- **SQLite pour la correction.** Le sujet laisse le choix de la base ; SQLite rend tests et
  démonstration exécutables sans rien installer. Le script de reprise vise PostgreSQL et
  reste compatible SQLite, ce qui permet de le tester sur l'export.
- **Limites connues.** Le traitement de reprise des inscriptions « en attente » et la
  convocation lue depuis `candidats` sont décrits, mais pas codés : je les ai jugés moins
  prioritaires dans le temps imparti.
