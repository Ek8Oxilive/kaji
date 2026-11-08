"""Fichiers ISO, modèles et images à importer : téléchargement par URL et téléversement. Tout est validé, rien n'est transmis tel quel.

Le téléchargement par URL est fait **par le nœud Proxmox** : une URL peut donc sonder le réseau local du nœud (constaté en réel : le nœud
atteint sa propre API sur 127.0.0.1). Kaji refuse les adresses locales littérales, les identifiants dans l'URL et les noms `localhost` ;
un nom DNS qui pointe vers une adresse locale n'est pas détecté (limite documentée).
"""
import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

Content = Literal["iso", "vztmpl", "import"]
FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+()\-]{0,200}")
EXTENSIONS: dict[str, tuple[str, ...]] = {
    "iso": (".iso", ".img"),
    "vztmpl": (".tar.gz", ".tar.xz", ".tar.zst", ".tar.bz2"),
    "import": (".qcow2", ".raw", ".vmdk", ".ova", ".ovf"),
}
ALGOS = {"md5": 32, "sha1": 40, "sha224": 56, "sha256": 64, "sha384": 96, "sha512": 128}
Algo = Literal["md5", "sha1", "sha224", "sha256", "sha384", "sha512"]
URL_CHARS = re.compile(r"[\x21-\x7e]{1,2000}")             # ASCII imprimable, sans espace ni saut de ligne
MAX_UPLOAD = 20 * 1024**3                                   # 20 Gio


def check_filename(name: str, content: str) -> str:
    if not isinstance(name, str) or not FILENAME.fullmatch(name) or ".." in name:
        raise ValueError("Nom de fichier invalide")
    if not name.lower().endswith(EXTENSIONS[content]):
        raise ValueError("Extension attendue : " + ", ".join(EXTENSIONS[content]))
    return name


def check_url(url: str) -> str:
    if not isinstance(url, str) or not URL_CHARS.fullmatch(url):
        raise ValueError("URL invalide")
    try:
        u = urlsplit(url)
        host, _ = u.hostname, u.port
    except ValueError:
        raise ValueError("URL invalide") from None
    if u.scheme not in ("http", "https") or not host:
        raise ValueError("Seules les URL http et https sont acceptées")
    if "@" in u.netloc:
        raise ValueError("Les identifiants dans l'URL ne sont pas acceptés")
    h = host.lower().rstrip(".")
    if h == "localhost" or h.endswith(".localhost"):
        raise ValueError("Adresse locale refusée")
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return url
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise ValueError("Adresse locale refusée")
    return url


def check_checksum(algo: str | None, value: str | None) -> dict[str, str]:
    """Somme de contrôle facultative : l'algorithme et la valeur vont ensemble ; la longueur doit correspondre."""
    if algo is None and value is None:
        return {}
    if algo is None or value is None or algo not in ALGOS:
        raise ValueError("Somme de contrôle : algorithme et valeur sont obligatoires ensemble")
    if len(value) != ALGOS[algo] or not re.fullmatch(r"[0-9a-fA-F]+", value):
        raise ValueError(f"Somme de contrôle invalide pour {algo}")
    return {"checksum-algorithm": algo, "checksum": value.lower()}


def shape_metadata(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    size = r.get("size")
    return {"filename": r["filename"][:255] if isinstance(r.get("filename"), str) else None,
            "mimetype": r["mimetype"][:100] if isinstance(r.get("mimetype"), str) else None,
            "size": size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None}
