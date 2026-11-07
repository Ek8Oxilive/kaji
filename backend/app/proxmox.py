import ssl
from urllib.parse import quote, urlencode

import httpx


class ProxmoxClient:
    """Client async pour l'API REST Proxmox (auth par API token).

    Une instance par connexion enregistrée, créée à la demande.
    """

    def __init__(self, host: str, user: str, token_id: str, token_secret: str,
                 port: int = 8006, verify_ssl: bool = False,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._ws = (host, port, verify_ssl, f"PVEAPIToken={user}!{token_id}={token_secret}")
        self._client = httpx.AsyncClient(
            base_url=f"https://{host}:{port}/api2/json",
            headers={"Authorization": f"PVEAPIToken={user}!{token_id}={token_secret}"},
            verify=verify_ssl,
            timeout=15,
            transport=transport,
        )

    def ws_target(self, path: str, /, **params) -> tuple[str, dict[str, str], ssl.SSLContext | None]:
        """`(adresse, en-têtes, contexte TLS)` d'un WebSocket Proxmox (console). Même authentification et même règle de
        vérification du certificat que les appels REST. L'adresse contient un ticket : **ne jamais la journaliser**."""
        host, port, verify, auth = self._ws
        query = urlencode(params, quote_via=quote)
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return f"wss://{host}:{port}/api2/json{path}?{query}", {"Authorization": auth}, ctx

    async def get(self, path: str, /, **params):
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()["data"]

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

    async def aclose(self):
        await self._client.aclose()
