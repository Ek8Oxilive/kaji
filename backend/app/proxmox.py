import httpx


class ProxmoxClient:
    """Client async pour l'API REST Proxmox (auth par API token).

    Une instance par connexion enregistrée, créée à la demande.
    """

    def __init__(self, host: str, user: str, token_id: str, token_secret: str,
                 port: int = 8006, verify_ssl: bool = False):
        self._client = httpx.AsyncClient(
            base_url=f"https://{host}:{port}/api2/json",
            headers={"Authorization": f"PVEAPIToken={user}!{token_id}={token_secret}"},
            verify=verify_ssl,
            timeout=15,
        )

    async def get(self, path: str, **params):
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()["data"]

    async def post(self, path: str, **data):
        r = await self._client.post(path, data=data)
        r.raise_for_status()
        return r.json()["data"]

    async def aclose(self):
        await self._client.aclose()
