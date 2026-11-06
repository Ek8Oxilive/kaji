"""Construction sûre des paramètres de création d'une VM : tout est validé, rien n'est transmis tel quel."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .hardware import BRIDGE, ISO

STORAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,39}$")
POOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,39}$")
OSTYPES = ("l26", "l24", "win11", "win10", "win8", "win7", "w2k22", "w2k19", "w2k16", "other")


class DiskSpec(BaseModel):
    storage: str
    size_gb: int = Field(ge=1, le=65536)

    @field_validator("storage")
    @classmethod
    def _storage(cls, v):
        if not STORAGE.match(v):
            raise ValueError("Nom de stockage invalide")
        return v


class NetSpec(BaseModel):
    bridge: str
    model: Literal["virtio", "e1000", "e1000e", "rtl8139", "vmxnet3"] = "virtio"
    tag: int | None = Field(default=None, ge=1, le=4094)
    firewall: bool = False

    @field_validator("bridge")
    @classmethod
    def _bridge(cls, v):
        if not BRIDGE.match(v):
            raise ValueError("Nom de bridge invalide")
        return v


class VmCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9\-.]{0,62}$")
    vmid: int | None = Field(default=None, ge=100, le=999999999)
    memory: int = Field(default=2048, ge=16, le=4_194_304, description="Mo")
    cores: int = Field(default=2, ge=1, le=512)
    sockets: int = Field(default=1, ge=1, le=8)
    cpu: str = Field(default="x86-64-v2-AES", pattern=r"^[A-Za-z0-9_\-]{1,40}$")
    ostype: Literal[OSTYPES] = "l26"  # type: ignore[valid-type]
    disk: DiskSpec | None = None
    net: NetSpec | None = None
    iso: str | None = Field(default=None, description="ex. local:iso/debian.iso")
    pool: str | None = None
    agent: bool = False
    start: bool = False
    description: str = Field(default="", max_length=200)

    @field_validator("iso")
    @classmethod
    def _iso(cls, v):
        if v is not None and not ISO.match(v):
            raise ValueError("Volume ISO invalide (attendu : stockage:iso/nom.iso)")
        return v

    @field_validator("pool")
    @classmethod
    def _pool(cls, v):
        if v is not None and not POOL.match(v):
            raise ValueError("Nom de pool invalide")
        return v


def build_params(spec: VmCreate, vmid: int) -> dict[str, str | int]:
    """Paramètres Proxmox pour POST /nodes/{node}/qemu. Windows 11 impose UEFI, q35, disque EFI et TPM."""
    p: dict[str, str | int] = {
        "vmid": vmid, "name": spec.name, "memory": spec.memory, "cores": spec.cores, "sockets": spec.sockets,
        "cpu": spec.cpu, "ostype": spec.ostype, "scsihw": "virtio-scsi-single",
    }
    if spec.description.strip():
        p["description"] = spec.description.strip()
    if spec.pool:
        p["pool"] = spec.pool
    if spec.agent:
        p["agent"] = 1
    if spec.start:
        p["start"] = 1
    if spec.disk:
        p["scsi0"] = f"{spec.disk.storage}:{spec.disk.size_gb}"
    if spec.net:
        n = spec.net
        p["net0"] = f"{n.model},bridge={n.bridge}" + (f",tag={n.tag}" if n.tag else "") + (",firewall=1" if n.firewall else "")
    if spec.iso:
        p["ide2"] = f"{spec.iso},media=cdrom"
    boot = [d for d, on in (("scsi0", spec.disk), ("ide2", spec.iso)) if on]
    if spec.iso and spec.disk:
        boot = ["scsi0", "ide2"]
    if boot:
        p["boot"] = "order=" + ";".join(boot)
    if spec.ostype == "win11":
        if not spec.disk:
            raise ValueError("Windows 11 demande un disque (stockage du disque EFI et du TPM)")
        p.update({"bios": "ovmf", "machine": "q35",
                  "efidisk0": f"{spec.disk.storage}:1,efitype=4m,pre-enrolled-keys=1",
                  "tpmstate0": f"{spec.disk.storage}:1,version=v2.0"})
    return p
