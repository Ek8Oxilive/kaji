"""Rotation de la clé des jetons Proxmox personnels (lot #440) : ré-chiffre chaque jeton avec la clé COURANTE.

Procédure (docs/deploiement.md) : sauvegarde (`tools/backup.sh`) ; `KAJI_TOKEN_KEY` = nouvelle clé et `KAJI_TOKEN_KEY_PREVIOUS` = ancienne, redémarrage ; `rotate-token-key` ; retrait de
`KAJI_TOKEN_KEY_PREVIOUS`, redémarrage. Tout ou rien : une seule transaction, relecture de chaque jeton avec la SEULE nouvelle clé avant de valider. Ne renvoie que des nombres.
"""
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import tokenkey
from .models import UserToken


class RotationError(Exception):
    pass


@dataclass
class RotationResult:
    total: int = 0
    rotated: int = 0
    dropped: int = 0


def rotate_all(db: Session, key_list: list[str], *, drop_unreadable: bool = False) -> RotationResult:
    """`key_list` = [courante, précédente]. Lève `RotationError` (rien n'est modifié) s'il faut deux clés, ou si un jeton n'est lisible par aucune (sauf `drop_unreadable`)."""
    if len(key_list) < 2:
        raise RotationError("Il faut les DEUX clés : KAJI_TOKEN_KEY (la nouvelle) et KAJI_TOKEN_KEY_PREVIOUS (l'ancienne).")
    current = [key_list[0]]
    res = RotationResult()
    rows = list(db.scalars(select(UserToken).order_by(UserToken.id)))
    res.total = len(rows)
    unreadable = [r for r in rows if not tokenkey.readable(r.secret_enc, key_list)]
    if unreadable and not drop_unreadable:
        raise RotationError(f"{len(unreadable)} jeton(s) personnel(s) sur {len(rows)} ne sont lisibles par aucune des deux clés : rien n'a été modifié. "
                            "Vérifie les clés, ou relance avec --drop-unreadable pour supprimer ces jetons (leurs propriétaires devront les enregistrer de nouveau).")
    try:
        for r in rows:
            if r in unreadable:
                db.delete(r)
                res.dropped += 1
                continue
            r.secret_enc = tokenkey.rotate(r.secret_enc, key_list)
            if not tokenkey.readable(r.secret_enc, current):                  # relecture avec la SEULE nouvelle clé : sinon on annule tout
                raise RotationError("Un jeton ré-chiffré n'est pas lisible avec la nouvelle clé : rien n'a été modifié.")
            res.rotated += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return res
