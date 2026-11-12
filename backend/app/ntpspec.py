"""Serveurs NTP d'un nœud : génère le fichier de sources `chrony` et les commandes à copier. **Kaji n'écrit rien chez Proxmox.**

L'API de Proxmox VE 9 n'a aucune route NTP : `/nodes/{n}/time` n'accepte que `timezone` (`apidoc.js`). La synchronisation se règle dans
`chrony` sur le nœud. Kaji valide chaque champ (liste blanche, jamais de texte libre) et fabrique ce qu'il faut coller dans la console du
nœud. Le format est celui de Debian (`sourcedir /etc/chrony/sources.d` : un fichier `*.sources` de lignes `server` / `pool`), mais **Kaji
ne peut pas relire la configuration du nœud** : la première commande vérifie que la directive `sourcedir` existe avant d'écrire.
"""
import ipaddress
import re

from pydantic import BaseModel, Field, field_validator

NAME = r"^[a-z0-9][a-z0-9-]{0,59}$"
HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?){0,10}")
DIR = "/etc/chrony/sources.d"


def is_ip(v: str) -> bool:
    try:
        ipaddress.ip_address(v)
        return True
    except ValueError:
        return False


class NtpSource(BaseModel):
    host: str = Field(max_length=253)
    kind: str = Field(default="server", pattern=r"^(server|pool)$")
    iburst: bool = True
    nts: bool = False

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        if "%" in v or not (is_ip(v) or HOST.fullmatch(v)):          # `%` : identifiant de zone IPv6, refusé
            raise ValueError("nom d'hôte ou adresse IP invalide")
        if not is_ip(v) and v.rsplit(".", 1)[-1].isdigit():          # « 1.1.1.256 » : une fausse adresse IP n'est pas un nom d'hôte
            raise ValueError("nom d'hôte ou adresse IP invalide")
        return v.lower()


class NtpConfig(BaseModel):
    name: str = Field(pattern=NAME, description="Nom du fichier : /etc/chrony/sources.d/<name>.sources")
    sources: list[NtpSource] = Field(min_length=1, max_length=4)

    @field_validator("sources")
    @classmethod
    def _sources(cls, v: list[NtpSource]) -> list[NtpSource]:
        if len({s.host for s in v}) != len(v):
            raise ValueError("doublon")
        for s in v:
            if s.kind == "pool" and is_ip(s.host):
                raise ValueError("un « pool » demande un nom d'hôte, pas une adresse IP")
        return v


def line(s: NtpSource) -> str:
    return " ".join([s.kind, s.host] + (["iburst"] if s.iburst else []) + (["nts"] if s.nts else []))


def render(c: NtpConfig) -> str:
    return "\n".join(line(s) for s in c.sources) + "\n"


def file_path(c: NtpConfig) -> str:
    return f"{DIR}/{c.name}.sources"


def commands(c: NtpConfig) -> list[str]:
    """Contrôle de la directive, écriture du fichier (délimiteur entre guillemets : rien n'est interprété), rechargement, vérification."""
    return [f"grep -E '^sourcedir {DIR}' /etc/chrony/chrony.conf",
            f"cat > {file_path(c)} <<'KAJI_EOF'\n{render(c)}KAJI_EOF",
            "chronyc reload sources",
            "chronyc sources -v"]


def warnings(c: NtpConfig) -> list[str]:
    out = ["la première commande doit afficher la ligne « sourcedir /etc/chrony/sources.d » : sinon ce nœud n'a pas la configuration Debian habituelle, n'écris rien et ajoute les lignes dans /etc/chrony/chrony.conf à la main"]
    if any(s.nts for s in c.sources):
        out.append("NTS : le serveur doit le proposer ; sinon chrony n'utilisera pas cette source")
    if any(s.kind == "server" and not s.iburst for s in c.sources):
        out.append("sans « iburst » : la première synchronisation sera plus lente")
    if any(is_ip(s.host) and (ipaddress.ip_address(s.host).is_private or ipaddress.ip_address(s.host).is_loopback) for s in c.sources):
        out.append("adresse du réseau local : le serveur doit être joignable depuis le nœud")
    return out
