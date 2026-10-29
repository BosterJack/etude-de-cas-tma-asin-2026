# Causes racines et liens entre incidents

Sources : dossier technique (section 3 du sujet), journal du 18/11 01:00 au 21/11 08:00,
export de la base du 21/11 08:00. Chiffres produits par `analyse/analyse_journal.py`
(résultats complets dans `analyse/resultats.txt`) et recoupés avec la base.
Toutes les heures sont en heure du Bénin (UTC+1).

## Vue d'ensemble

```
                 Client HTTP sans délai d'attente (config. par défaut)
                 + appel d'identité placé ENTRE le calcul (étapes 4-6) et l'écriture (étape 8)
                                          |
     service d'identification lent        |
     le 19/11, 09:09 -> 09:39  ---------> INC-206  requêtes bloquées 20 à 62 s
                                          |
                    fenêtre de 20 à 62 s entre « lire l'état » et « écrire »
                    sans transaction, sans verrou, sans contrainte d'unicité
                 /                        |                          \
        INC-201                       INC-202                       INC-203
  numero = max + 1 lu par         COUNT(*) < capacité lu         le candidat reclique ;
  plusieurs requêtes à la fois    par 11 requêtes à la fois      le doublon passe l'étape 4

  INC-204 : heure locale du serveur comparée à une valeur UTC      (indépendant)
  INC-205 : âge = jours / 365, décimal                             (indépendant)
  INC-207 : N+1 requêtes, sans index                               (indépendant)
  INC-208 : comportement conforme à la règle du « même jour »      (pas une anomalie)
  Non signalé : injection SQL sur la recherche par nom             (indépendant, le plus grave)
```

**Le point clé :** 201, 202, 203 et 206 ont une même cause de conception. La lenteur du
service d'identification n'est que le **déclencheur**. Elle a élargi une fenêtre de
concurrence qui existe en permanence, comme le montre N-0574 : deux requêtes à la même
seconde le 18/11 à 16:42, hors de toute lenteur, ont produit un doublon en 258 ms.

---

## INC-206 : plateforme bloquée le 19/11 au matin

- **Faits.** Du **19/11 09:09:48 au 09:39:49** (30 min), 60 appels au service d'identification
  ont duré entre 5,2 s et **61,7 s** (38 s en moyenne). Les **60 requêtes touchées** sont
  41 inscriptions et 19 convocations, exactement les deux routes qui appellent ce service.
  Les autres routes (`/api/concours`, `/api/centres`) sont restées rapides.
- **Cause racine.** Le client HTTP est utilisé « dans sa configuration par défaut », donc
  sans délai d'attente : chaque requête attend le service aussi longtemps qu'il le faut.
  La règle « au-delà de 5 s, inscription en attente de vérification » n'est pas implémentée.
  Aucune requête n'a abouti en « en attente » dans le journal.
- **Facteur aggravant.** La convocation rappelle le service d'identification à chaque
  affichage, alors que le nom et les prénoms sont déjà dans `candidats` : une dépendance
  externe inutile sur une page de consultation.
- **Correction.** `inscriptions/client_identite.py` : délai total plafonné à 5 s, et statut
  `en_attente_verification` si le service est lent, en erreur ou injoignable. L'appel est
  sorti de la transaction (`inscriptions/service.py`). Pour la convocation, lire `candidats`.

## INC-201 : numéro de table en double

- **Faits.** **10 numéros** attribués plusieurs fois (22 attributions en trop). 9 d'entre
  eux datent de la fenêtre du 19/11, entre 09:11 et 09:34 : L-0297 ×5, L-0298 ×6, P-0464 ×2
  (le signalement), C-3305, C-3306, C-3308, C-3311 et C-3313 ×3, C-3309 ×2. Le 10e est
  N-0574 ×2, le 18/11 à 16:42:07. La base contient exactement les mêmes doublons.
- **Cause racine.** Le numéro vaut « plus grand numéro du centre + 1 » (étape 6), lu sans
  verrou, puis écrit à l'étape 8. Toutes les requêtes présentes dans la fenêtre lisent le
  même maximum. Aucune contrainte d'unicité ne rattrape l'erreur.
- **Lien avec 206.** L'appel d'identité, entre l'étape 6 et l'étape 8, a fait passer cette
  fenêtre de quelques millisecondes à 20-60 s. 30 des 41 inscriptions de la période ont reçu
  un numéro déjà pris.

## INC-202 : Lokossa, 307 inscrits pour 300 places

