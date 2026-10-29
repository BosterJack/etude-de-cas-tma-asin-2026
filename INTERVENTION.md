# INTERVENTION — Classement des incidents

Situation au 21 novembre 2026 à 8 h (heure du Bénin) :
- la campagne DOUANES / IMPOTS est **encore ouverte** (clôture le 30/11 à 23 h 59) ;
- la campagne TRESOR est **close** depuis le 20/11 ;
- les épreuves ont lieu les 12/12 et 19/12.

Critères : **gravité** (données corrompues, candidats exclus à tort, blocage du service) × **urgence** (l'incident peut-il se reproduire maintenant ? reste-t-il du temps avant la clôture ou l'épreuve ?).

| Rang | Incident | Gravité | Urgence | Justification |
|---|---|---|---|---|
| 1 | INC-206 Plateforme bloquée 30 min | Critique | Immédiate | Peut se reproduire à chaque lenteur du service d'identification et bloque tous les candidats ; c'est aussi lui qui agrandit la fenêtre de concurrence à l'origine de 201, 202 et 203. |
| 2 | INC-201 Numéro de table en double | Critique | Immédiate | Corruption de données encore possible à chaque inscription simultanée ; deux candidats sur une même place le jour de l'épreuve. |
| 3 | INC-202 Lokossa : 307 inscrits pour 300 places | Critique | Haute | Dépassement de capacité, même cause que 201 ; les données sont déjà touchées et il faut une décision métier avant les convocations. |
| 4 | INC-203 Double inscription (double clic) | Majeure | Haute | Doublons en base qui faussent aussi le décompte des places (202) ; même cause, même correctif. |
| 5 | INC-204 Clôture du Trésor une heure trop tôt | Majeure | Haute | Des candidats ont été exclus à tort (préjudice, risque de recours) ; le même bug fermera DOUANES et IMPOTS une heure trop tôt le 30/11. |
| 6 | INC-205 Refus à tort pour l'âge | Majeure | Moyenne | Exclusion à tort de candidats éligibles, mais le nombre de personnes touchées est limité ; à corriger et à recontacter les candidats concernés avant le 30/11. |
| 7 | INC-207 Liste des inscrits de Cotonou en plus de 40 s | Mineure | Moyenne | Lenteur d'un écran interne, sans perte de données et avec un contournement possible ; à corriger avant l'édition des listes du jour d'épreuve. |
| 8 | INC-208 Inscription impossible à IMPOTS après DOUANES | — | — | **Comportement conforme** : les deux épreuves ont lieu le même jour (12/12) et la règle l'interdit. Pas d'anomalie : on répond au candidat. |

Liens pressentis (à confirmer par l'analyse) : 201, 202 et 203 ont une cause commune (aucune transaction, aucun verrou, aucune contrainte d'unicité), et 206 l'aggrave en rallongeant le traitement. 204 et 205 sont des erreurs de règle métier, indépendantes des précédentes.

---

## Mise à jour après analyse

Le classement ci-dessus est celui du premier commit, fait avant l'analyse détaillée. Il est conservé tel quel. L'analyse le confirme, avec un ajout :

| Rang | Incident | Pourquoi |
|---|---|---|
| **0** | **Non signalé : injection SQL sur la recherche par nom** | Le 20/11 à 04:13, une IP externe a extrait NPI, nom et date de naissance des **18 535** candidats. C'est une violation de données personnelles, à traiter dans l'heure et à notifier. Voir [docs/incident-securite-recherche.md](docs/incident-securite-recherche.md). |
| 1 à 4 | INC-206, 201, 202, 203 | Confirmés : **une seule cause** (appel d'identité sans délai, entre lecture et écriture, sans verrou ni contrainte). Un seul correctif, plus une reprise des données. |
| 5 | INC-204 | 94 candidats privés d'inscription au Trésor. **Échéance ferme : le 30/11**, sinon DOUANES et IMPOTS fermeront aussi à 22 h 59. |
| 6 | INC-205 | 36 candidats refusés à tort, à recontacter avant le 30/11. |
| 7 | INC-207 | N+1 confirmé (18,5 ms par ligne). |
| 8 | INC-208 | Conforme, aucune correction. |

Détail des causes : [docs/causes-racines.md](docs/causes-racines.md).
