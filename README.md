# Étude de cas TMA : inscriptions aux concours administratifs

Intervention de tierce maintenance applicative sur la plateforme d'inscription aux concours
(DOUANES, IMPOTS, TRESOR). Le travail suit cet ordre : prioriser, établir les faits,
trouver les causes, corriger, réparer les données, rendre compte.

Toutes les commandes se lancent depuis la racine du dépôt.

## Démarrage rapide avec Docker (recommandé)

Seul Docker est nécessaire. PostgreSQL 16 est fourni.

```bash
docker compose run --rm tests-postgres   # les 39 tests, correction sur PostgreSQL (comme en production)
docker compose run --rm tests            # les mêmes tests, correction sur SQLite
docker compose run --rm analyse          # l'analyse du journal
docker compose run --rm reprise          # le script SQL appliqué DEUX fois à l'export, sur PostgreSQL
docker compose down -v                   # tout arrêter ; les bases repartiront de zéro
```

Pour la reprise, le second passage doit afficher `INSERT 0 0`, `DELETE 0` et `UPDATE 0`,
ce qui prouve que le script peut être rejoué. La base reste accessible pour l'inspecter :
`localhost:55432`, base `inscriptions`, utilisateur et mot de passe `tma`.

## Sans Docker

Python 3.10 ou plus suffit, sans rien installer : la correction tourne alors sur SQLite,
inclus dans Python. Il faut une version de SQLite égale ou supérieure à 3.35 (pour
`RETURNING`) ; c'est le cas des versions de Python 3.10 et suivantes pour Windows et macOS.
Pour vérifier : `python -c "import sqlite3; print(sqlite3.sqlite_version)"`.
Les commandes sont détaillées dans les sections ci-dessous.

## Synthèse par incident

| Incident | Verdict | Cause racine | Correction | Preuve |
|---|---|---|---|---|
| **INC-206** Plateforme bloquée | Anomalie | Appel d'identité sans délai d'attente (client HTTP par défaut) | `inscriptions/client_identite.py` : 5 s au maximum, sinon « en attente de vérification » ; appel sorti de la transaction | `test_service.py` : `TestServiceIdentiteLent` |
| **INC-201** Numéro en double | Anomalie | « max + 1 » lu sans verrou, longtemps avant l'écriture | Transaction sous verrou (`service.py`, `depot.py`) et index unique (centre, numéro) | `test_concurrence.py` : 100 inscriptions simultanées |
| **INC-202** Lokossa 307/300 | Anomalie | Capacité lue sans verrou | Même transaction ; données : `docs/decision-lokossa.md` | `test_concurrence.py` : 60 demandes pour 20 places |
| **INC-203** Double inscription | Anomalie | Contrôle du doublon sans verrou, pas de contrainte d'unicité | Même transaction et index unique (npi, concours) | `test_concurrence.py` : 15 doubles clics simultanés |
| **INC-204** Clôture à 22 h 59 | Anomalie | Heure locale du serveur comparée à une valeur UTC | `regles.inscriptions_closes` : comparaison d'instants avec fuseau | `test_regles.py` : `TestCloture` |
| **INC-205** Refus pour l'âge | Anomalie | Âge = jours / 365, décimal | `regles.age_au_31_decembre` : années révolues | `test_regles.py` : `TestAge` |
| **INC-207** Liste lente | Anomalie | Une requête par inscrit (N+1), sans index | Une requête avec jointure et index | `test_service.py` : 5 000 inscrits en moins de 2 s |
| **INC-208** IMPOTS après DOUANES | **Conforme** | Règle du même jour (épreuves le 12/12) | Aucune : réponse au candidat | `test_service.py` : `test_inc_208_…` |
| Non signalé | Sécurité | Recherche par nom construite par concaténation SQL | Mesures immédiates : `docs/incident-securite-recherche.md` | `test_analyse_journal.py` : détection |

201, 202, 203 et 206 ont **une seule cause** : l'appel d'identité, devenu lent, élargissait
une fenêtre de concurrence sans verrou ni contrainte. Détail dans `docs/causes-racines.md`.

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
python -m unittest discover -s tests -t . -v                 # correction sur SQLite

