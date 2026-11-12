"""Console SPICE : le fichier `.vv` que `virt-viewer` ouvre, construit à partir de la réponse de Proxmox (`spiceproxy`).

Proxmox renvoie la configuration du fichier (hôte, port TLS, **ticket à usage unique**, proxy, certificat…). Rien n'est recopié tel quel : seules les
clés connues sont gardées, chaque valeur est contrôlée (jamais de saut de ligne, qui permettrait d'ajouter une section ou une clé au fichier),
et une réponse incomplète ou suspecte est refusée. Le ticket n'est jamais journalisé ni audité.
"""
import re

# clé -> motif que la valeur doit respecter en entier (`fullmatch`)
_HOST = r"[A-Za-z0-9._\-\[\]:]{1,255}"
_PRINT = r"[\x20-\x7e]{1,%d}"
VALUE = {
    "type": r"spice",
    "title": _PRINT % 120,
    "host": _HOST,
    "proxy": rf"https?://{_HOST}",
    "tls-port": r"[0-9]{1,5}",
    "password": r"[\x21-\x7e]{1,512}",              # le ticket : caractères imprimables sans espace
    "host-subject": _PRINT % 1024,
    "delete-this-file": r"[01]",
    "secure-attention": _PRINT % 64,
    "release-cursor": _PRINT % 64,
    "toggle-fullscreen": _PRINT % 64,
    "fullscreen": r"[01]",
}
NUMERIC = ("tls-port", "delete-this-file", "fullscreen")      # clés que Proxmox peut envoyer sous forme de nombre
REQUIRED = ("type", "host", "tls-port", "password")
ORDER = ("type", "title", "host", "tls-port", "password", "proxy", "ca", "host-subject", "delete-this-file", "secure-attention", "release-cursor", "toggle-fullscreen", "fullscreen")
_CA = re.compile(r"[-A-Za-z0-9+/=\n\\ ]{1,8192}")   # certificat PEM : lettres, chiffres, + / = - espaces, sauts de ligne


class SpiceError(ValueError):
    """Réponse de Proxmox inexploitable (message fixe, sans valeur issue de la réponse)."""


def build_vv(reply) -> str:
    """Contenu du fichier `.vv`, ou `SpiceError`."""
    if not isinstance(reply, dict):
        raise SpiceError("Réponse inattendue de Proxmox pour la console SPICE")
    out: dict[str, str] = {}
    for key in ORDER:
        if key not in reply:
            continue
        v = reply[key]
        if isinstance(v, (bool, int)):
            if key not in NUMERIC or (isinstance(v, bool) and key == "tls-port"):      # un nombre n'est admis que là où il a un sens ; jamais un booléen comme port
                raise SpiceError("Réponse inattendue de Proxmox pour la console SPICE")
            v = str(int(v))
        if not isinstance(v, str):
            raise SpiceError("Réponse inattendue de Proxmox pour la console SPICE")
        if key == "ca":
            if not _CA.fullmatch(v):
                raise SpiceError("Réponse inattendue de Proxmox pour la console SPICE")
            v = v.replace("\n", "\\n")                  # le format .vv écrit les sauts de ligne du certificat en `\n`
        elif not re.fullmatch(VALUE[key], v):
            raise SpiceError("Réponse inattendue de Proxmox pour la console SPICE")
        out[key] = v
    if any(k not in out for k in REQUIRED) or not 1 <= int(out["tls-port"]) <= 65535:
        raise SpiceError("Réponse inattendue de Proxmox pour la console SPICE")
    return "[virt-viewer]\n" + "".join(f"{k}={v}\n" for k, v in out.items())


def proxy_host(host: str) -> str | None:
    """Nom ou adresse du nœud à donner comme proxy (celui de la connexion de Kaji), ou `None` s'il n'est pas sûr."""
    return host if re.fullmatch(_HOST, host) else None
