-- =============================================================================
-- Reprise des données : INC-201 (numéros en double), INC-203 (inscriptions en
-- double), INC-202 (Lokossa, préparation de la décision), puis contraintes.
--
-- Cible : la base de production (PostgreSQL) ; testé aussi sur SQLite (même syntaxe).
--   psql -v ON_ERROR_STOP=1 -d inscriptions -f sql/reprise_donnees.sql
--   sqlite3 inscriptions.db < sql/reprise_donnees.sql
--
-- Rejouable : chaque étape ne traite que ce qui reste à traiter, et tout se fait
-- dans une seule transaction (tout ou rien). Rien n'est perdu : chaque ligne
-- supprimée ou renumérotée est d'abord tracée dans une table reprise_*.
--
-- AVANT de l'appliquer en production : sauvegarde complète, et arrêt des
-- inscriptions le temps du script (quelques secondes), sinon un nouvel envoi
-- concurrent peut recréer un doublon entre l'étape 1 et la pose des index.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 0. Tables de traçabilité (servent aussi à prévenir les candidats concernés)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reprise_inscriptions_supprimees (
  id INTEGER PRIMARY KEY,
  concours_id INTEGER NOT NULL,
  centre_id INTEGER NOT NULL,
  npi VARCHAR(10) NOT NULL,
  numero_table VARCHAR(6) NOT NULL,
  statut VARCHAR(30) NOT NULL,
  cree_le TIMESTAMP NOT NULL,
  doublon_de INTEGER NOT NULL,          -- inscription conservée
  motif VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS reprise_renumerotations (
  inscription_id INTEGER PRIMARY KEY,
  npi VARCHAR(10) NOT NULL,
  ancien_numero VARCHAR(6) NOT NULL,
  nouveau_numero VARCHAR(6) NOT NULL
);

-- -----------------------------------------------------------------------------
-- 1. INC-203 : inscriptions en double (même NPI, même concours).
--    On garde la première enregistrée (plus petit id) ; les autres sont archivées
--    puis supprimées. Ce sont de vrais doublons : même candidat, même numéro.
-- -----------------------------------------------------------------------------
INSERT INTO reprise_inscriptions_supprimees
  (id, concours_id, centre_id, npi, numero_table, statut, cree_le, doublon_de, motif)
SELECT i.id, i.concours_id, i.centre_id, i.npi, i.numero_table, i.statut, i.cree_le,
       d.conservee_id, 'INC-203 inscription en double'
FROM inscriptions i
JOIN (SELECT npi, concours_id, MIN(id) AS conservee_id
      FROM inscriptions
      GROUP BY npi, concours_id
      HAVING COUNT(*) > 1) d
  ON d.npi = i.npi AND d.concours_id = i.concours_id
WHERE i.id <> d.conservee_id
  AND NOT EXISTS (SELECT 1 FROM reprise_inscriptions_supprimees s WHERE s.id = i.id);

DELETE FROM inscriptions
WHERE id IN (SELECT id FROM reprise_inscriptions_supprimees);

-- -----------------------------------------------------------------------------
-- 2. INC-201 : numéros de table attribués plusieurs fois dans un centre.
--    La première inscription enregistrée (plus petit id) garde son numéro ; les
--    suivantes reçoivent un nouveau numéro à la suite du plus grand du centre.
--    Format P-0412 : SUBSTR(CAST(10000 + n ...), 2) remplace LPAD (absent de SQLite).
-- -----------------------------------------------------------------------------
INSERT INTO reprise_renumerotations (inscription_id, npi, ancien_numero, nouveau_numero)
SELECT a.id, a.npi, a.numero_table,
       a.code_centre || '-' || SUBSTR(CAST(10000 + m.dernier + a.rang AS VARCHAR(5)), 2)
FROM (SELECT i.id, i.npi, i.centre_id, i.numero_table, ce.code AS code_centre,
             ROW_NUMBER() OVER (PARTITION BY i.centre_id ORDER BY i.id) AS rang
      FROM inscriptions i
      JOIN centres ce ON ce.id = i.centre_id
      WHERE EXISTS (SELECT 1 FROM inscriptions p
                    WHERE p.centre_id = i.centre_id
                      AND p.numero_table = i.numero_table
                      AND p.id < i.id)) a
JOIN (SELECT centre_id, MAX(CAST(SUBSTR(numero_table, 3) AS INTEGER)) AS dernier
      FROM inscriptions
      GROUP BY centre_id) m
  ON m.centre_id = a.centre_id
WHERE NOT EXISTS (SELECT 1 FROM reprise_renumerotations r WHERE r.inscription_id = a.id);

UPDATE inscriptions
SET numero_table = (SELECT r.nouveau_numero FROM reprise_renumerotations r
                    WHERE r.inscription_id = inscriptions.id)
WHERE EXISTS (SELECT 1 FROM reprise_renumerotations r
              WHERE r.inscription_id = inscriptions.id
                AND r.ancien_numero = inscriptions.numero_table);

