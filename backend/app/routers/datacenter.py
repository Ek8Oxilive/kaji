"""Options du datacenter (Datacenter → Options) et notes du datacenter. Validation et liste blanche : `app/datacenterspec.py`. Droit Proxmox : `Sys.Audit` (lire), `Sys.Modify` sur `/` (écrire)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import audit
from ..clusterwrite import PHRASE
from ..datacenterspec import (DELNAME, FENCING_EXPERIMENTAL, HA_CLEARABLE, KEY, DatacenterOptions, build, digest_of, parse_bwlimit, parse_crs, parse_ha, parse_next_id, parse_replication,
                              parse_tag_list, parse_tag_style, parse_user_tag_access, parse_webauthn, shape_options)
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/datacenter", tags=["datacenter"], dependencies=[Depends(current_user)])


def _read(raw) -> dict:
    shaped = shape_options(raw)
    return {**shaped, "digest": digest_of(shaped)}


@router.get("/options")
async def get_options(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Options lues (champs gérés + champs en lecture seule) et `digest` (empreinte de Kaji, à renvoyer avec la modification)."""
    return _read(await _px(db, factory, conn_id, "get", "/cluster/options"))


def _same(k: str, got, want) -> bool:
    if k in ("description", "consent-text"):
        return (got or "").rstrip("\n") == want.rstrip("\n")
    if k == "registered-tags":
        return got == parse_tag_list(want)
    if k == "user-tag-access":
        return got == parse_user_tag_access(want)
    if k == "mac_prefix":
        return isinstance(got, str) and got.upper() == want.upper()
    if k == "migration":
        typ, _, net = (want[len("type="):]).partition(",network=")
        return got == {"type": typ, "network": net or None}
    if k == "next-id":
        return got == parse_next_id(want)
    if k == "tag-style":
        return got == parse_tag_style(want)
    if k == "ha":
        return got == parse_ha(want)
    if k == "crs":
        return got == parse_crs(want)
    if k == "bwlimit":
        return got == parse_bwlimit(want)
    if k == "replication":
        return got == parse_replication(want)
    if k == "webauthn":
        return got == parse_webauthn(want)
    return got == want


def _webauthn_break(cur: dict, params: dict, delete: list[str]) -> bool:
    """Changer ou retirer une valeur WebAuthn DÉJÀ définie casse les credentials existants (`id`) ou peut les casser (`origin`, `rp`, sous-domaines) : verrou à phrase."""
    if not any(cur.get(k) is not None for k in ("id", "origin", "rp")):
        return False                                                  # rien de défini : aucun credential ne peut exister
    if "webauthn" in delete:
        return True
    if "webauthn" not in params:
        return False
    new = parse_webauthn(params["webauthn"])
    sub = lambda d: True if d["allow_subdomains"] is None else d["allow_subdomains"]          # noqa: E731  (par défaut Proxmox : 1)
    return any(cur[k] is not None and new[k] != cur[k] for k in ("id", "origin", "rp")) or sub(new) != sub(cur)


def _blank(v) -> bool:
    """Réglage retiré : absent, chaîne vide, ou objet sans aucune valeur (constaté : les notes retirées reviennent en chaîne vide)."""
    return v in (None, "") or (isinstance(v, list) and not v) or (isinstance(v, dict) and all(x is None or x == "" or x is False or (isinstance(x, list) and not x) for x in v.values()))   # 0 est une valeur (débit), pas du vide


@router.put("/options")
async def put_options(body: DatacenterOptions, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="datacenter-options", target="datacenter", status=st, detail=detail)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, /, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    cur = _read(await px("get", "/cluster/options"))
    if body.digest is not None and body.digest != cur["digest"]:
        refuse("Les options ont changé depuis ta lecture (digest périmé) : recharge avant de modifier", status.HTTP_409_CONFLICT)
    try:
        params, delete, _ = build(body, cur)
    except ValueError as e:
        refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    insecure = "migration" in params and params["migration"].startswith("type=insecure") and cur["migration"]["type"] != "insecure"
    rep_insecure = "replication" in params and params["replication"].startswith("type=insecure") and cur["replication"]["type"] != "insecure"
    ha_effect = any(k in params for k in ("ha", "crs", "fencing")) or any(k in delete for k in HA_CLEARABLE)       # change ce que fait la HA à l'arrêt, à la reprise ou au placement
    hw_fencing = params.get("fencing") in FENCING_EXPERIMENTAL and cur["fencing"] != params["fencing"]
    wa_effect = "webauthn" in params or "webauthn" in delete
    wa_break = wa_effect and _webauthn_break(cur["webauthn"], params, delete)
    locks = {"insecure": insecure, "replication_insecure": rep_insecure, "ha": ha_effect, "fencing_experimental": hw_fencing, "webauthn": wa_effect, "webauthn_break": wa_break}
    if body.dry_run:
        return {"dry_run": True, "params": {k: ("défini" if k in ("description", "consent-text") else v) for k, v in params.items()}, "remove": delete, "locks": locks}
    if insecure and not body.confirm:
        refuse("Migration non chiffrée : le trafic de migration (mémoire des machines) circulera en clair. Renvoie la requête avec confirm=true", status.HTTP_409_CONFLICT)
    if rep_insecure and not body.confirm:
        refuse("Réplication non chiffrée : le trafic de réplication (disques des machines) circulera en clair. Renvoie la requête avec confirm=true", status.HTTP_409_CONFLICT)
    if ha_effect and not body.confirm:
        refuse("Réglage de la haute disponibilité : il change ce que fait la HA à l'arrêt d'un nœud, à la reprise ou au placement des machines. Renvoie la requête avec confirm=true", status.HTTP_409_CONFLICT)
    if wa_effect and not body.confirm:
        refuse("Réglage WebAuthn : il peut empêcher des comptes de valider leur double authentification. Renvoie la requête avec confirm=true", status.HTTP_409_CONFLICT)
    if wa_break and not (body.acknowledge_cut_access and body.type_name == PHRASE):
        refuse("Changer ou retirer un réglage WebAuthn déjà défini casse (ou peut casser) les credentials existants : des comptes pourraient ne plus pouvoir se connecter. "
               f"Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
    if hw_fencing and not (body.acknowledge_cut_access and body.type_name == PHRASE):
        refuse("Fencing matériel (expérimental dans Proxmox) : sans appareils configurés dans /etc/pve/ha/fence.cfg, la HA ne reprendra plus les machines d'un nœud tombé. "
               f"Renvoie la requête avec acknowledge_cut_access=true et type_name=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
    send = dict(params)
    if delete:
        send["delete"] = ",".join(DELNAME.get(k, k) for k in delete)
    await px("put", "/cluster/options", **send)
    fresh = _read(await px("get", "/cluster/options"))
    after = fresh
    for k, v in params.items():
        if not _same(k, after.get(KEY.get(k, k)), v):
            refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    for k in delete:
        if not _blank(after.get(k)):                # constaté en réel : les notes retirées reviennent en chaîne vide
            refuse("Proxmox n'a pas retiré le réglage", status.HTTP_502_BAD_GATEWAY)
    log("started", ", ".join(f"{k}={'défini' if k in ('description', 'consent-text') else v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else ""))
    return {"changed": sorted(params), "removed": delete, "locks": locks, **fresh}
