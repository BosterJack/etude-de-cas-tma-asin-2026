"""Chiffres de l'analyse du journal fourni (garde-fou contre les régressions du programme)."""
import unittest
from datetime import datetime
from pathlib import Path

from analyse import analyse_journal as aj

JOURNAL = Path(__file__).resolve().parent.parent / "donnees" / "journal_production.log"


class TestAnalyseJournal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requetes, cls.appels, cls.ignorees = aj.lire_journal(JOURNAL)

    def test_toutes_les_lignes_sont_reconnues(self):
        self.assertEqual(self.ignorees, [])
        self.assertEqual(len(self.requetes) + len(self.appels), 12777)

    def test_numeros_en_double(self):
        doubles = aj.numeros_en_double(self.requetes)
        self.assertEqual(len(doubles), 10)
        self.assertEqual(len(doubles["P-0464"]), 2)  # INC-201
        self.assertEqual(len(doubles["L-0298"]), 6)

    def test_inscriptions_en_double(self):
        self.assertEqual(len(aj.inscriptions_en_double(self.requetes)), 7)

    def test_periode_identite_lente_en_heure_du_benin(self):
        periode = aj.periode_identite_lente(self.appels, self.requetes)
        debut, fin = (periode[k].astimezone(aj.BENIN).replace(tzinfo=None, microsecond=0) for k in ("debut", "fin"))
        self.assertEqual(debut, datetime(2026, 11, 19, 9, 9, 48))
        self.assertEqual(fin, datetime(2026, 11, 19, 9, 39, 49))
        self.assertEqual(periode["nb_requetes_touchees"], 60)

    def test_refus_a_tort_cloture_tresor(self):
        self.assertEqual(len(aj.refus_cloture_a_tort(self.requetes)["TRESOR"]), 147)

    def test_refus_a_tort_age(self):
        refus = aj.refus_age_a_tort(self.requetes)
        self.assertEqual(len(refus), 36)
        self.assertIn("1991-06-20", {r["naissance"] for r in refus})  # INC-205

    def test_liste_des_inscrits_cotonou(self):
        stats = aj.stats_liste_inscrits(self.requetes)
        self.assertGreater(stats["C"]["max_ms"], 40000)  # INC-207

    def test_injection_sql_detectee(self):
        suspectes = aj.recherches_suspectes(self.requetes)
        self.assertEqual({r["ip"] for r in suspectes}, {"102.64.217.33"})
        self.assertEqual(max(int(r.get("lignes", 0) or 0) for r in suspectes), 18535)


if __name__ == "__main__":
    unittest.main()