-- -----------------------------------------------------------------------------
-- 3. Contraintes : la base refuse désormais ces incidents, quel que soit le code.
--    La capacité d'un centre et la règle du « même jour » ne s'expriment pas par
--    un index : elles sont garanties par la transaction de l'application corrigée.
-- -----------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS ux_inscriptions_centre_numero ON inscriptions (centre_id, numero_table);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inscriptions_npi_concours ON inscriptions (npi, concours_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_candidats_npi ON candidats (npi);
CREATE UNIQUE INDEX IF NOT EXISTS ux_concours_code ON concours (code);
CREATE UNIQUE INDEX IF NOT EXISTS ux_centres_code ON centres (code);
-- INC-207 : liste des inscrits d'un centre et d'un concours.
CREATE INDEX IF NOT EXISTS ix_inscriptions_centre_concours ON inscriptions (centre_id, concours_id);

-- -----------------------------------------------------------------------------
-- 4. INC-202 : Lokossa, 307 inscrits pour 300 places. AUCUNE SUPPRESSION.
--    296 inscrits avant l'incident, puis 11 inscriptions acceptées le 19/11 entre
--    9 h 11 et 9 h 13 (heure du Bénin) pendant la lenteur du service d'identification.
--    Il restait 4 places : on classe les 11 par heure d'ARRIVÉE de la requête
--    (journal : fin - durée), plus juste que cree_le, qui est l'heure de fin.
--    Décision à demander à la Direction des concours : voir docs/decision-lokossa.md.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reprise_lokossa_a_arbitrer (
  inscription_id INTEGER PRIMARY KEY,
  npi VARCHAR(10) NOT NULL,
  arrivee_requete_utc TIMESTAMP NOT NULL,   -- source : journal_production.log
  requete VARCHAR(8) NOT NULL
);

INSERT INTO reprise_lokossa_a_arbitrer (inscription_id, npi, arrivee_requete_utc, requete) VALUES
  (5045, '8496397796', '2026-11-19 08:11:01.871', 'aaf0f8db'),
  (5046, '1230531326', '2026-11-19 08:11:07.847', '29c31296'),
  (5047, '5849598968', '2026-11-19 08:11:11.145', 'fd92dc93'),
  (5049, '7390181652', '2026-11-19 08:11:16.244', '036e0cc8'),
  (5052, '5764074760', '2026-11-19 08:11:22.658', 'f4cf0482'),
  (5050, '6926583899', '2026-11-19 08:11:26.471', '160e4365'),
  (5048, '7626262999', '2026-11-19 08:11:32.514', 'ca41610c'),
  (5054, '7237864540', '2026-11-19 08:11:36.417', '5239eb06'),
  (5051, '0804931531', '2026-11-19 08:11:42.659', 'fd3154d6'),
  (5053, '5004565733', '2026-11-19 08:11:47.322', '0af7789b'),
  (5055, '1168848367', '2026-11-19 08:11:51.081', 'baaa5823')
ON CONFLICT (inscription_id) DO NOTHING;

COMMIT;

-- -----------------------------------------------------------------------------
-- 5. Contrôles et listes à transmettre (lecture seule)
-- -----------------------------------------------------------------------------

-- Doit renvoyer 0 ligne :
SELECT centre_id, numero_table, COUNT(*) AS nb FROM inscriptions
GROUP BY centre_id, numero_table HAVING COUNT(*) > 1;

SELECT npi, concours_id, COUNT(*) AS nb FROM inscriptions
GROUP BY npi, concours_id HAVING COUNT(*) > 1;

-- Remplissage des centres après reprise :
SELECT ce.code, ce.nom, ce.capacite, COUNT(i.id) AS inscrits, COUNT(i.id) - ce.capacite AS depassement
FROM centres ce LEFT JOIN inscriptions i ON i.centre_id = ce.id
GROUP BY ce.code, ce.nom, ce.capacite
ORDER BY ce.code;

-- Lokossa : liste pour la décision (rang d'arrivée ; rang <= 4 = dans la capacité).
SELECT ROW_NUMBER() OVER (ORDER BY l.arrivee_requete_utc) AS rang_arrivee,
       CASE WHEN ROW_NUMBER() OVER (ORDER BY l.arrivee_requete_utc)
                 <= ce.capacite - (SELECT COUNT(*) FROM inscriptions x
                                   WHERE x.centre_id = ce.id
                                     AND x.id NOT IN (SELECT inscription_id FROM reprise_lokossa_a_arbitrer))
            THEN 'dans la capacité' ELSE 'au-delà de la capacité' END AS situation,
       l.inscription_id, l.npi, c.nom, c.prenoms, co.code AS concours, i.numero_table, l.arrivee_requete_utc
FROM reprise_lokossa_a_arbitrer l
JOIN inscriptions i ON i.id = l.inscription_id
JOIN centres ce ON ce.id = i.centre_id
JOIN concours co ON co.id = i.concours_id
LEFT JOIN candidats c ON c.npi = l.npi
ORDER BY l.arrivee_requete_utc;

-- Candidats à prévenir : numéro de table changé (nouvelle convocation).
SELECT r.inscription_id, r.npi, c.nom, c.prenoms, r.ancien_numero, r.nouveau_numero
FROM reprise_renumerotations r LEFT JOIN candidats c ON c.npi = r.npi
ORDER BY r.nouveau_numero;
