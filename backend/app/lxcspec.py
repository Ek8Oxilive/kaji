"""Paramètres sûrs de création d'un conteneur LXC : tout est validé, rien n'est transmis tel quel à Proxmox."""
import re

from pydantic import BaseModel, Field, SecretStr, field_validator

from .hardware import BRIDGE, build_new_net
from .vmspec import POOL, DiskSpec

TEMPLATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,39}:vztmpl/[A-Za-z0-9][A-Za-z0-9._+\-]{0,150}\.tar\.(zst|gz|xz|bz2)$")
SSH_KEY = re.compile(r"^(ssh-(rsa|ed25519|dss)|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com) "
                     r"[A-Za-z0-9+/=]{20,} ?[^\r\n]{0,100}$")


class LxcNet(BaseModel):
    bridge: str
    tag: int | None = Field(default=None, ge=1, le=4094)
    firewall: bool = False
    ip: str | None = Field(default=None, max_length=64, description="dhcp, manual ou adresse CIDR")
    gateway: str | None = Field(default=None, max_length=64)

    @field_validator("bridge")
    @classmethod
    def _bridge(cls, v):
        if not BRIDGE.match(v):
            raise ValueError("Nom de bridge invalide")
        return v


class LxcCreate(BaseModel):
    hostname: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9\-.]{0,62}$")
    vmid: int | None = Field(default=None, ge=100, le=999999999)
    template: str = Field(description="Modèle déjà présent, ex. local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst")
    memory: int = Field(default=512, ge=16, le=4_194_304, description="Mo")
    swap: int = Field(default=512, ge=0, le=4_194_304, description="Mo")
    cores: int = Field(default=1, ge=1, le=512)
    disk: DiskSpec
    net: LxcNet | None = None
    password: SecretStr | None = Field(default=None, min_length=8, max_length=128, description="Mot de passe root (secret)")
    ssh_public_keys: str | None = Field(default=None, max_length=8192, description="Clés publiques, une par ligne")
    unprivileged: bool = True
    nesting: bool = False
    pool: str | None = None
    start: bool = False
    description: str = Field(default="", max_length=200)

    @field_validator("template")
    @classmethod
    def _template(cls, v):
        if not TEMPLATE.match(v):
            raise ValueError("Modèle invalide (attendu : stockage:vztmpl/nom.tar.zst)")
        return v

    @field_validator("pool")
    @classmethod
    def _pool(cls, v):
        if v is not None and not POOL.match(v):
            raise ValueError("Nom de pool invalide")
        return v

    @field_validator("ssh_public_keys")
    @classmethod
    def _keys(cls, v):
        if v is None or not v.strip():
            return None
        lines = [l.strip() for l in v.strip().splitlines() if l.strip()]
        if len(lines) > 8 or not all(SSH_KEY.match(l) for l in lines):
            raise ValueError("Clé SSH publique invalide (8 clés au plus, une par ligne : ssh-ed25519 AAAA… commentaire)")
        return "\n".join(lines)


def build_lxc_params(spec: LxcCreate, vmid: int) -> dict[str, str | int]:
    p: dict[str, str | int] = {
        "vmid": vmid, "ostemplate": spec.template, "hostname": spec.hostname, "memory": spec.memory, "swap": spec.swap,
        "cores": spec.cores, "rootfs": f"{spec.disk.storage}:{spec.disk.size_gb}", "unprivileged": 1 if spec.unprivileged else 0,
    }
    if spec.nesting:
        p["features"] = "nesting=1"
    if spec.net:
        n = spec.net
        p["net0"] = build_new_net(True, 0, bridge=n.bridge, tag=n.tag, firewall=n.firewall, ip=n.ip, gateway=n.gateway)
    if spec.password:
        p["password"] = spec.password.get_secret_value()
    if spec.ssh_public_keys:
        p["ssh-public-keys"] = spec.ssh_public_keys
    if spec.pool:
        p["pool"] = spec.pool
    if spec.start:
        p["start"] = 1
    if spec.description.strip():
        p["description"] = spec.description.strip()
    return p
