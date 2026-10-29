# Image unique pour les tests et l'analyse du journal.
# Aucune dépendance à installer : le projet n'utilise que la bibliothèque standard de Python.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY analyse ./analyse
COPY inscriptions ./inscriptions
COPY tests ./tests
COPY sql ./sql
COPY donnees ./donnees

CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]
