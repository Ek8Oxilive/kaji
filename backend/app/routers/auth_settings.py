"""Réglages de connexion par le SSO et l'annuaire, depuis l'interface (lot #443, jalon J2) : `GET/PUT/DELETE /api/auth-settings/{provider}` et un test de connexion. Règles : `app/authconfig.py`, `docs/api/auth-settings.md`.

- Réservé aux ADMINISTRATEURS (la politique de rôles refuse tout le reste par défaut) ; chaque écriture est auditée par les NOMS des réglages changés, jamais une valeur.
- Les secrets sont en écriture seule. `dry_run` valide sans rien écrire ; l'écriture exige `confirm`.
- Le test de connexion n'envoie JAMAIS le mot de passe d'une personne : il lie le compte de lecture (annuaire) ou lit la découverte du fournisseur (SSO).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, authconfig, ldaplogin, oidc
from ..db import get_db
from ..models import AdminUser
from .auth import current_user

router = APIRouter(prefix="/api/auth-settings", tags=["auth"])


class SettingsUpdate(BaseModel):
    values: dict = Field(default_factory=dict, description="Réglages non secrets à changer (les autres restent)")
    secrets: dict = Field(default_factory=dict, description="Secrets à définir (écriture seule)")
    clear_secrets: list[str] = Field(default_factory=list, max_length=4)
    confirm: bool = False
    dry_run: bool = False


def _provider(provider: str) -> str:
    try:
        return authconfig.check_provider(provider)
    except authconfig.SettingError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fournisseur inconnu")


@router.get("")
def read_all(user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    return {p: authconfig.view(db, p) for p in authconfig.PROVIDERS}


@router.put("/{provider}")
def write(provider: str, body: SettingsUpdate, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    provider = _provider(provider)
    if len(body.values) > 20 or len(body.secrets) > 4:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Trop de réglages")
    try:
        changed = authconfig.save(db, provider, body.values, body.secrets, body.clear_secrets, user.username, commit=not body.dry_run and body.confirm)
    except authconfig.SettingError as e:
        audit.record(db, username=user.username, connection_id=None, action="auth-settings", target=provider, status="error", detail=str(e)[:150])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    if body.dry_run:
        return {"dry_run": True, "changes": changed}
    if not body.confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirmation requise (confirm=true)")
    audit.record(db, username=user.username, connection_id=None, action="auth-settings", target=provider, status="started", detail=("modifié : " + ", ".join(changed))[:150] if changed else "aucun changement")
    return authconfig.view(db, provider)


@router.delete("/{provider}")
def reset(provider: str, confirm: bool = False, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Retire les réglages de la base : le `.env` s'applique de nouveau."""
    provider = _provider(provider)
    if not confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirmation requise (confirm=true)")
    removed = authconfig.remove(db, provider)
    audit.record(db, username=user.username, connection_id=None, action="auth-settings", target=provider, status="started", detail="retour au .env" if removed else "rien à retirer")
    return authconfig.view(db, provider)


class TestBody(BaseModel):
    values: dict = Field(default_factory=dict, description="Réglages à essayer par-dessus l'existant, sans les enregistrer")
    secrets: dict = Field(default_factory=dict, description="Secrets à essayer, sans les enregistrer")


@router.post("/{provider}/test")
async def test_connection(provider: str, body: TestBody | None = None, user: AdminUser = Depends(current_user), db: Session = Depends(get_db)):
    """Essaie la configuration sans le mot de passe de personne : celle que contient `body` (valeurs de la fenêtre, NON enregistrées) par-dessus l'existant, ou l'effective sans corps.
    Réponse : `{ok, detail}` (texte court et fixe, jamais une valeur reçue de l'annuaire ou du fournisseur)."""
    provider = _provider(provider)
    if body is not None and (len(body.values) > 20 or len(body.secrets) > 4):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Trop de réglages")
    try:
        s = authconfig.preview(db, provider, body.values, body.secrets) if body is not None else authconfig.effective(db, provider)
    except authconfig.SettingError as e:
        return {"ok": False, "detail": str(e)[:150]}
    if errs := authconfig.problems(provider, s):
        return {"ok": False, "detail": errs[0][:150]}
    if provider == "oidc":
        if not oidc.enabled(s):
            return {"ok": False, "detail": "SSO non configuré"}
        try:
            await oidc.discovery(s)
        except oidc.OidcError as e:
            return {"ok": False, "detail": str(e)[:150]}
        return {"ok": True, "detail": "le fournisseur répond et sa découverte est valide"}
    if not ldaplogin.enabled(s):
        return {"ok": False, "detail": "annuaire non configuré"}
    import asyncio
    try:
        reader = await asyncio.to_thread(ldaplogin._connection, s, s.kaji_ldap_bind_dn, s.kaji_ldap_bind_password)
        try:
            reader.unbind()
        except Exception:
            pass
    except ldaplogin.LdapError as e:
        return {"ok": False, "detail": "compte de lecture refusé par l'annuaire" if str(e) == "liaison refusée" else str(e)[:150]}
    except Exception:
        return {"ok": False, "detail": "annuaire injoignable"}
    return {"ok": True, "detail": "le compte de lecture se lie à l'annuaire (chiffrement et certificat vérifiés)"}
