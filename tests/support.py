"""Outils communs aux tests : faux service d'identification et base de test."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

from inscriptions import client_identite, depot, service
from inscriptions.api import ServeurHTTP

# Le 25/11/2026 : DOUANES et IMPOTS ouverts, TRESOR clos.
MAINTENANT = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)


class FauxServiceIdentite:
    """NPI commençant par 9 : inconnu (404). `delai_s` simule la lenteur du 19/11."""

    def __init__(self):
        self.delai_s = 0.0
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def do_GET(self):
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

            def log_message(self, format, *args):
                pass

        class Serveur(ServeurHTTP):
            def handle_error(self, request, client_address):
                pass  # le client a abandonné après son délai : c'est le comportement attendu

        self.http = Serveur(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def arreter(self):
        self.http.shutdown()
        self.http.server_close()


def creer_base(chemin_db, capacite_lokossa=20):
    depot.initialiser(chemin_db)
    cnx = depot.connexion(chemin_db)
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


class CasAvecBase(unittest.TestCase):
    """Base SQLite neuve et faux service d'identification pour chaque test."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.db = os.path.join(self.dossier, "test.db")
        creer_base(self.db)
        self.faux = FauxServiceIdentite()
        self.identite = client_identite.ClientIdentite(self.faux.url, delai_s=2.0)

    def tearDown(self):
        self.faux.arreter()
        shutil.rmtree(self.dossier, ignore_errors=True)

    def inscrire(self, d, maintenant=MAINTENANT):
        return service.inscrire(self.db, d, self.identite, maintenant)

    def requete(self, sql, *params):
        cnx = depot.connexion(self.db)
        try:
            return cnx.execute(sql, params).fetchall()
        finally:
            cnx.close()
