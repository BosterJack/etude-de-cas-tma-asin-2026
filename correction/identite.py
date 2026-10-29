"""Client du service national d'identification, borné à 5 secondes.

INC-206 : le client HTTP d'origine, « dans sa configuration par défaut », n'avait
pas de délai d'attente. Ici le délai porte sur la durée totale de l'appel (pas
seulement sur chaque lecture de socket) : au-delà, on rend la main et
l'inscription passe « en attente de vérification ».
"""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as DelaiDepasse

DELAI_MAX_S = 5.0

CONNU = "connu"
INCONNU = "inconnu"
INDISPONIBLE = "indisponible"  # lent, en erreur ou injoignable : ne bloque jamais le candidat

_executeur = ThreadPoolExecutor(max_workers=32, thread_name_prefix="identite")


class ClientIdentite:
    def __init__(self, url_base, delai_s=DELAI_MAX_S):
        self.url_base = url_base.rstrip("/")
        self.delai_s = min(delai_s, DELAI_MAX_S)

    def _appel(self, npi):
        url = f"{self.url_base}/identite/{npi}"
        try:
            # Le délai de socket évite aussi qu'un thread reste bloqué indéfiniment.
            with urllib.request.urlopen(url, timeout=self.delai_s) as rep:
                corps = rep.read()
                try:
                    return CONNU, json.loads(corps or b"{}")
                except ValueError:
                    return CONNU, {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return INCONNU, None
            return INDISPONIBLE, None
        except (urllib.error.URLError, OSError):
            return INDISPONIBLE, None

    def verifier(self, npi):
        """Retourne (CONNU, identite) | (INCONNU, None) | (INDISPONIBLE, None) en au plus delai_s."""
        futur = _executeur.submit(self._appel, npi)
        try:
            return futur.result(timeout=self.delai_s)
        except DelaiDepasse:
            return INDISPONIBLE, None
