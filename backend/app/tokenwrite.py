"""Tokens d'API Proxmox : créer et révoquer, un à la fois, avec l'identité de la session administrateur.

Garde-fous (`docs/m6-ecriture.md`, §5, point 6 en particulier) :
- le **secret** d'un token n'est renvoyé qu'**une seule fois**, dans la réponse de la création ; il n'est ni journalisé, ni conservé, et aucune autre
  route ne peut le relire (Proxmox ne le redonne jamais) ;
- Kaji ne crée que des tokens à **privilèges séparés** (`privsep=1`) : sans droit tant qu'une ACL ne leur en donne pas. Un token sans séparation hériterait de tous
  les droits de son utilisateur : refusé ;
- uniquement pour un utilisateur du realm `pve`, jamais pour `root@pam`, Kaji ni la session administrateur ; jamais de révocation du token de Kaji ou de ces comptes ;
- `confirm=true` et l'identifiant complet `utilisateur!token` retapé ; état relu avant et après.
"""
import re

from pydantic import Field, StrictBool, field_validator

from .adminsession import SECRET, TOKEN_ID
from .userwrite import MAX_EXPIRE, Confirmed, _note, _user

TOKEN_RX = re.compile(TOKEN_ID.pattern)
MAX_TOKENS = 20                                   # par utilisateur : au-delà, on refuse de créer (ménage d'abord)


def check_token_id(v: str) -> str:
    if not isinstance(v, str) or not TOKEN_RX.fullmatch(v):
        raise ValueError("Nom de token invalide")
    return v


def full_id(userid: str, tokenid: str) -> str:
    return f"{userid}!{tokenid}"


class TokenCreate(Confirmed):
    userid: str = Field(max_length=80)
    tokenid: str = Field(max_length=64)
    comment: str | None = Field(default=None, max_length=100)
    expire: int | None = Field(default=None, ge=0, le=MAX_EXPIRE, description="Secondes depuis 1970 ; 0 ou absent = pas d'expiration")
    privsep: StrictBool = True

    _u = field_validator("userid")(lambda cls, v: _user(v))
    _t = field_validator("tokenid")(lambda cls, v: check_token_id(v))
    _c = field_validator("comment")(lambda cls, v: _note(v))

    @field_validator("privsep")
    @classmethod
    def _privsep(cls, v: bool):
        if v is not True:
            raise ValueError("Seuls les tokens à privilèges séparés sont créés ici")
        return v


def create_params(b: TokenCreate) -> dict[str, str | int]:
    p: dict[str, str | int] = {"privsep": 1}
    if b.comment:
        p["comment"] = b.comment
    if b.expire is not None:
        p["expire"] = b.expire
    return p


def shape_tokens(raw) -> list[dict]:
    """Liste des tokens d'un utilisateur, en liste blanche. Si Proxmox renvoyait une valeur secrète par erreur, elle n'est jamais reprise."""
    out = []
    for r in raw if isinstance(raw, list) else []:
        tid = r.get("tokenid") if isinstance(r, dict) else None
        if not isinstance(tid, str) or not TOKEN_RX.fullmatch(tid):
            continue
        exp = r.get("expire")
        out.append({"tokenid": tid, "privsep": r.get("privsep") in (1, True, "1"),
                    "expire": exp if isinstance(exp, int) and not isinstance(exp, bool) and exp > 0 else None,
                    "comment": r["comment"][:100] if isinstance(r.get("comment"), str) else None})
    return sorted(out, key=lambda t: t["tokenid"])


def secret_of(raw) -> str | None:
    """Le secret renvoyé par la création, seulement s'il a la forme attendue (UUID) ; sinon None (on ne relaie pas une valeur inattendue)."""
    v = raw.get("value") if isinstance(raw, dict) else None
    return v if isinstance(v, str) and SECRET.fullmatch(v) else None
