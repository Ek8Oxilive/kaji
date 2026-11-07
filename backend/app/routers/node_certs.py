"""Certificat personnalisé d'un nœud : contrôler, installer, retirer (droit `Sys.Modify`). Contrôles locaux : `certspec`.

La clé privée traverse Kaji pour atteindre Proxmox et n'est ni stockée, ni auditée, ni renvoyée.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..certspec import CUSTOM_FILE, CertProblem, CheckCert, CustomCert, analyse
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-certs"], dependencies=[Depends(current_user)])


def _report(db, user, conn_id, action, target, st, detail=None):
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status=st, detail=detail)


async def _has_custom(db, factory, conn_id: int, node: str) -> bool:
    info = await _px(db, factory, conn_id, "get", f"/nodes/{node}/certificates/info")
    return any(isinstance(c, dict) and c.get("filename") == CUSTOM_FILE for c in (info if isinstance(info, list) else []))


@router.post("/nodes/{node}/certificates/custom/check")
async def check_custom(body: CheckCert, conn_id: int, node: str = Path(pattern=NODE)):
    """Contrôle local du certificat et de la clé (aucun appel à Proxmox, rien n'est écrit). Renvoie un résumé sans secret."""
    try:
        return analyse(body.certificates, body.key.get_secret_value())
    except CertProblem as e:
        raise HTTPException(422, str(e)) from None


@router.put("/nodes/{node}/certificates/custom", status_code=status.HTTP_200_OK)
async def install_custom(body: CustomCert, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    target = f"node/{node}"

    def fail(code: int, msg: str):
        _report(db, user, conn_id, "node-cert-install", target, "error", msg)
        raise HTTPException(code, msg)

    if not body.confirm:
        fail(400, "Confirmation requise")
    try:
        summary = analyse(body.certificates, body.key.get_secret_value())
    except CertProblem as e:
        fail(422, str(e))
    if summary["self_signed"] and _get_or_404(db, conn_id).verify_ssl:
        fail(422, "Certificat auto-signé alors que cette connexion vérifie le certificat de Proxmox : Kaji perdrait l'accès au nœud")
    try:
        exists = await _has_custom(db, factory, conn_id, node)
    except HTTPException:
        fail(502, "État des certificats illisible : action refusée par précaution")
    if exists and not body.replace_existing:
        fail(409, "Un certificat personnalisé est déjà installé : confirme son remplacement (replace_existing)")
    try:
        await _px(db, factory, conn_id, "post", f"/nodes/{node}/certificates/custom", certificates=body.certificates,
                  key=body.key.get_secret_value(), force=int(body.replace_existing), restart=int(body.restart))
    except HTTPException as e:
        fail(e.status_code, str(e.detail))
    _report(db, user, conn_id, "node-cert-install", target, "ok", f"empreinte SHA-256 {summary['fingerprint']}")
    return {"ok": True, **summary}


@router.delete("/nodes/{node}/certificates/custom")
async def remove_custom(conn_id: int, node: str = Path(pattern=NODE), confirm: bool = Query(default=False), restart: bool = Query(default=True),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Retire le certificat personnalisé : le nœud revient à son certificat auto-signé par Proxmox."""
    target = f"node/{node}"

    def fail(code: int, msg: str):
        _report(db, user, conn_id, "node-cert-remove", target, "error", msg)
        raise HTTPException(code, msg)

    if not confirm:
        fail(400, "Confirmation requise")
    if _get_or_404(db, conn_id).verify_ssl:
        fail(422, "Cette connexion vérifie le certificat de Proxmox : revenir au certificat auto-signé ferait perdre l'accès à Kaji")
    try:
        exists = await _has_custom(db, factory, conn_id, node)
    except HTTPException:
        fail(502, "État des certificats illisible : action refusée par précaution")
    if not exists:
        fail(409, "Aucun certificat personnalisé n'est installé sur ce nœud")
    try:
        await _px(db, factory, conn_id, "delete", f"/nodes/{node}/certificates/custom", restart=int(restart))
    except HTTPException as e:
        fail(e.status_code, str(e.detail))
    _report(db, user, conn_id, "node-cert-remove", target, "ok")
    return {"ok": True}