# Correction sur un PostgreSQL déjà installé (base vide dédiée ; pip install "psycopg[binary]")
BASE_TEST=postgres PG_URL=postgresql://tma:tma@localhost:5432/tests python -m unittest discover -s tests -t . -v
```

Attention : sur PostgreSQL, chaque test recrée les tables de la base indiquée. Il faut une
base vide dédiée aux tests, et `max_connections` d'au moins 150 pour les tests de concurrence.

39 tests, environ 40 s :

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

Le script a été vérifié sur **PostgreSQL** (appliqué deux fois à l'export, mêmes résultats)
et sur SQLite (`tests/test_reprise_donnees.py`). Il n'est pas compatible MySQL : MySQL ne
connaît ni `CREATE INDEX IF NOT EXISTS` ni l'opérateur `||` de concaténation.

On applique d'abord inscriptions en double (étape 1), puis numéros en double (étape 2),
alors que le sujet les cite dans l'autre ordre. Supprimer d'abord les doublons évite
d'attribuer un nouveau numéro à une ligne qui va disparaître : sur les 22 attributions en
trop, 7 sont des doublons et seules 15 sont à renuméroter.

### Qui prévenir

| Qui | Pourquoi | Liste |
|---|---|---|
| Direction des concours | Valider la reprise ; décider pour Lokossa ; rouvrir ou non le Trésor pour les 94 candidats refusés à tort à la clôture, et recontacter les 36 refusés pour l'âge | `docs/decision-lokossa.md`, `analyse/resultats.txt` |
| 15 candidats renumérotés | Nouveau numéro, nouvelle convocation | table `reprise_renumerotations` |
| 7 candidats inscrits deux fois | Une seule convocation reste valable | table `reprise_inscriptions_supprimees` |
| Chefs de centre de Cotonou, Parakou et Lokossa | Listes d'émargement mises à jour | les deux tables ci-dessus |
| Support / centre d'appels | Réponse type aux candidats concernés | — |
| Exploitation | Sauvegarde et arrêt des inscriptions pendant l'application du script | — |

## 4. Lancer l'API corrigée (facultatif)

```bash
python -m inscriptions.api --db inscriptions.db --identite http://<service-identification> --port 8000
python -m inscriptions.api --db postgresql://tma:tma@localhost:55432/inscriptions --identite http://<service-identification>
```

Routes : `POST /api/inscriptions` (JSON : `npi`, `date_naissance`, `concours`, `centre`) et
`GET /api/centres/{code}/inscrits?concours=…`.

## Architecture

```
├── INTERVENTION.md            priorisation
├── analyse/
│   ├── analyse_journal.py     programme d'analyse du journal
│   └── resultats.txt          sa sortie sur le journal fourni
├── inscriptions/              correction (étapes 4 à 8 de POST /api/inscriptions)
│   ├── regles.py              règles métier pures : âge, clôture, NPI
│   ├── client_identite.py     appel au service d'identification, borné à 5 s
│   ├── depot.py               accès SQL, SQLite ou PostgreSQL
│   ├── service.py             enregistrement transactionnel d'une inscription
│   ├── api.py                 API HTTP minimale
│   ├── schema.sql             schéma SQLite avec contraintes et index
│   └── schema_postgres.sql    le même schéma pour PostgreSQL
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
- **Sous PostgreSQL (production, et service Docker `tests-postgres`).** Dans la même transaction :
  `SELECT … FROM centres WHERE id = $1 FOR UPDATE` (capacité et numéro) et
  `pg_advisory_xact_lock(<npi>)` (doublon et même jour), avec les mêmes index uniques.
  Le verrou porte sur le centre, pas sur toute la base : les centres ne se bloquent pas
  entre eux.
- **Délai de 5 s sur la durée totale de l'appel.** Le `timeout` d'une bibliothèque HTTP
  ne borne en général que chaque lecture réseau. L'appel tourne donc dans un thread
  attendu au plus 5 s.
- **Inscription « en attente de vérification ».** Le numéro de table est attribué et la
  place est comptée. La ligne `candidats` est créée plus tard, à la vérification.
- **Deux bases pour la correction.** PostgreSQL, comme en production (via Docker), et
  SQLite, pour tout exécuter sans rien installer. Le service ne voit qu'une `Connexion`
  commune (`inscriptions/depot.py`) ; seule la façon de verrouiller diffère. Les mêmes
  39 tests passent sur les deux bases.
- **Limites connues.** Le traitement de reprise des inscriptions « en attente » et la
  convocation lue depuis `candidats` sont décrits, mais pas codés : je les ai jugés moins
  prioritaires dans le temps imparti.
