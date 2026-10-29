"""API HTTP minimale autour du service (bibliothèque standard).

    python -m inscriptions.api --db inscriptions.db --identite http://localhost:9000 [--port 8000]
    python -m inscriptions.api --db postgresql://tma:tma@localhost:55432/inscriptions --identite …

Routes :
    POST /api/inscriptions                       corps JSON {npi, date_naissance, concours, centre}
    GET  /api/centres/{code}/inscrits?concours=…
"""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import client_identite, depot, service
from .regles import Refus

RE_LISTE_INSCRITS = re.compile(r"^/api/centres/([^/]+)/inscrits$")


class ServeurHTTP(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256  # 5 par défaut : un pic de connexions simultanées serait rejeté


def creer_serveur(base, identite, hote="127.0.0.1", port=0, horloge=None):
    """`horloge` : fonction qui renvoie l'instant courant (injectée pour les tests)."""

    class Gestionnaire(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _repondre(self, code, corps):
            data = json.dumps(corps, ensure_ascii=False, default=str).encode("utf-8")  # default=str : dates PostgreSQL
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
                self._repondre(201, service.inscrire(base, demande, identite, maintenant))
            except Refus as refus:
                self._repondre(refus.code_http, {"erreur": refus.message})

        def do_GET(self):
            url = urlparse(self.path)
            m = RE_LISTE_INSCRITS.match(url.path)
            if not m:
                return self._repondre(404, {"erreur": "Route inconnue."})
            concours = parse_qs(url.query).get("concours", [""])[0]
            self._repondre(200, service.lister_inscrits(base, m.group(1), concours))

        def log_message(self, format, *args):
            pass  # pas de trace par requête sur la sortie standard

    return ServeurHTTP((hote, port), Gestionnaire)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="fichier SQLite, ou URL postgresql://…")
    parser.add_argument("--identite", required=True, help="URL de base du service d'identification")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    base = depot.ouvrir_base(args.db)
    base.initialiser()
    serveur = creer_serveur(base, client_identite.ClientIdentite(args.identite), port=args.port)
    print(f"API à l'écoute sur http://127.0.0.1:{serveur.server_address[1]}")
    serveur.serve_forever()


if __name__ == "__main__":
    main()
