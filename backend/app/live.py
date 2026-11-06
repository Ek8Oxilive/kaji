"""Diffusion temps réel : un seul interrogateur Proxmox par cluster, partagé par tous les navigateurs.

Sans ça, chaque onglet ouvert interrogerait Proxmox lui-même. Ici l'interrogateur démarre à la première
connexion, s'arrête quand la dernière part, et n'envoie un instantané que s'il a changé.
"""
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

Fetch = Callable[[], Awaitable[dict]]
Item = tuple[str, object]          # ("snapshot", dict) ou ("error", str)


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


@dataclass
class _Channel:
    fetch: Fetch
    queues: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None
    last_snapshot: dict | None = None
    last_error: str | None = None


class Hub:
    def __init__(self, interval: float = 5.0, error_interval: float = 10.0):
        self.interval, self.error_interval = interval, error_interval
        self._channels: dict[int, _Channel] = {}

    @staticmethod
    def _push(q: asyncio.Queue, item: Item) -> None:
        if q.full():                      # abonné lent : on jette le plus ancien, il ne doit pas bloquer les autres
            q.get_nowait()
        q.put_nowait(item)

    def _broadcast(self, ch: _Channel, item: Item) -> None:
        for q in ch.queues:
            self._push(q, item)

    async def _poll(self, key: int) -> None:
        ch = self._channels[key]
        while True:
            delay = self.interval
            try:
                snap = await ch.fetch()
                ch.last_error = None
                if snap != ch.last_snapshot:
                    ch.last_snapshot = snap
                    self._broadcast(ch, ("snapshot", snap))
            except asyncio.CancelledError:
                raise
            except Exception as e:           # noqa: BLE001 - l'interrogateur ne doit jamais mourir
                msg = str(getattr(e, "detail", None) or e) or "Erreur inconnue"
                if msg != ch.last_error:
                    ch.last_error = msg
                    self._broadcast(ch, ("error", msg))
                delay = self.error_interval
            await asyncio.sleep(delay)

    async def subscribe(self, key: int, fetch: Fetch) -> AsyncIterator[Item]:
        ch = self._channels.get(key)
        if ch is None:
            ch = self._channels[key] = _Channel(fetch=fetch)
            ch.task = asyncio.create_task(self._poll(key))
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        ch.queues.add(q)
        if ch.last_snapshot is not None:     # un nouvel arrivant reçoit tout de suite l'état courant
            q.put_nowait(("snapshot", ch.last_snapshot))
        if ch.last_error is not None:
            q.put_nowait(("error", ch.last_error))
        try:
            while True:
                yield await q.get()
        finally:
            ch.queues.discard(q)
            if not ch.queues:
                if ch.task:
                    ch.task.cancel()
                self._channels.pop(key, None)

    def active(self) -> dict[int, int]:
        return {k: len(c.queues) for k, c in self._channels.items()}


hub = Hub()
