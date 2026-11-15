"""SSO par OpenID Connect (lot #443, jalon J2) : départ vers le fournisseur, retour, et état pour l'écran de connexion. Détail des vérifications : `app/oidc.py`, `docs/api/sso.md`.

- Désactivé (404) tant que `KAJI_OIDC_ISSUER` est vide ; le mot de passe local reste le repli.
- Le SSO REMPLACE l'ouverture de session, pas le compte : il faut un compte de Kaji (existant, relié à la personne) ou `KAJI_OIDC_AUTO_CREATE`. Le rôle reste celui du compte de Kaji.
- Le fournisseur a déjà authentifié la personne (et son second facteur éventuel) : le TOTP de Kaji n'est pas redemandé.
- Tout refus renvoie vers `/?sso=erreur` (jamais le détail) et est audité par un MOTIF COURT, jamais une valeur reçue.
"""
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import audit, authconfig, oidc, rolemap
from ..db import get_db
from ..security import throttle
from .auth import _ip, _start_session

COOKIE = "kaji_oidc"
PATH = "/api/auth/oidc"
router = APIRouter(prefix=PATH, tags=["auth"])


def _refuse(db: Session, request: Request, reason: str) -> RedirectResponse:
    throttle.fail(f"sso:{_ip(request)}")
    audit.record(db, username="sso", connection_id=None, action="login-sso", target="oidc", status="error", detail=reason[:150])
    resp = RedirectResponse("/?sso=erreur", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(COOKIE, path=PATH)
    return resp


@router.get("/status")
def sso_status(db: Session = Depends(get_db)):
    s = authconfig.effective(db, "oidc")                                     # réglages de l'interface, puis `.env` (`app/authconfig.py`)
    return {"enabled": oidc.enabled(s), "label": s.kaji_oidc_label[:40] if oidc.enabled(s) else None}


@router.get("/login")
async def sso_login(request: Request, db: Session = Depends(get_db)):
    s = authconfig.effective(db, "oidc")
    if not oidc.enabled(s):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO non configuré")
    if throttle.blocked(f"sso:{_ip(request)}"):
        return RedirectResponse("/?sso=trop", status_code=status.HTTP_303_SEE_OTHER)
    try:
        doc = await oidc.discovery(s)
    except oidc.OidcError as e:
        return _refuse(db, request, str(e))
    flow = oidc.new_flow()
    resp = RedirectResponse(oidc.authorize_url(doc, flow, s), status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(COOKIE, oidc.seal_flow(s.kaji_secret_key, flow), max_age=oidc.STATE_SECONDS, httponly=True, secure=s.kaji_cookie_secure,
                    samesite="lax", path=PATH)            # « lax » : le cookie doit suivre le retour du fournisseur (navigation de haut niveau venue d'un autre site)
    return resp


@router.get("/callback")
async def sso_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    s = authconfig.effective(db, "oidc")
    if not oidc.enabled(s):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO non configuré")
    if throttle.blocked(f"sso:{_ip(request)}"):
        return RedirectResponse("/?sso=trop", status_code=status.HTTP_303_SEE_OTHER)
    flow = oidc.open_flow(s.kaji_secret_key, request.cookies.get(COOKIE))
    if flow is None:
        return _refuse(db, request, "état de connexion absent ou expiré")
    if error:
        return _refuse(db, request, "refus du fournisseur")                              # le motif du fournisseur n'est pas recopié
    if not code or not state or len(code) > 2048 or len(state) > 256 or not hmac.compare_digest(state.encode(), flow["state"].encode()):
        return _refuse(db, request, "état invalide")
    try:
        doc = await oidc.discovery(s)
        id_token = await oidc.exchange_code(doc, code, flow["verifier"], s)
        claims = await oidc.verify_id_token(doc, id_token, flow["nonce"], s)
    except oidc.OidcError as e:
        return _refuse(db, request, str(e))
    groups = rolemap.as_list(claims.get(s.kaji_oidc_groups_claim))[:500]
    user = oidc.resolve_user(db, doc["issuer"], claims, s, groups)
    if user is None:
        return _refuse(db, request, "aucun compte de Kaji pour cette personne")
    if change := rolemap.apply(db, user, rolemap.target_role(s, "oidc", groups)):                  # groupes → rôle, à chaque connexion (sans groupe configuré : rien)
        audit.record(db, username=user.username, connection_id=None, action="role-sync", target="oidc", status="started", detail=f"rôle {change[0]} → {change[1]} (groupes du fournisseur)")
    throttle.reset(f"sso:{_ip(request)}")
    resp = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _start_session(db, resp, user.id)
    resp.delete_cookie(COOKIE, path=PATH)                                               # l'état ne sert qu'une fois
    audit.record(db, username=user.username, connection_id=None, action="login-sso", target="oidc", status="started", detail="connexion par le fournisseur d'identité")
    return resp
