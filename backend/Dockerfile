# Backend Kaji. Un SEUL processus : le limiteur de connexions et le flux temps réel (SSE) vivent en mémoire.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Utilisateur sans privilèges ; /data reçoit la base SQLite (volume).
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin kaji \
 && mkdir -p /app /data && chown kaji:kaji /data
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

ENV DATABASE_URL=sqlite:////data/kaji.db
USER kaji
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

# Les migrations de schéma s'exécutent au démarrage (sauvegarde de la base avant toute migration).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
