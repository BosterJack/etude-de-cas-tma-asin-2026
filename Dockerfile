# Image unique pour les tests et l'analyse du journal.
# Seule dépendance : le pilote PostgreSQL (le reste n'utilise que la bibliothèque standard).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir "psycopg[binary]==3.2.3"

COPY analyse ./analyse
COPY inscriptions ./inscriptions
COPY tests ./tests
COPY sql ./sql
COPY donnees ./donnees

CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]
