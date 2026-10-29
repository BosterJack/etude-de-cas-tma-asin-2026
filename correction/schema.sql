-- Schéma de la correction (SQLite). Même structure que l'export, plus les
-- contraintes et index qui manquaient. Les instants (cloture, cree_le) sont en UTC.

CREATE TABLE IF NOT EXISTS concours (
  id INTEGER PRIMARY KEY,
  code VARCHAR(10) NOT NULL UNIQUE,
  libelle VARCHAR(100) NOT NULL,
  date_epreuve DATE NOT NULL,
  cloture TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS centres (
  id INTEGER PRIMARY KEY,
  code VARCHAR(1) NOT NULL UNIQUE,
  nom VARCHAR(50) NOT NULL,
  capacite INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS candidats (
  id INTEGER PRIMARY KEY,
  npi VARCHAR(10) NOT NULL,
  nom VARCHAR(60) NOT NULL,
  prenoms VARCHAR(80) NOT NULL,
  date_naissance DATE NOT NULL,
  cree_le TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS inscriptions (
  id INTEGER PRIMARY KEY,
  concours_id INTEGER NOT NULL REFERENCES concours (id),
  centre_id INTEGER NOT NULL REFERENCES centres (id),
  npi VARCHAR(10) NOT NULL,
  numero_table VARCHAR(6) NOT NULL,
  statut VARCHAR(30) NOT NULL,
  cree_le TIMESTAMP NOT NULL
);

-- Filets de sécurité : même si le code se trompait, la base refuse les doublons.
-- Les inscriptions annulées (reprise des données) sortent des contraintes.
CREATE UNIQUE INDEX IF NOT EXISTS ux_candidats_npi ON candidats (npi);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inscriptions_numero
  ON inscriptions (centre_id, numero_table) WHERE statut <> 'annulee';
CREATE UNIQUE INDEX IF NOT EXISTS ux_inscriptions_npi_concours
  ON inscriptions (npi, concours_id) WHERE statut <> 'annulee';

-- INC-207 : liste des inscrits d'un centre pour un concours.
CREATE INDEX IF NOT EXISTS ix_inscriptions_centre_concours ON inscriptions (centre_id, concours_id);
