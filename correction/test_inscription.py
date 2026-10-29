"""Tests de la correction. Lancement depuis la racine du dépôt :

    python -m unittest discover -s correction -v
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler

import identite
import inscription
import serveur

MAINTENANT = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)


# --- Faux service d'identification -------------------------------------------

class FauxIdentite:
    """NPI commençant par 9 : inconnu (404). `delai_s` simule la lenteur du 19/11."""

    def __init__(self):
        self.delai_s = 0.0
        self.appels = 0
        faux = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                faux.appels += 1
                time.sleep(faux.delai_s)
                npi = self.path.rsplit("/", 1)[-1]
                if npi.startswith("9"):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                corps = json.dumps({"npi": npi, "nom": "DOSSOU", "prenoms": "Test"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *a):
                pass

        class Serveur(serveur.ServeurHTTP):
            def handle_error(self, request, client_address):
                pass  # le client a abandonné après son délai : c'est le comportement attendu

        self.http = Serveur(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def arreter(self):
        self.http.shutdown()
        self.http.server_close()


def remplir(chemin_db, capacite_lokossa=20):
    inscription.initialiser(chemin_db)
    cnx = inscription.connexion(chemin_db)
    cnx.executescript(f"""
        INSERT INTO concours (id, code, libelle, date_epreuve, cloture) VALUES
          (1, 'DOUANES', 'Douanes', '2026-12-12', '2026-11-30 22:59:00'),
          (2, 'IMPOTS',  'Impôts',  '2026-12-12', '2026-11-30 22:59:00'),
          (3, 'TRESOR',  'Trésor',  '2026-12-19', '2026-11-20 22:59:00');
        INSERT INTO centres (id, code, nom, capacite) VALUES
          (1, 'C', 'Cotonou', 6000), (2, 'P', 'Parakou', 700), (3, 'L', 'Lokossa', {capacite_lokossa});
    """)
    cnx.close()


def npi(i):
    return f"{1000000000 + i}"


def demande(i, concours="DOUANES", centre="C", naissance="1995-03-14"):
    return {"npi": npi(i), "date_naissance": naissance, "concours": concours, "centre": centre}


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.db = os.path.join(self.dossier, "test.db")
        remplir(self.db)
        self.faux = FauxIdentite()
        self.client = identite.ClientIdentite(self.faux.url, delai_s=2.0)

    def tearDown(self):
        self.faux.arreter()
        shutil.rmtree(self.dossier, ignore_errors=True)

    def inscrire(self, d, maintenant=MAINTENANT):
        return inscription.inscrire(self.db, d, self.client, maintenant)

    def lignes(self, sql, *params):
        cnx = inscription.connexion(self.db)
        try:
            return cnx.execute(sql, params).fetchall()
        finally:
            cnx.close()


# --- Règles corrigées --------------------------------------------------------

class TestAge(unittest.TestCase):
    def test_inc_205_ne_le_20_juin_1991_a_35_ans_et_est_accepte(self):
        self.assertEqual(inscription.age_au_31_decembre(date(1991, 6, 20), 2026), 35)
        self.assertTrue(inscription.age_valide(date(1991, 6, 20), date(2026, 12, 12)))

    def test_bornes(self):
        epreuve = date(2026, 12, 12)
        self.assertTrue(inscription.age_valide(date(1991, 1, 1), epreuve))     # 35 ans au 31/12
        self.assertTrue(inscription.age_valide(date(1992, 1, 8), epreuve))     # refusé à tort par jours/365
        self.assertFalse(inscription.age_valide(date(1990, 12, 31), epreuve))  # 36 ans au 31/12

    def test_ancien_calcul_etait_faux(self):
        jours = (date(2026, 12, 31) - date(1991, 6, 20)).days
        self.assertGreater(jours / 365, 35)  # c'est ce qui refusait le candidat d'INC-205


class TestCloture(unittest.TestCase):
    CLOTURE = inscription.parse_utc("2026-11-20 22:59:00")  # 23 h 59 heure du Bénin

    def test_inc_204_ouvert_a_23h30_heure_du_benin(self):
        from datetime import timedelta
        benin = timezone(timedelta(hours=1))
        self.assertFalse(inscription.inscriptions_closes(self.CLOTURE, datetime(2026, 11, 20, 23, 0, tzinfo=benin)))
        self.assertFalse(inscription.inscriptions_closes(self.CLOTURE, datetime(2026, 11, 20, 23, 59, tzinfo=benin)))
        self.assertTrue(inscription.inscriptions_closes(self.CLOTURE, datetime(2026, 11, 20, 23, 59, 1, tzinfo=benin)))

    def test_heure_sans_fuseau_refusee(self):
        with self.assertRaises(ValueError):
            inscription.inscriptions_closes(self.CLOTURE, datetime(2026, 11, 20, 23, 0))


# --- Enregistrement ----------------------------------------------------------

class TestInscription(BaseTest):
    def test_inscription_nominale(self):
        r = self.inscrire(demande(1))
        self.assertEqual((r["numero_table"], r["statut"]), ("C-0001", "validee"))
        self.assertEqual(self.inscrire(demande(2))["numero_table"], "C-0002")
        self.assertEqual(len(self.lignes("SELECT * FROM candidats")), 2)

    def test_double_inscription_refusee(self):
        self.inscrire(demande(1))
        with self.assertRaises(inscription.Refus) as e:
            self.inscrire(demande(1))
        self.assertIn("déjà inscrit à ce concours", e.exception.message)

    def test_inc_208_meme_jour_refuse(self):
        self.inscrire(demande(1, "DOUANES"))
        with self.assertRaises(inscription.Refus) as e:
            self.inscrire(demande(1, "IMPOTS"))
        self.assertIn("même jour", e.exception.message)

    def test_autre_jour_accepte(self):
        self.inscrire(demande(1, "DOUANES"))
        apres_tresor = datetime(2026, 11, 20, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(self.inscrire(demande(1, "TRESOR"), apres_tresor)["statut"], "validee")

    def test_cloture_tresor(self):
        self.assertEqual(self.inscrire(demande(1, "TRESOR"), datetime(2026, 11, 20, 22, 30, tzinfo=timezone.utc))["statut"],
                         "validee")
        with self.assertRaises(inscription.Refus):
            self.inscrire(demande(2, "TRESOR"), datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc))

    def test_capacite(self):
        for i in range(20):
            self.inscrire(demande(i, centre="L"))
        with self.assertRaises(inscription.Refus) as e:
            self.inscrire(demande(99, centre="L"))
        self.assertIn("complet", e.exception.message)

    def test_npi_inconnu(self):
        with self.assertRaises(inscription.Refus) as e:
            self.inscrire({**demande(0), "npi": "9000000001"})
        self.assertIn("inconnu", e.exception.message)
        self.assertEqual(self.lignes("SELECT COUNT(*) FROM inscriptions")[0][0], 0)

    def test_controle_de_forme(self):
        for mauvais in ({**demande(1), "npi": "97001234567"}, {**demande(1), "date_naissance": "12/03/1995"},
                        {**demande(1), "centre": "X"}, {**demande(1), "concours": "POLICE"}):
            with self.assertRaises(inscription.Refus) as e:
                self.inscrire(mauvais)
            self.assertEqual(e.exception.code_http, 400)


class TestIdentiteLente(BaseTest):
    def test_inc_206_service_lent_inscription_en_attente_sans_bloquer(self):
        self.faux.delai_s = 3.0
        self.client = identite.ClientIdentite(self.faux.url, delai_s=0.5)
        debut = time.monotonic()
        r = self.inscrire(demande(1))
        duree = time.monotonic() - debut
        self.assertEqual(r["statut"], "en_attente_verification")
        self.assertLess(duree, 1.5)

    def test_service_injoignable(self):
        self.client = identite.ClientIdentite("http://127.0.0.1:1", delai_s=0.5)
        self.assertEqual(self.inscrire(demande(1))["statut"], "en_attente_verification")

    def test_delai_plafonne_a_5_secondes(self):
        self.assertEqual(identite.ClientIdentite("http://x", delai_s=60).delai_s, 5.0)
        self.assertEqual(identite.ClientIdentite("http://x").delai_s, 5.0)


# --- Concurrence, à travers l'API HTTP ---------------------------------------

class TestConcurrence(BaseTest):
    def setUp(self):
        super().setUp()
        # Lenteur du service : c'est elle qui ouvrait la fenêtre de concurrence le 19/11.
        self.faux.delai_s = 0.2
        self.api = serveur.creer_serveur(self.db, self.client, horloge=lambda: MAINTENANT)
        self.url = f"http://127.0.0.1:{self.api.server_address[1]}/api/inscriptions"
        threading.Thread(target=self.api.serve_forever, daemon=True).start()

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
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
            barriere.wait()  # toutes les requêtes partent au même instant
            return self.poster(d)

        with ThreadPoolExecutor(max_workers=len(demandes)) as ex:
            return list(ex.map(envoyer, demandes))

    def test_inc_201_202_capacite_et_numeros_sous_concurrence(self):
        # 60 candidats différents se ruent sur Lokossa (20 places), sur deux concours.
        demandes = [demande(i, "IMPOTS" if i % 2 else "DOUANES", "L") for i in range(60)]
        resultats = self.en_parallele(demandes)
        acceptes = [c for s, c in resultats if s == 201]
        refus = [c for s, c in resultats if s != 201]
        self.assertEqual(len(acceptes), 20)
        self.assertTrue(all("complet" in c["erreur"] for c in refus))
        numeros = sorted(c["numero_table"] for c in acceptes)
        self.assertEqual(numeros, [f"L-{n:04d}" for n in range(1, 21)])
        self.assertEqual(self.lignes("SELECT COUNT(*) FROM inscriptions WHERE centre_id = 3")[0][0], 20)

    def test_inc_203_double_clic_simultane(self):
        resultats = self.en_parallele([demande(7)] * 15)
        self.assertEqual(sum(1 for s, _ in resultats if s == 201), 1)
        self.assertEqual(self.lignes("SELECT COUNT(*) FROM inscriptions WHERE npi = ?", npi(7))[0][0], 1)

    def test_meme_jour_simultane(self):
        resultats = self.en_parallele([demande(8, "DOUANES"), demande(8, "IMPOTS")] * 5)
        self.assertEqual(sum(1 for s, _ in resultats if s == 201), 1)

    def test_numeros_uniques_grand_volume(self):
        resultats = self.en_parallele([demande(i) for i in range(100)])
        self.assertTrue(all(s == 201 for s, _ in resultats))
        doublons = self.lignes("SELECT numero_table FROM inscriptions GROUP BY centre_id, numero_table HAVING COUNT(*) > 1")
        self.assertEqual(doublons, [])


# --- INC-207 -------------------------------------------------------------------

class TestListe(BaseTest):
    def test_liste_5000_inscrits_en_moins_de_2_secondes(self):
        cnx = inscription.connexion(self.db)
        cnx.execute("BEGIN")
        for i in range(5000):
            cnx.execute("INSERT INTO candidats (npi, nom, prenoms, date_naissance, cree_le) VALUES (?, 'N', 'P', '1995-01-01', '2026-11-20 00:00:00')", (npi(i),))
            cnx.execute("INSERT INTO inscriptions (concours_id, centre_id, npi, numero_table, statut, cree_le) VALUES (1, 1, ?, ?, 'validee', '2026-11-20 00:00:00')", (npi(i), f"C-{i + 1:04d}"))
        cnx.execute("COMMIT")
        cnx.close()
        debut = time.monotonic()
        liste = inscription.lister_inscrits(self.db, "C", "DOUANES")
        self.assertEqual(len(liste), 5000)
        self.assertLess(time.monotonic() - debut, 2.0)


if __name__ == "__main__":
    unittest.main()
