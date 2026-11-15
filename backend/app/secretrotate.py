"""Rotation de `KAJI_SECRET_KEY` (lot #461, runbook d'exploitation) : ré-chiffre les secrets des CONNEXIONS, les webhooks d'alerte et les secrets TOTP de connexion (lot #444) de l'ancienne clé vers la nouvelle.

Sans cette commande, changer la clé rendait illisibles le jeton partagé de chaque connexion et chaque webhook d'alerte (à ressaisir un par un). Procédure (docs/runbook.md) : sauvegarde ;
`KAJI_SECRET_KEY` = nouvelle clé et `KAJI_SECRET_KEY_PREVIOUS` = ancienne ; `rotate-secret-key --yes` (backend arrêté ou non) ; retrait de `KAJI_SECRET_KEY_PREVIOUS` ; redémarrage.
Tout ou rien (une transaction), rejouable (un secret déjà lisible avec la nouvelle clé est laissé tel quel), relecture de chaque secret avec la SEULE nouvelle clé avant de valider, ne renvoie que des
nombres. Les codes de secours TOTP sont de simples empreintes SHA-256 : la rotation ne les concerne pas. **Les sessions sont signées avec cette clé : elles tombent toutes** (reconnexion). Les jetons personnels et de service ont leur propre clé (`app/tokenkey.py`) et ne sont pas touchés.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .crypto import decrypt, encrypt
from .models import AlertRule, AuthSetting, Connection, UserTotp


class SecretRotationError(Exception):
    pass


@dataclass
class SecretRotationResult:
    connections: int = 0
    webhooks: int = 0
    totp: int = 0
    auth: int = 0
    already_current: int = 0


def _readable(key: str, blob: str | None) -> bool:
    try:
        decrypt(key, blob or "")
        return True
    except ValueError:
        return False


def rotate_secret_key(db: Session, new_key: str, old_key: str) -> SecretRotationResult:
    """Ré-chiffre `connections.token_secret_enc`, `alert_rules.webhook_enc` et `user_totp.secret_enc`. Lève `SecretRotationError` (rien n'est modifié) si les deux clés sont identiques ou manquantes, ou si un secret n'est lisible
    avec aucune des deux."""
    if not new_key or not old_key:
        raise SecretRotationError("Il faut les DEUX clés : KAJI_SECRET_KEY (la nouvelle) et KAJI_SECRET_KEY_PREVIOUS (l'ancienne).")
    if new_key == old_key:
        raise SecretRotationError("KAJI_SECRET_KEY_PREVIOUS est identique à KAJI_SECRET_KEY : il n'y a rien à faire tourner.")
    items = [(c, "token_secret_enc", "connections") for c in db.scalars(select(Connection).order_by(Connection.id))]
    items += [(r, "webhook_enc", "webhooks") for r in db.scalars(select(AlertRule).order_by(AlertRule.id)) if r.webhook_enc]
    items += [(t, "secret_enc", "totp") for t in db.scalars(select(UserTotp).order_by(UserTotp.user_id))]
    items += [(a, "secret_enc", "auth") for a in db.scalars(select(AuthSetting).order_by(AuthSetting.provider)) if a.secret_enc]       # secrets SSO / annuaire du menu Authentification
    unreadable = [kind for obj, attr, kind in items if not (_readable(new_key, getattr(obj, attr)) or _readable(old_key, getattr(obj, attr)))]
    if unreadable:
        raise SecretRotationError(f"{len(unreadable)} secret(s) sur {len(items)} ne sont lisibles par aucune des deux clés : rien n'a été modifié. Vérifie les clés (ou ressaisis la connexion concernée).")
    res = SecretRotationResult()
    try:
        for obj, attr, kind in items:
            blob = getattr(obj, attr)
            if _readable(new_key, blob):                                    # déjà fait (rotation rejouée) : on ne touche pas
                res.already_current += 1
                continue
            setattr(obj, attr, encrypt(new_key, decrypt(old_key, blob)))
            if not _readable(new_key, getattr(obj, attr)):                  # relecture avec la SEULE nouvelle clé
                raise SecretRotationError("Un secret ré-chiffré n'est pas lisible avec la nouvelle clé : rien n'a été modifié.")
            if kind == "connections":
                res.connections += 1
            elif kind == "totp":
                res.totp += 1
            elif kind == "auth":
                res.auth += 1
            else:
                res.webhooks += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return res
