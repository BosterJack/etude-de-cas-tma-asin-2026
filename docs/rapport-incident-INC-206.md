# Rapport d'incident INC-206 : plateforme bloquée le 19 novembre 2026

| | |
|---|---|
| Signalé par | Exploitation |
| Date de l'incident | 19/11/2026, de 09:09 à 09:40 (heure du Bénin) |
| Gravité | Critique : service d'inscription indisponible, avec corruption de données induite |
| Incidents liés | INC-201, INC-202 et INC-203 (conséquences directes) |
| Statut | Cause identifiée ; correctif codé et testé, à déployer avant le 30/11 |

## Résumé

Pendant 30 minutes, le service national d'identification a répondu en 5 à 62 secondes
au lieu de 0,1 à 0,4 seconde. Notre plateforme l'attendait sans limite de temps : toutes
les inscriptions et toutes les convocations sont restées bloquées. Pendant ce temps, les
inscriptions en cours se sont chevauchées et ont abîmé la base : numéros de table en
double, 7 places de trop à Lokossa, et inscriptions en double après des doubles clics.

## Chronologie (heure du Bénin)

| Heure | Événement |
|---|---|
| 09:09:48 | Début du premier appel lent au service d'identification (5,2 s) |
| 09:10 – 09:15 | Pic : 19 appels lents, jusqu'à 62 s |
| 09:11:01 – 09:11:51 | 11 inscriptions pour Lokossa arrivent et restent bloquées ; elles passent toutes le contrôle de capacité (4 places restantes) |
| 09:11:23 – 09:12:43 | Elles sont enregistrées : L-0297 ×5, L-0298 ×6, 307 inscrits pour 300 places (INC-202) |
| 09:13 – 09:34 | Numéros en double à Cotonou et Parakou (dont P-0464 à 09:21, INC-201) ; 6 candidats renvoient le formulaire 6 à 13 s après le premier envoi (INC-203) |
| 09:15 – 09:40 | 7 à 9 appels lents par tranche de 5 minutes |
| 09:39:49 | Fin du dernier appel lent ; retour à la normale sans intervention |

Le journal ne montre aucune action d'exploitation pendant l'incident. La sortie a été
spontanée : le service d'identification est redevenu rapide.

## Impact chiffré

| Mesure | Valeur |
|---|---|
| Durée | 30 min 01 s |
| Requêtes touchées (appel d'identité de 5 s ou plus) | **60** : 41 inscriptions et 19 convocations |
| Part des inscriptions et convocations de la période | 60 sur 65 (92 %) |
| Attente du candidat | 38 s en moyenne, 62 s au maximum |
| Numéros de table attribués plusieurs fois | 9 numéros (30 des 41 inscriptions de la période) |
| Dépassement de capacité | Lokossa : 307 pour 300 |
| Inscriptions en double | 6 (plus 1 hors période, même cause) |
| Candidats à prévenir après reprise | 15 renumérotés, 7 doublons supprimés, 11 à Lokossa selon la décision |

Les autres pages (liste des concours, liste des centres) sont restées rapides : seules les
routes qui appellent le service d'identification étaient bloquées.

## Cause racine

1. **Déclencheur (externe) :** lenteur du service national d'identification.
2. **Cause racine (interne) :** l'appel se fait avec un client HTTP « dans sa configuration
   par défaut », donc **sans délai d'attente**. La règle du cahier des charges (« au-delà
   de 5 secondes, inscription en attente de vérification ; une lenteur ne doit jamais
   bloquer les candidats ») n'est pas implémentée.
3. **Ce qui a transformé une lenteur en corruption de données :** l'appel d'identité se
   trouve entre la lecture de l'état (étapes 4 à 6 : doublon, capacité, numéro) et
   l'écriture (étape 8), sans transaction ni verrou, et sans contrainte d'unicité en base.
   La fenêtre de concurrence est passée de quelques millisecondes à près d'une minute.
4. **Aggravant :** la convocation rappelle le service d'identification à chaque
   affichage, alors que les nom et prénoms sont déjà dans `candidats`.

## Correction

- **Client d'identité** (`inscriptions/client_identite.py`) : délai **total** plafonné à
  5 s. Au-delà, ou si le service est en erreur ou injoignable, l'inscription est
  enregistrée en `en_attente_verification`.
- **Ordre des étapes** (`inscriptions/service.py`) : l'appel d'identité se fait d'abord,
  hors transaction. Les étapes 4, 5, 6 et 8 suivent dans une transaction exclusive. En
  PostgreSQL : `SELECT … FOR UPDATE` sur le centre et `pg_advisory_xact_lock` sur le NPI.
- **Base** : index uniques `(centre_id, numero_table)` et `(npi, concours_id)`
  (`sql/reprise_donnees.sql`).
- **Tests** : service lent → réponse en moins de 1,5 s avec un délai de 0,5 s ; 60
  requêtes simultanées sur 20 places → exactement 20 acceptées, numéros L-0001 à L-0020 ;
  15 doubles clics simultanés → 1 inscription.
- **Données** : reprise par `sql/reprise_donnees.sql` (rejouable, testée sur l'export).

## Actions pour éviter que l'incident se reproduise

| Action | Responsable | Échéance |
|---|---|---|
| Déployer le correctif (délai de 5 s, transaction, index) | TMA | Avant le 30/11 (clôture DOUANES/IMPOTS) |
| Traitement de reprise des inscriptions « en attente » : revérifier, puis créer le candidat | TMA | Avec le déploiement |
| Convocation : lire `candidats` au lieu d'appeler le service d'identification | TMA | Avec le déploiement |
| Coupe-circuit : après N échecs, ne plus appeler le service pendant 30 s et passer directement en attente | TMA | Sprint suivant |
| Désactiver le bouton « Valider » après envoi, et clé d'idempotence par envoi | TMA | Sprint suivant |
| Alerte de supervision : p95 de l'appel d'identité > 2 s, ou plus de 5 WARN en 5 minutes | Exploitation | Immédiat |
| Délai de réponse attendu du service d'identification, et contact d'astreinte | Direction / fournisseur | À négocier |
| Revue de code : tout appel externe doit avoir un délai d'attente explicite | TMA | Règle permanente |
