"""Enregistrement d'une inscription, séquentiel : règles, identité, liste des inscrits."""
import time
import unittest
from datetime import datetime, timezone

from inscriptions import client_identite, depot, service
from inscriptions.regles import Refus
from tests.support import CasAvecBase, demande, npi


class TestInscription(CasAvecBase):
    def test_inscription_nominale(self):
        r = self.inscrire(demande(1))
        self.assertEqual((r["numero_table"], r["statut"]), ("C-0001", "validee"))
        self.assertEqual(self.inscrire(demande(2))["numero_table"], "C-0002")
        self.assertEqual(len(self.requete("SELECT * FROM candidats")), 2)

    def test_double_inscription_refusee(self):
        self.inscrire(demande(1))
        with self.assertRaises(Refus) as e:
            self.inscrire(demande(1))
        self.assertIn("déjà inscrit à ce concours", e.exception.message)

    def test_inc_208_meme_jour_refuse_comportement_conforme(self):
        self.inscrire(demande(1, "DOUANES"))
        with self.assertRaises(Refus) as e:
            self.inscrire(demande(1, "IMPOTS"))
        self.assertIn("même jour", e.exception.message)

    def test_concours_d_un_autre_jour_accepte(self):
        avant_cloture_tresor = datetime(2026, 11, 20, 22, 0, tzinfo=timezone.utc)
        self.inscrire(demande(1, "DOUANES"), avant_cloture_tresor)
        self.assertEqual(self.inscrire(demande(1, "TRESOR"), avant_cloture_tresor)["statut"], "validee")

    def test_inc_204_inscription_tresor_a_23h30_heure_du_benin(self):
        a_23h30_benin = datetime(2026, 11, 20, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(self.inscrire(demande(1, "TRESOR"), a_23h30_benin)["statut"], "validee")
        with self.assertRaises(Refus):
            self.inscrire(demande(2, "TRESOR"), datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc))

    def test_inc_205_candidat_ne_le_20_juin_1991_accepte(self):
        self.assertEqual(self.inscrire(demande(1, naissance="1991-06-20"))["statut"], "validee")
        with self.assertRaises(Refus):
            self.inscrire(demande(2, naissance="1990-12-31"))

    def test_capacite_du_centre(self):
        for i in range(20):
            self.inscrire(demande(i, "IMPOTS" if i % 2 else "DOUANES", centre="L"))
        with self.assertRaises(Refus) as e:
            self.inscrire(demande(99, centre="L"))
        self.assertIn("complet", e.exception.message)

    def test_npi_inconnu_rien_n_est_enregistre(self):
        with self.assertRaises(Refus) as e:
            self.inscrire({**demande(0), "npi": "9000000001"})
        self.assertIn("inconnu", e.exception.message)
        self.assertEqual(self.requete("SELECT COUNT(*) FROM inscriptions")[0][0], 0)

    def test_controle_de_forme_refus_400(self):
        for mauvaise in ({**demande(1), "npi": "97001234567"}, {**demande(1), "date_naissance": "12/03/1995"},
                         {**demande(1), "centre": "X"}, {**demande(1), "concours": "POLICE"}):
            with self.assertRaises(Refus) as e:
                self.inscrire(mauvaise)
            self.assertEqual(e.exception.code_http, 400, mauvaise)


class TestServiceIdentiteLent(CasAvecBase):
    def test_inc_206_service_lent_inscription_en_attente_sans_bloquer(self):
        self.faux.delai_s = 3.0
        self.identite = client_identite.ClientIdentite(self.faux.url, delai_s=0.5)
        debut = time.monotonic()
        r = self.inscrire(demande(1))
        self.assertLess(time.monotonic() - debut, 1.5)
        self.assertEqual(r["statut"], "en_attente_verification")
        self.assertEqual(r["numero_table"], "C-0001")

    def test_service_injoignable_inscription_en_attente(self):
        self.identite = client_identite.ClientIdentite("http://127.0.0.1:1", delai_s=0.5)
        self.assertEqual(self.inscrire(demande(1))["statut"], "en_attente_verification")

    def test_delai_plafonne_a_5_secondes(self):
        self.assertEqual(client_identite.ClientIdentite("http://x").delai_s, 5.0)
        self.assertEqual(client_identite.ClientIdentite("http://x", delai_s=60).delai_s, 5.0)


class TestListeInscrits(CasAvecBase):
    def test_inc_207_liste_de_5000_inscrits_en_moins_de_2_secondes(self):
        cnx = depot.connexion(self.db)
        cnx.execute("BEGIN")
        for i in range(5000):
            cnx.execute("INSERT INTO candidats (npi, nom, prenoms, date_naissance, cree_le) "
                        "VALUES (?, 'NOM', 'Prénom', '1995-01-01', '2026-11-20 00:00:00')", (npi(i),))
            cnx.execute("INSERT INTO inscriptions (concours_id, centre_id, npi, numero_table, statut, cree_le) "
                        "VALUES (1, 1, ?, ?, 'validee', '2026-11-20 00:00:00')", (npi(i), f"C-{i + 1:04d}"))
        cnx.execute("COMMIT")
        cnx.close()
        debut = time.monotonic()
        liste = service.lister_inscrits(self.db, "C", "DOUANES")
        self.assertLess(time.monotonic() - debut, 2.0)
        self.assertEqual(len(liste), 5000)
        self.assertEqual(liste[0]["nom"], "NOM")


if __name__ == "__main__":
    unittest.main()
