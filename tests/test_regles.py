"""Règles d'âge (INC-205) et de clôture (INC-204)."""
import unittest
from datetime import date, datetime, timedelta, timezone

from inscriptions import regles

BENIN = timezone(timedelta(hours=1))


class TestAge(unittest.TestCase):
    EPREUVE_2026 = date(2026, 12, 12)

    def test_inc_205_ne_le_20_juin_1991_a_35_ans_et_est_accepte(self):
        self.assertEqual(regles.age_au_31_decembre(date(1991, 6, 20), 2026), 35)
        self.assertTrue(regles.age_valide(date(1991, 6, 20), self.EPREUVE_2026))

    def test_bornes_de_l_annee_limite(self):
        self.assertTrue(regles.age_valide(date(1991, 1, 1), self.EPREUVE_2026))
        self.assertTrue(regles.age_valide(date(1991, 12, 31), self.EPREUVE_2026))
        self.assertFalse(regles.age_valide(date(1990, 12, 31), self.EPREUVE_2026))

    def test_ne_debut_1992_refuse_a_tort_par_l_ancien_calcul(self):
        # 34 ans au 31/12/2026, mais 12 776 jours / 365 = 35,003 à cause des années bissextiles.
        self.assertGreater((date(2026, 12, 31) - date(1992, 1, 8)).days / 365, 35)
        self.assertTrue(regles.age_valide(date(1992, 1, 8), self.EPREUVE_2026))


class TestCloture(unittest.TestCase):
    CLOTURE_TRESOR = regles.instant_utc("2026-11-20 22:59:00")  # 23 h 59 heure du Bénin

    def test_inc_204_ouvert_entre_22h59_et_23h59_heure_du_benin(self):
        for minute in ((22, 59), (23, 30), (23, 59)):
            instant = datetime(2026, 11, 20, *minute, tzinfo=BENIN)
            self.assertFalse(regles.inscriptions_closes(self.CLOTURE_TRESOR, instant), instant)

    def test_clos_apres_23h59_heure_du_benin(self):
        self.assertTrue(regles.inscriptions_closes(self.CLOTURE_TRESOR, datetime(2026, 11, 20, 23, 59, 1, tzinfo=BENIN)))
        self.assertTrue(regles.inscriptions_closes(self.CLOTURE_TRESOR, datetime(2026, 11, 21, 0, 0, tzinfo=BENIN)))

    def test_meme_resultat_quel_que_soit_le_fuseau_du_serveur(self):
        instant_benin = datetime(2026, 11, 20, 23, 30, tzinfo=BENIN)
        self.assertEqual(regles.inscriptions_closes(self.CLOTURE_TRESOR, instant_benin),
                         regles.inscriptions_closes(self.CLOTURE_TRESOR, instant_benin.astimezone(timezone.utc)))

    def test_heure_sans_fuseau_refusee(self):
        with self.assertRaises(ValueError):
            regles.inscriptions_closes(self.CLOTURE_TRESOR, datetime(2026, 11, 20, 23, 0))


class TestNpi(unittest.TestCase):
    def test_formats_vus_dans_le_journal(self):
        self.assertTrue(regles.npi_valide("0175791358"))
        for mauvais in ("97001234567", "0123456789A", "01 23 45 67 89", ""):
            self.assertFalse(regles.npi_valide(mauvais), mauvais)


if __name__ == "__main__":
    unittest.main()
