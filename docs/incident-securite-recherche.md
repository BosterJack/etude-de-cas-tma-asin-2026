# Bonus : incident non signalé, injection SQL et vol des données des candidats

**Gravité : critique. Violation de données personnelles avérée.** Cet incident passe en
tête des priorités (voir la mise à jour de `INTERVENTION.md`).

## Faits (journal, heure du Bénin)

Une seule adresse IP externe, **102.64.217.33**, en un peu plus d'une minute, le **20/11** :

| Heure | Requête `GET /api/inscrits/recherche?nom=` | Réponse | Lecture |
|---|---|---|---|
| 04:12:40 | `KPADONOU` | 200, 390 lignes | Repérage avec une recherche normale |
| 04:13:05 | `'` | **500** : `unterminated quoted string at or near "'%' LIMIT 50"` | L'erreur SQL est renvoyée telle quelle et révèle la structure de la requête : `… LIKE '%<nom>%' LIMIT 50` |
| 04:13:27 | `' OR '1'='1` | 200, 50 lignes | Injection confirmée |
| 04:13:50 | `' UNION SELECT npi, nom, date_naissance FROM candidats --` | 200, **18 535 lignes** | Extraction : `--` neutralise aussi le `LIMIT 50` |
| 04:14:16 | même requête | 200, 18 535 lignes | Seconde extraction |

**18 535 est exactement le nombre de lignes de `candidats` créées avant 04:13:50** (vérifié
sur l'export). L'attaquant a donc récupéré **toute la table**, y compris 13 400 candidats
des campagnes précédentes. Le journal ne montre aucune autre requête de cette IP.

## Ce qui a pu être exposé

- **Avéré :** NPI, nom et date de naissance des **18 535 personnes** de la table `candidats`.
- **Possible :** une injection `UNION` permet de lire tout ce que le compte de base de
  l'application peut lire : inscriptions, centres, autres tables et schémas, selon ses
  droits. Le journal ne montre que ces deux requêtes, mais on ne peut pas l'exclure pour
  d'autres routes vulnérables ni pour des accès hors journal.
- **Conséquence :** le NPI et la date de naissance suffisent à s'inscrire au nom d'un
  autre. Ils servent aussi peut-être d'identifiants sur d'autres services de l'État
  (usurpation d'identité, hameçonnage ciblé).

## Cause

La recherche par nom construit sa requête SQL par concaténation de texte, au lieu
d'utiliser une requête paramétrée. Trois défauts s'ajoutent :
- les erreurs SQL sont renvoyées au client ;
- la route semble accessible sans authentification depuis Internet (IP externe), alors
  que les seuls usages légitimes viennent de l'IP interne 10.20.1.15 ;
- le compte de base a sans doute plus de droits que nécessaire.

Une anomalie est aussi à vérifier : les recherches légitimes renvoient 336 à 419 lignes
alors que la limite annoncée est de 50.

## Mesures immédiates (dans l'heure)

1. **Couper la route** `/api/inscrits/recherche` (ou la restreindre au réseau interne),
   puis la corriger avec une requête paramétrée :
   `SELECT … FROM candidats WHERE nom LIKE ? LIMIT 50`.
2. **Bloquer l'IP 102.64.217.33** au pare-feu, puis rechercher son activité dans **tous**
   les journaux disponibles (serveur web, base, avant le 18/11).
3. **Préserver les preuves** : copie intègre des journaux et de l'état de la base.
4. **Ne plus renvoyer les erreurs SQL** au client (message générique et identifiant de requête).
5. **Changer le mot de passe du compte de base** de l'application, et réduire ses droits
   au strict nécessaire.
6. **Auditer les autres routes** qui prennent un paramètre texte. Vérifier aussi que la
   convocation (`/api/inscriptions/{id}/convocation`, identifiant séquentiel) ne s'affiche
   pas sans contrôle d'identité.

## Qui prévenir

| Qui | Quand |
|---|---|
| RSSI et direction de l'ASIN | Immédiatement |
| Délégué à la protection des données | Immédiatement |
| **APDP** (Autorité de protection des données personnelles du Bénin) | Notification de la violation dans les délais légaux (Code du numérique) ; viser 72 h |
| bjCSIRT (CERT national) | Pour l'analyse et le partage de l'indicateur (IP) |
| Direction des concours | Risque d'inscriptions frauduleuses : surveiller les inscriptions à venir |
| Les 18 535 personnes concernées | Selon l'avis de l'APDP et du délégué : information et vigilance contre l'hameçonnage |
