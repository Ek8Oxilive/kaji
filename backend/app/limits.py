"""Limite de requêtes simultanées (lot #457) : refuser PROPREMENT plutôt que tout bloquer.

Constaté en mesure le 2026-11-14 : quand les requêtes en cours dépassent le pool de connexions à la base, les threads de FastAPI attendent tous une connexion alors que celles qui en détiennent
ne peuvent pas se terminer (plus de thread libre pour fermer leur session) : **tout se bloque 30 s**, puis des erreurs 500. Ici, au-delà de `KAJI_MAX_CONCURRENT_REQUESTS` requêtes en cours,
les nouvelles reçoivent tout de suite un **503** clair avec `Retry-After`, et le reste continue de répondre.

Exemptés : `/api/health` (la supervision doit toujours répondre), le flux temps réel `…/events` (long, il ne tient pas de connexion à la base), et tout ce qui n'est pas HTTP (consoles WebSocket).
Le compteur vit dans la boucle d'événements : aucune course possible entre le test et l'incrément (pas d'`await` entre les deux).
"""
import json
import logging
import time

log = logging.getLogger("kaji.limits")
BODY = json.dumps({"detail": "Kaji est surchargé (trop de requêtes simultanées) : réessaie dans quelques secondes."}).encode()


class ConcurrencyLimit:
    def __init__(self, app, limit=None):
        """`limit` : un entier, ou `None` pour lire `KAJI_MAX_CONCURRENT_REQUESTS` à chaque requête (configuration en cache : pas d'évaluation à l'import, qui ferait échouer le démarrage avant le message
        explicite d'une clé manquante)."""
        self.app, self._limit = app, limit
        self.in_flight = 0
        self.shed = 0
        self._last_log = 0.0

    @property
    def limit(self) -> int:
        if self._limit is not None:
            return self._limit
        from .config import get_settings
        return get_settings().kaji_max_concurrent_requests

    @staticmethod
    def exempt(path: str) -> bool:
        return path == "/api/health" or path.endswith("/events")

    async def __call__(self, scope, receive, send):
        limit = self.limit
        if scope["type"] != "http" or limit <= 0 or self.exempt(scope.get("path", "")):
            return await self.app(scope, receive, send)
        if self.in_flight >= limit:
            self.shed += 1
            now = time.monotonic()
            if now - self._last_log > 10:                                       # un message toutes les 10 s au plus
                self._last_log = now
                log.warning("surcharge : %d requêtes en cours (limite %d), %d refusées depuis le démarrage", self.in_flight, limit, self.shed)
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(BODY)).encode()),
                                                                                  (b"retry-after", b"2"), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": BODY})
            return
        self.in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_flight -= 1
