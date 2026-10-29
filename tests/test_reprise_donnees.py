"""Script de reprise appliqué à l'export fourni : résultat attendu et rejouabilité."""
import sqlite3
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
EXPORT = RACINE / "donnees" / "base_inscriptions.sql"
SCRIPT = RACINE / "sql" / "reprise_donnees.sql"


class TestRepriseDonnees(unittest.TestCase):
    def setUp(self):
        self.cnx = sqlite3.connect(":memory:", isolation_level=None)
        self.cnx.executescript(EXPORT.read_text(encoding="utf-8"))
        self.script = SCRIPT.read_text(encoding="utf-8")

    def tearDown(self):
        self.cnx.close()

    def valeur(self, sql):
        return self.cnx.execute(sql).fetchone()[0]

    def etat(self):
        return (self.cnx.execute("SELECT id, centre_id, npi, numero_table FROM inscriptions ORDER BY id").fetchall(),
                self.cnx.execute("SELECT * FROM reprise_renumerotations ORDER BY inscription_id").fetchall(),
                self.cnx.execute("SELECT id FROM reprise_inscriptions_supprimees ORDER BY id").fetchall())

    def test_etat_initial_conforme_au_journal(self):
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM inscriptions"), 6400)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM (SELECT 1 FROM inscriptions "
                                     "GROUP BY centre_id, numero_table HAVING COUNT(*) > 1)"), 10)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM inscriptions WHERE centre_id = 3"), 307)

    def test_reprise(self):
        self.cnx.executescript(self.script)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM reprise_inscriptions_supprimees"), 7)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM inscriptions"), 6393)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM reprise_renumerotations"), 15)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM (SELECT 1 FROM inscriptions "
                                     "GROUP BY centre_id, numero_table HAVING COUNT(*) > 1)"), 0)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM (SELECT 1 FROM inscriptions "
                                     "GROUP BY npi, concours_id HAVING COUNT(*) > 1)"), 0)
        # P-0464 (INC-201) : le premier garde son numéro, le second reçoit le suivant du centre.
        self.assertEqual(self.cnx.execute("SELECT numero_table FROM inscriptions WHERE id IN (5065, 5066) "
                                          "ORDER BY id").fetchall(), [("P-0464",), ("P-0614",)])

    def test_lokossa_aucune_inscription_supprimee(self):
        self.cnx.executescript(self.script)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM inscriptions WHERE centre_id = 3"), 307)
        self.assertEqual(self.valeur("SELECT COUNT(*) FROM reprise_lokossa_a_arbitrer"), 11)

    def test_rejouable(self):
        self.cnx.executescript(self.script)
        premier = self.etat()
        self.cnx.executescript(self.script)
        self.assertEqual(self.etat(), premier)

    def test_contraintes_posees(self):
        self.cnx.executescript(self.script)
        with self.assertRaises(sqlite3.IntegrityError):
            self.cnx.execute("INSERT INTO inscriptions (concours_id, centre_id, npi, numero_table, statut, cree_le) "
                             "VALUES (1, 2, '0000000001', 'P-0464', 'validee', '2026-11-21 08:00:00')")
        npi_existant = self.valeur("SELECT npi FROM inscriptions WHERE concours_id = 1 LIMIT 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.cnx.execute("INSERT INTO inscriptions (concours_id, centre_id, npi, numero_table, statut, cree_le) "
                             f"VALUES (1, 2, '{npi_existant}', 'P-9999', 'validee', '2026-11-21 08:00:00')")


if __name__ == "__main__":
    unittest.main()
