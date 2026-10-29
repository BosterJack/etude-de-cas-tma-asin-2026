"""Chiffres de l'analyse sur le journal fourni (garde-fou contre les régressions)."""
import unittest
from datetime import datetime
from pathlib import Path

from analyse import analyse_journal as analyse

JOURNAL = Path(__file__).resolve().parent.parent / "donnees" / "journal_production.log"


def en_heure_du_benin(instant):
    return instant.astimezone(analyse.HEURE_DU_BENIN).replace(tzinfo=None, microsecond=0)


class TestAnalyseJournal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requetes, cls.appels, cls.non_reconnues = analyse.lire_journal(JOURNAL)

    def test_toutes_les_lignes_sont_reconnues(self):
        self.assertEqual(self.non_reconnues, [])
        self.assertEqual(len(self.requetes) + len(self.appels), 12777)

    def test_numeros_en_double(self):
        doublons = analyse.numeros_en_double(self.requetes)
        self.assertEqual(len(doublons), 10)
        self.assertEqual(len(doublons["P-0464"]), 2)  # INC-201
        self.assertEqual(len(doublons["L-0298"]), 6)

    def test_inscriptions_en_double(self):
        self.assertEqual(len(analyse.inscriptions_en_double(self.requetes)), 7)

    def test_periode_identite_lente(self):
        periode = analyse.periode_identite_lente(self.appels, self.requetes)
        assert periode is not None
        self.assertEqual(en_heure_du_benin(periode.debut), datetime(2026, 11, 19, 9, 9, 48))
        self.assertEqual(en_heure_du_benin(periode.fin), datetime(2026, 11, 19, 9, 39, 49))
        self.assertEqual(len(periode.requetes_touchees), 60)

    def test_refus_a_tort_cloture_tresor(self):
        refus = analyse.refus_cloture_a_tort(self.requetes)
        self.assertEqual(len([r for r in refus if r.champs["concours"] == "TRESOR"]), 147)

    def test_refus_a_tort_age(self):
        refus = analyse.refus_age_a_tort(self.requetes)
        self.assertEqual(len(refus), 36)
        self.assertIn("1991-06-20", {r.champs["naissance"] for r in refus})  # INC-205

    def test_liste_des_inscrits_de_cotonou(self):
        self.assertGreater(analyse.durees_liste_inscrits(self.requetes)["C"].max_ms, 40000)  # INC-207

    def test_injection_sql_detectee(self):
        suspectes = analyse.recherches_suspectes(self.requetes)
        self.assertEqual({r.ip for r in suspectes}, {"102.64.217.33"})
        self.assertEqual(max(int(r.champs.get("lignes", 0)) for r in suspectes), 18535)


if __name__ == "__main__":
    unittest.main()
