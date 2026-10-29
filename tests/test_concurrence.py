"""Requêtes simultanées à travers l'API HTTP (INC-201, INC-202, INC-203).

Toutes les requêtes d'un test partent au même instant (barrière), et le faux service
d'identification répond en 0,2 s pour rouvrir la fenêtre de concurrence du 19/11.
"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from inscriptions import api
from tests.support import MAINTENANT, CasAvecBase, demande, npi


class TestConcurrence(CasAvecBase):
    def setUp(self):
        super().setUp()
        self.faux.delai_s = 0.2
        self.serveur = api.creer_serveur(self.db, self.identite, horloge=lambda: MAINTENANT)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}/api/inscriptions"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def tearDown(self):
        self.serveur.shutdown()
        self.serveur.server_close()
        super().tearDown()

    def poster(self, d):
        req = urllib.request.Request(self.url, data=json.dumps(d).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as rep:
                return rep.status, json.loads(rep.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def en_parallele(self, demandes):
        barriere = threading.Barrier(len(demandes))

        def envoyer(d):
            barriere.wait()
            return self.poster(d)

        with ThreadPoolExecutor(max_workers=len(demandes)) as executeur:
            return list(executeur.map(envoyer, demandes))

    def test_inc_202_capacite_jamais_depassee_et_inc_201_numeros_uniques(self):
        # 60 candidats différents se ruent sur Lokossa (20 places), sur deux concours.
        resultats = self.en_parallele([demande(i, "IMPOTS" if i % 2 else "DOUANES", "L") for i in range(60)])
        acceptes = [corps for code, corps in resultats if code == 201]
        refuses = [corps for code, corps in resultats if code != 201]
        self.assertEqual(len(acceptes), 20)
        self.assertTrue(all("complet" in corps["erreur"] for corps in refuses))
        self.assertEqual(sorted(c["numero_table"] for c in acceptes), [f"L-{n:04d}" for n in range(1, 21)])
        self.assertEqual(self.requete("SELECT COUNT(*) FROM inscriptions WHERE centre_id = 3")[0][0], 20)

    def test_inc_203_double_clic_une_seule_inscription(self):
        resultats = self.en_parallele([demande(7)] * 15)
        self.assertEqual(sum(1 for code, _ in resultats if code == 201), 1)
        self.assertEqual(self.requete("SELECT COUNT(*) FROM inscriptions WHERE npi = ?", npi(7))[0][0], 1)

    def test_deux_concours_du_meme_jour_en_meme_temps(self):
        resultats = self.en_parallele([demande(8, "DOUANES"), demande(8, "IMPOTS")] * 5)
        self.assertEqual(sum(1 for code, _ in resultats if code == 201), 1)

    def test_100_inscriptions_simultanees_sans_numero_en_double(self):
        resultats = self.en_parallele([demande(i) for i in range(100)])
        self.assertTrue(all(code == 201 for code, _ in resultats))
        self.assertEqual(sorted(c["numero_table"] for _, c in resultats), [f"C-{n:04d}" for n in range(1, 101)])


if __name__ == "__main__":
    unittest.main()
