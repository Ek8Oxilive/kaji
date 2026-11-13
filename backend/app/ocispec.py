"""Images OCI (Proxmox 9) : valider la référence d'une image et mettre en forme la liste des étiquettes. Schéma lu sur `apidoc.js`
(`POST /nodes/{node}/storage/{storage}/oci-registry-pull`, `GET /nodes/{node}/query-oci-repo-tags`).

Le nœud télécharge l'image depuis un registre : un registre local (boucle locale, adresse réservée) est refusé, comme pour les URL de téléchargement.
Les motifs sont ceux du schéma de Proxmox, compilés en ASCII (`\\d` et `\\w` ne doivent pas accepter les chiffres et lettres Unicode).
"""
import ipaddress
import re

_HOST = r"(?:[a-zA-Z\d]|[a-zA-Z\d][a-zA-Z\d-]*[a-zA-Z\d])(?:\.(?:[a-zA-Z\d]|[a-zA-Z\d][a-zA-Z\d-]*[a-zA-Z\d]))*(?::\d+)?"
_REPO = r"[a-z\d]+(?:(?:[._]|__|[-]*)[a-z\d]+)*(?:/[a-z\d]+(?:(?:[._]|__|[-]*)[a-z\d]+)*)*"
REPOSITORY = re.compile(rf"^(?:{_HOST}/)?{_REPO}$", re.ASCII)
REFERENCE = re.compile(rf"^(?:{_HOST}/)?{_REPO}:\w[\w.-]{{0,127}}$", re.ASCII)
TAG = re.compile(r"^\w[\w.-]{0,127}$", re.ASCII)
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$", re.ASCII)
MAX_TAGS = 500


def _check_registry(ref: str) -> None:
    """Refuse un registre local. Convention de Docker : le premier segment est un registre s'il contient « . » ou « : » ou vaut « localhost »."""
    first = ref.split("/", 1)[0] if "/" in ref else ""
    if not (first == "localhost" or "." in first or ":" in first):
        return
    host = first.rsplit(":", 1)[0].lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Registre local refusé")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise ValueError("Registre local refusé")


def check_reference(ref: str) -> str:
    """Référence complète (`[registre/]dépôt:étiquette`). `ValueError` sinon."""
    if not isinstance(ref, str) or len(ref) > 300 or not REFERENCE.fullmatch(ref):
        raise ValueError("Référence d'image invalide (attendu : [registre/]dépôt:étiquette)")
    _check_registry(ref)
    return ref


def check_repository(ref: str) -> str:
    """Dépôt sans étiquette (pour lister ses étiquettes)."""
    if not isinstance(ref, str) or len(ref) > 300 or not REPOSITORY.fullmatch(ref):
        raise ValueError("Dépôt invalide (attendu : [registre/]dépôt, sans étiquette)")
    _check_registry(ref)
    return ref


def check_filename(name: str) -> str:
    if not isinstance(name, str) or not FILENAME.fullmatch(name) or ".." in name:
        raise ValueError("Nom de fichier invalide")
    return name


def shape_tags(raw) -> list[str]:
    """Étiquettes valides seulement, bornées ; Proxmox peut renvoyer une liste de chaînes ou d'objets `{tag}`."""
    out: list[str] = []
    for t in (raw if isinstance(raw, list) else [])[:MAX_TAGS * 2]:
        v = t.get("tag") if isinstance(t, dict) else t
        if isinstance(v, str) and TAG.fullmatch(v) and v not in out:
            out.append(v)
        if len(out) >= MAX_TAGS:
            break
    return out
