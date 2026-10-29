# INC-202 : Lokossa, décision à demander

**Destinataire de la décision : la Direction des concours.** La TMA ne supprime aucune
inscription : les 307 candidats ont reçu une confirmation et une convocation.

## Constat

| | |
|---|---|
| Capacité du centre | 300 |
| Inscrits avant l'incident | 296 (jusqu'au 15/11) |
| Inscriptions acceptées le 19/11 entre 09:11 et 09:13 | 11 (concours IMPOTS) |
| Places qui restaient | 4 |
| Dépassement | **7** |

## Les 11 inscriptions, par heure d'arrivée

Ordre d'**arrivée** de la requête (journal : heure de fin − durée). Il diffère de l'ordre
d'enregistrement en base (`cree_le`), qui dépend de la vitesse de réponse du service
d'identification : il serait injuste de départager les candidats sur ce critère.

| Rang | Inscription | NPI | Candidat | Arrivée (Bénin) | Numéro après reprise | Situation |
|---:|---:|---|---|---|---|---|
| 1 | 5045 | 8496397796 | TCHOBO Florent Dorcas | 09:11:01.871 | L-0297 | dans la capacité |
| 2 | 5046 | 1230531326 | SODJINOU Hermann Kévin | 09:11:07.847 | L-0299 | dans la capacité |
| 3 | 5047 | 5849598968 | SOSSOU Gildas Ulrich | 09:11:11.145 | L-0300 | dans la capacité |
| 4 | 5049 | 7390181652 | KPADONOU Rosine Aïcha | 09:11:16.244 | L-0301 | dans la capacité |
| 5 | 5052 | 5764074760 | WABI Carine Kévin | 09:11:22.658 | L-0304 | au-delà |
| 6 | 5050 | 6926583899 | KORA Carine | 09:11:26.471 | L-0302 | au-delà |
| 7 | 5048 | 7626262999 | CHABI Sêmêvo | 09:11:32.514 | L-0298 | au-delà |
| 8 | 5054 | 7237864540 | DANSOU Espérance | 09:11:36.417 | L-0306 | au-delà |
| 9 | 5051 | 0804931531 | AKPLOGAN Boris | 09:11:42.659 | L-0303 | au-delà |
| 10 | 5053 | 5004565733 | MONTCHO Wilfried | 09:11:47.322 | L-0305 | au-delà |
| 11 | 5055 | 1168848367 | TCHOBO Boris | 09:11:51.081 | L-0307 | au-delà |

La même liste est produite par la dernière requête de `sql/reprise_donnees.sql` (table
`reprise_lokossa_a_arbitrer`).

## Options

1. **Ajouter 7 places à Lokossa** (une salle de plus). *Recommandé* : aucun candidat n'est
   pénalisé pour une erreur du système, et le concours IMPOTS est le 12/12, ce qui laisse
   le temps d'organiser la salle.
2. **Transférer les 7 derniers arrivés vers un centre proche qui a de la place**, avec leur
   accord. Après reprise : Abomey 509/600, Porto-Novo 782/800, Parakou 614/700.
3. **Annuler les 7 dernières inscriptions.** *Déconseillé* : ces candidats ont reçu une
   confirmation, le risque de recours est réel, et l'inscription au même concours dans un
   autre centre reste possible jusqu'au 30/11.

## Qui prévenir

| Qui | Pourquoi |
|---|---|
| Direction des concours | Décision ci-dessus ; validation de la reprise des données |
| Chef du centre de Lokossa | Effectif réel, et salle supplémentaire selon la décision |
| Les 11 candidats | Selon la décision ; ceux renumérotés reçoivent une nouvelle convocation |
| Support / centre d'appels | Réponse type pour les candidats qui appellent |