- **Faits.** 296 inscrits jusqu'au 15/11. Le 19/11 entre 09:11:01 et 09:11:51, **11
  requêtes** pour Lokossa (toutes IMPOTS) arrivent en 50 s. Toutes passent le contrôle de
  capacité, alors qu'il ne restait que 4 places : 307 inscrits, soit 7 de trop. Ces 11
  inscriptions sont aussi celles des numéros L-0297 et L-0298 (INC-201).
- **Cause racine.** Même cause que 201 : `COUNT(*) < capacité` (étape 5) est lu sans
  verrou, longtemps avant l'écriture.
- **Reprise.** Aucune suppression. Classement par heure d'arrivée et décision à demander :
  voir [decision-lokossa.md](decision-lokossa.md).

## INC-203 : double inscription après un double clic

- **Faits.** **7 candidats** inscrits deux fois au même concours, avec le même numéro.
  6 cas datent du 19/11 entre 09:13 et 09:34 : le second envoi part **6 à 13 s** après le
  premier, depuis la même IP, alors que le premier attend encore le service d'identification.
  Le 7e cas est N-0574 : deux envois à la même seconde.
- **Cause racine.** L'étape 4 (« déjà inscrit ? ») est lue sans verrou. Il n'y a pas de
  contrainte `UNIQUE (npi, concours_id)`, et rien ne rend l'envoi idempotent.
- **Lien avec 206.** Une page qui ne répond pas pousse le candidat à recliquer.
  L'interface devrait aussi désactiver le bouton après l'envoi.

## INC-204 : clôture du Trésor dès 22 h 59

- **Faits.** **147 refus « Inscriptions closes »** entre 22:59:05 et 23:58:58 le 20/11,
  pour 100 candidats. 6 étaient déjà inscrits (nouvel envoi). **94 candidats ont donc été
  privés d'inscription.** Les 80 refus après 23:59 sont légitimes.
- **Cause racine.** `concours.cloture` est en UTC (22:59 UTC = 23:59 au Bénin). Le serveur
  compare son **heure locale** (Bénin) à cette valeur, comme si c'était une heure locale :
  la clôture tombe une heure trop tôt.
- **Risque immédiat.** DOUANES et IMPOTS (clôture le 30/11 à 23:59) seront fermés à
  22:59 si le correctif n'est pas en production d'ici là.
- **Correction.** Comparaison entre instants avec fuseau (`inscriptions/regles.py`). Une
  heure sans fuseau est refusée. À décider par la Direction des concours : rouvrir
  le Trésor pour les 94 candidats (liste fournie par l'analyse).

## INC-205 : refus à tort pour l'âge

- **Faits.** **36 candidats** refusés à tort : 34 nés en 1991 (35 ans au 31/12/2026) et
  2 nés début janvier 1992 (34 ans). Aucun ne s'est inscrit ensuite. Le candidat du
  signalement (né le 20/06/1991) en fait partie.
- **Cause racine.** L'âge est calculé comme « jours / 365 » puis comparé à 35. Le résultat
  est décimal (35,55 > 35) et compte un jour de trop tous les 4 ans (années bissextiles).
  La règle est « au plus 35 ans au 31 décembre », c'est-à-dire en années révolues.
- **Correction.** Âge = année du concours − année de naissance (`regles.age_au_31_decembre`).
  Il faut recontacter les 36 candidats avant le 30/11.

## INC-207 : liste des inscrits de Cotonou en plus de 40 s

- **Faits.** Cotonou : 25,4 s en moyenne et **46,5 s au maximum** (2 408 lignes). La durée
  est proportionnelle au nombre de lignes, environ **18,5 ms par ligne dans tous les
  centres**. À 5 000 inscrits, on dépasserait 90 s.
- **Cause racine.** Une requête `candidats` par inscription (N+1), sur une table de 19 303
  lignes sans index sur `npi` (« clés primaires uniquement ») : chaque requête parcourt
  toute la table.
- **Correction.** Une seule requête avec jointure, et des index `candidats(npi)` et
  `inscriptions(centre_id, concours_id)`. Testé : 5 000 inscrits en moins de 2 s.

## INC-208 : impossible de s'inscrire aux impôts après les douanes

**Pas une anomalie.** DOUANES et IMPOTS ont leur épreuve le même jour (12/12/2026), et la
règle interdit de s'inscrire à deux concours du même jour. Le journal montre 3 refus de ce
type, tous justifiés. Action : répondre au candidat via le support, sans rien corriger.

## Incident non signalé : injection SQL et vol de données

Voir [incident-securite-recherche.md](incident-securite-recherche.md). Cause : la recherche
par nom construit sa requête SQL par concaténation. Sans lien technique avec les autres
incidents, c'est pourtant **le plus grave** : il touche des données personnelles.
