import ssl
import uuid
from urllib.parse import quote, urlencode

import httpx

from .tlspin import context_for


class ProxmoxClient:
    """Client async pour l'API REST Proxmox (auth par API token).

    Une instance par connexion enregistrée, créée à la demande.
    """

    def __init__(self, host: str, user: str, token_id: str, token_secret: str,
                 port: int = 8006, verify_ssl: bool = False, pinned_cert: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, *, ticket: str | None = None, csrf: str | None = None, anonymous: bool = False):
        """Authentification : par défaut un jeton d'API. `ticket` + `csrf` : session par ticket (cookie `PVEAuthCookie` + `CSRFPreventionToken`), seule façon
        d'appeler les routes que Proxmox interdit aux jetons (`allowtoken: 0`, comme l'écriture de la double authentification). `anonymous` : aucune
        authentification (seulement pour `POST /access/ticket`, qui interdit justement les jetons)."""
        # Certificat épinglé (PEM) : seul lui est accepté (`app/tlspin.py`) ; il prime sur `verify_ssl`.
        self._pin = pinned_cert
        if anonymous:
            auth_headers: dict[str, str] = {}
        elif ticket is not None:
            auth_headers = {"Cookie": f"PVEAuthCookie={quote(ticket, safe='')}", **({"CSRFPreventionToken": csrf} if csrf else {})}
        else:
            auth_headers = {"Authorization": f"PVEAPIToken={user}!{token_id}={token_secret}"}
        self._ws = (host, port, verify_ssl, auth_headers.get("Authorization", ""))
        self._client = httpx.AsyncClient(
            base_url=f"https://{host}:{port}/api2/json",
            headers=auth_headers,
            verify=context_for(pinned_cert) if pinned_cert else verify_ssl,
            timeout=15,
            transport=transport,
        )

    def ws_target(self, path: str, /, **params) -> tuple[str, dict[str, str], ssl.SSLContext | None]:
        """`(adresse, en-têtes, contexte TLS)` d'un WebSocket Proxmox (console). Même authentification et même règle de
        vérification du certificat que les appels REST. L'adresse contient un ticket : **ne jamais la journaliser**."""
        host, port, verify, auth = self._ws
        query = urlencode(params, quote_via=quote)
        if self._pin:
            ctx = context_for(self._pin)
        else:
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        return f"wss://{host}:{port}/api2/json{path}?{query}", {"Authorization": auth}, ctx

    async def get(self, path: str, /, **params):
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()["data"]

    async def get_envelope(self, path: str, /, **params):
        """Réponse complète de Proxmox (`data` plus les attributs de l'enveloppe, comme `changes` pour le réseau). Lecture seule."""
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, dict) else {"data": body}

    async def get_with_total(self, path: str, /, **params):
        """Comme `get`, mais renvoie aussi le `total` de l'enveloppe (listes paginées comme le journal système) : `(data, total|None)`."""
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        body = r.json()
        total = body.get("total")
        return body["data"], (total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None)

    async def post(self, path: str, /, **data):
        r = await self._client.post(path, data=data)
        r.raise_for_status()
        return r.json()["data"]

    async def put(self, path: str, /, **data):
        r = await self._client.put(path, data=data)
        r.raise_for_status()
        return r.json()["data"]

    async def delete(self, path: str, /, **params):
        r = await self._client.delete(path, params=params)
        r.raise_for_status()
        return r.json()["data"]

    async def upload(self, path: str, /, *, fields: dict[str, str], filename: str, body, length: int):
        """Envoie un fichier en multipart, **en flux** (jamais chargé en mémoire ni écrit sur le disque de Kaji).
        `body` : itérateur asynchrone d'octets de taille totale `length` ; `fields` : champs texte, placés avant le fichier.
        Le Content-Length est calculé d'avance (pveproxy n'accepte pas l'envoi en morceaux)."""
        boundary = "kajiupload" + uuid.uuid4().hex
        head = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
        head += (f'--{boundary}\r\nContent-Disposition: form-data; name="filename"; filename="{filename}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()

        async def stream():
            yield head
            async for chunk in body:
                yield chunk
            yield tail

        r = await self._client.post(path, content=stream(), timeout=httpx.Timeout(30, read=None, write=None),
                                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                             "Content-Length": str(len(head) + length + len(tail))})
        r.raise_for_status()
        return r.json()["data"]

    def add_response_hook(self, hook) -> None:
        """Appelle `await hook(response)` à chaque réponse de Proxmox, avant tout traitement (sert à signaler un jeton personnel refusé). Une exception levée par le crochet remonte à l'appelant."""
        self._client.event_hooks["response"].append(hook)

    async def aclose(self):
        await self._client.aclose()
