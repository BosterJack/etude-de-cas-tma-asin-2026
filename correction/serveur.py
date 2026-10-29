"""API HTTP minimale autour de la correction (bibliothèque standard).

    python correction/serveur.py --db inscriptions.db --identite http://localhost:9000 [--port 8000]

Routes :
    POST /api/inscriptions                         {"npi", "date_naissance", "concours", "centre"}
    GET  /api/centres/{code}/inscrits?concours=…
"""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import identite
import inscription

RE_LISTE = re.compile(r"^/api/centres/([^/]+)/inscrits$")


class ServeurHTTP(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256  # 5 par défaut : les pics de connexions simultanées seraient rejetés


def creer_serveur(chemin_db, client_identite, hote="127.0.0.1", port=0, horloge=None):
    class Gestionnaire(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _repondre(self, code, corps):
            data = json.dumps(corps, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/api/inscriptions":
                return self._repondre(404, {"erreur": "Route inconnue."})
            try:
                longueur = int(self.headers.get("Content-Length", 0))
                demande = json.loads(self.rfile.read(longueur) or b"{}")
                if not isinstance(demande, dict):
                    raise ValueError
            except ValueError:
                return self._repondre(400, {"erreur": "Corps JSON invalide."})
            try:
                maintenant = horloge() if horloge else None
                self._repondre(201, inscription.inscrire(chemin_db, demande, client_identite, maintenant))
            except inscription.Refus as r:
                self._repondre(r.code_http, {"erreur": r.message})

        def do_GET(self):
            url = urlparse(self.path)
            m = RE_LISTE.match(url.path)
            if not m:
                return self._repondre(404, {"erreur": "Route inconnue."})
            concours = parse_qs(url.query).get("concours", [""])[0]
            self._repondre(200, inscription.lister_inscrits(chemin_db, m.group(1), concours))

        def log_message(self, *args):
            pass

    return ServeurHTTP((hote, port), Gestionnaire)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--identite", required=True, help="URL de base du service d'identification")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    inscription.initialiser(args.db)
    serveur = creer_serveur(args.db, identite.ClientIdentite(args.identite), port=args.port)
    print(f"API sur http://127.0.0.1:{serveur.server_address[1]}")
    serveur.serve_forever()


if __name__ == "__main__":
    main()
