"""Téléverser un fichier (ISO, modèle, image) ou le faire télécharger par le nœud depuis une URL."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..isospec import MAX_UPLOAD, Algo, Content, check_checksum, check_filename, check_url, shape_metadata
from ..models import AdminUser
from ..vmspec import STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/nodes/{node}", tags=["downloads"], dependencies=[Depends(current_user)])


class DownloadBody(BaseModel):
    url: str = Field(max_length=2000)
    filename: str = Field(max_length=255)
    content: Content
    checksum_algorithm: Algo | None = None
    checksum: str | None = Field(default=None, max_length=128)
    verify_certificates: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return check_url(v)


class Ctx:
    def __init__(self, db, factory, user, conn_id, action, target):
        self.db, self.factory, self.user, self.conn_id, self.action, self.target = db, factory, user, conn_id, action, target

    def log(self, st, detail=None, upid=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action,
                     target=self.target, status=st, detail=detail, upid=upid)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method, path, /, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise


def _upid(v):
    return v if isinstance(v, str) else None


@router.get("/url-metadata")
async def url_metadata(conn_id: int, node: str = Path(pattern=NODE), url: str = Query(max_length=2000),
                       verify_certificates: bool = Query(default=True), db: Session = Depends(get_db),
                       factory: Factory = Depends(get_client_factory)):
    """Nom, taille et type d'un fichier distant (requête HEAD faite par le nœud). Ne télécharge rien."""
    try:
        check_url(url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return shape_metadata(await _px(db, factory, conn_id, "get", f"/nodes/{node}/query-url-metadata", url=url,
                                    **{"verify-certificates": 1 if verify_certificates else 0}))


@router.post("/storage/{storage}/download-url", status_code=status.HTTP_202_ACCEPTED)
async def download_url(body: DownloadBody, conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       user: AdminUser = Depends(current_user)):
    """Le nœud télécharge le fichier dans le stockage (tâche longue). Un fichier de même nom est refusé par Proxmox."""
    c = Ctx(db, factory, user, conn_id, "storage-download", f"{storage}/{body.filename}@{node}")
    try:
        check_filename(body.filename, body.content)
        sums = check_checksum(body.checksum_algorithm, body.checksum)
    except ValueError as e:
        c.refuse(str(e), 422)
    params = {"url": body.url, "filename": body.filename, "content": body.content,
              "verify-certificates": 1 if body.verify_certificates else 0, **sums}
    upid = await c.px("post", f"/nodes/{node}/storage/{storage}/download-url", **params)
    # L'URL n'est pas journalisée en entier : elle peut porter un jeton dans sa requête.
    host = body.url.split("/")[2] if body.url.count("/") >= 2 else "?"
    c.log("started", f"{body.content} depuis {host}" + (f", {body.checksum_algorithm} exigé" if sums else ", sans somme de contrôle"), upid=_upid(upid))
    return {"upid": upid, "node": node}


@router.post("/storage/{storage}/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload(request: Request, conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern),
                 filename: str = Query(max_length=255), content: Content = Query(),
                 checksum_algorithm: Algo | None = Query(default=None), checksum: str | None = Query(default=None, max_length=128),
                 db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Téléverse un fichier : le **corps de la requête est le fichier** (flux, jamais gardé sur le disque de Kaji), taille obligatoire
    et limitée à 20 Gio."""
    c = Ctx(db, factory, user, conn_id, "storage-upload", f"{storage}/{filename}@{node}")
    try:
        check_filename(filename, content)
        sums = check_checksum(checksum_algorithm, checksum)
    except ValueError as e:
        c.refuse(str(e), 422)
    raw = request.headers.get("content-length", "")
    if not raw.isdigit() or int(raw) < 1:
        c.refuse("Taille du fichier obligatoire (en-tête Content-Length)", 411)
    length = int(raw)
    if length > MAX_UPLOAD:
        c.refuse("Fichier trop gros (20 Gio au plus)", 413)

    async def body():
        got = 0
        async for chunk in request.stream():
            got += len(chunk)
            if got > length:
                raise HTTPException(400, "Le fichier dépasse la taille annoncée")
            yield chunk

    try:
        upid = await c.px("upload", f"/nodes/{node}/storage/{storage}/upload", fields={"content": content, **sums},
                          filename=filename, body=body(), length=length)
    except HTTPException:
        raise
    except Exception:                                       # envoi interrompu (navigateur fermé, taille fausse…)
        c.refuse("Envoi interrompu", 400)
    c.log("started", f"{content}, {length} octets" + (f", {checksum_algorithm} exigé" if sums else ""), upid=_upid(upid))
    return {"upid": upid, "node": node}
