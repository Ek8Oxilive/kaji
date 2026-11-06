"""Un `$` en fin de motif accepte aussi un saut de ligne final avec `re.match` (« abc\\n » passe).

Règle du dépôt : on valide avec `fullmatch`, jamais `match`/`search`. Ces tests couvrent
(1) chaque validateur de saisie, avec un `\\n` final, (2) le code source entier, pour
qu'un futur `.match(` (de n'importe quel agent) fasse échouer la CI.
"""
import ast
import pathlib

import pytest
from pydantic import ValidationError

from app import hardware
from app.lxcspec import LxcCreate, LxcNet
from app.routers import actions
from app.routers.clone import CloneBody
from app.routers.cloudinit import CloudInitUpdate, DriveAdd
from app.routers.connections import ConnectionCreate
from app.routers.disks import DiskAdd, Move
from app.routers.hardware import CdromEdit, ConfigUpdate, NetEdit
from app.routers.migrate import MigrateBody
from app.routers.nets import NetAdd
from app.vmspec import DiskSpec, NetSpec, VmCreate

NL = "\n"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabc commentaire"
TPL = "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
ISO = "local:iso/debian.iso"
LXC_DISK = {"storage": "local-lvm", "size_gb": 8}


def build(model, **fields):
    return lambda: model(**fields)


# (nom, constructeur valide, constructeur avec un « \n » final)
CASES = [
    ("vm.disk.storage", build(DiskSpec, storage="local-lvm", size_gb=8), build(DiskSpec, storage="local-lvm" + NL, size_gb=8)),
    ("vm.net.bridge", build(NetSpec, bridge="vmbr0"), build(NetSpec, bridge="vmbr0" + NL)),
    ("vm.name", build(VmCreate, name="web"), build(VmCreate, name="web" + NL)),
    ("vm.cpu", build(VmCreate, name="web", cpu="host"), build(VmCreate, name="web", cpu="host" + NL)),
    ("vm.iso", build(VmCreate, name="web", iso=ISO), build(VmCreate, name="web", iso=ISO + NL)),
    ("vm.pool", build(VmCreate, name="web", pool="bac"), build(VmCreate, name="web", pool="bac" + NL)),
    ("lxc.hostname", build(LxcCreate, hostname="ct", template=TPL, disk=LXC_DISK), build(LxcCreate, hostname="ct" + NL, template=TPL, disk=LXC_DISK)),
    ("lxc.template", build(LxcCreate, hostname="ct", template=TPL, disk=LXC_DISK), build(LxcCreate, hostname="ct", template=TPL + NL, disk=LXC_DISK)),
    ("lxc.pool", build(LxcCreate, hostname="ct", template=TPL, disk=LXC_DISK, pool="bac"), build(LxcCreate, hostname="ct", template=TPL, disk=LXC_DISK, pool="bac" + NL)),
    ("lxc.bridge", build(LxcNet, bridge="vmbr0"), build(LxcNet, bridge="vmbr0" + NL)),
    ("lxc.ssh_key", build(LxcCreate, hostname="ct", template=TPL, disk=LXC_DISK, ssh_public_keys=KEY),
     # la clé est découpée par lignes puis nettoyée : on vise donc le motif lui-même, voir test plus bas
     None),
    ("clone.name", build(CloneBody, name="copie"), build(CloneBody, name="copie" + NL)),
    ("clone.node", build(CloneBody, name="copie", target_node="pve2"), build(CloneBody, name="copie", target_node="pve2" + NL)),
    ("clone.storage", build(CloneBody, name="copie", storage="local-lvm"), build(CloneBody, name="copie", storage="local-lvm" + NL)),
    ("clone.pool", build(CloneBody, name="copie", pool="bac"), build(CloneBody, name="copie", pool="bac" + NL)),
    ("clone.snapshot", build(CloneBody, name="copie", snapshot="avant"), build(CloneBody, name="copie", snapshot="avant" + NL)),
    ("migrate.node", build(MigrateBody, target_node="pve2"), build(MigrateBody, target_node="pve2" + NL)),
    ("migrate.storage", build(MigrateBody, target_node="pve2", target_storage="local-lvm"), build(MigrateBody, target_node="pve2", target_storage="local-lvm" + NL)),
    ("conn.host", build(ConnectionCreate, name="n", host="10.0.0.1", user="kaji@pve", token_id="t", token_secret="x"), build(ConnectionCreate, name="n", host="10.0.0.1" + NL + "evil", user="kaji@pve", token_id="t", token_secret="x")),
    ("cloudinit.user", build(CloudInitUpdate, user="debian"), build(CloudInitUpdate, user="debian" + NL)),
    ("cloudinit.domain", build(CloudInitUpdate, searchdomain="lab.local"), build(CloudInitUpdate, searchdomain="lab.local" + NL)),
    ("cloudinit.drive", build(DriveAdd, storage="local-lvm"), build(DriveAdd, storage="local-lvm" + NL)),
    ("nets.bridge", build(NetAdd, bridge="vmbr0"), build(NetAdd, bridge="vmbr0" + NL)),
    ("hw.net.bridge", build(NetEdit, bridge="vmbr0"), build(NetEdit, bridge="vmbr0" + NL)),
    ("hw.cdrom.iso", build(CdromEdit, iso=ISO), build(CdromEdit, iso=ISO + NL)),
    ("hw.cpu", build(ConfigUpdate, cpu="host"), build(ConfigUpdate, cpu="host" + NL)),
    ("hw.boot", build(ConfigUpdate, boot=["scsi0"]), build(ConfigUpdate, boot=["scsi0" + NL])),
    ("disks.add.storage", build(DiskAdd, storage="local-lvm", size_gb=1), build(DiskAdd, storage="local-lvm" + NL, size_gb=1)),
    ("disks.move.storage", build(Move, storage="local-lvm"), build(Move, storage="local-lvm" + NL)),
]
CASES = [c for c in CASES if c[2] is not None]


@pytest.mark.parametrize("name,ok,bad", CASES, ids=[c[0] for c in CASES])
def test_saut_de_ligne_final_refuse(name, ok, bad):
    ok()  # la valeur propre reste acceptée (le test ne passe pas parce que tout est refusé)
    with pytest.raises(ValidationError):
        bad()


def test_hote_de_connexion_est_nettoye_pas_conserve_avec_saut_de_ligne():
    c = ConnectionCreate(name="n", host="10.0.0.1" + NL, user="kaji@pve", token_id="t", token_secret="x")
    assert c.host == "10.0.0.1"  # le validateur retire les blancs AVANT de contrôler ; aucun \n n'est transmis


def test_cle_ssh_motif_lui_meme():
    assert hardware.BRIDGE.fullmatch("vmbr0") and not hardware.BRIDGE.fullmatch("vmbr0" + NL)
    from app.lxcspec import SSH_KEY
    assert SSH_KEY.fullmatch(KEY) and not SSH_KEY.fullmatch(KEY + NL)


def test_cloudinit_ipconfig_et_cle_ssh():
    CloudInitUpdate(ipconfig={"ipconfig0": {"mode": "dhcp"}}, ssh_keys=KEY)
    with pytest.raises(ValidationError):
        CloudInitUpdate(ipconfig={"ipconfig0" + NL: {"mode": "dhcp"}})


@pytest.mark.parametrize("fn,good", [
    (hardware.check_mp_path, "/srv/data"),
])
def test_chemin_de_montage(fn, good):
    assert fn(good) == good
    with pytest.raises(ValueError):
        fn(good + NL)


def test_upid():
    ok = "UPID:pve:0000AAAA:0000BBBB:5F000000:qmstart:100:root@pam:"
    assert actions._check_upid(ok) == ok
    with pytest.raises(Exception):
        actions._check_upid(ok + NL)


@pytest.mark.parametrize("pat,good", [
    (hardware.DISK_KEY, "scsi0"), (hardware.NET_KEY, "net0"), (hardware.MP_KEY, "mp0"),
    (hardware.BOOT_KEY, "scsi0"), (hardware.UNUSED_KEY, "unused0"), (hardware.SIZE, "10G"),
    (hardware.ISO, ISO), (hardware.MP_PATH, "/srv"),
])
def test_motifs_du_materiel(pat, good):
    assert pat.fullmatch(good) and not pat.fullmatch(good + NL)


def test_aucun_match_ou_search_dans_le_code():
    """`re.match` / `.match(` / `.search(` : interdits dans backend/app (utiliser fullmatch)."""
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    fautes = []
    for f in sorted(root.rglob("*.py")):
        if f.name == "migrations.py" or "migrations" in f.parts:
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"match", "search"}:
                fautes.append(f"{f.relative_to(root.parent)}:{node.lineno} .{node.func.attr}(")
    assert not fautes, "Utiliser fullmatch (le $ final accepte un saut de ligne) :\n" + "\n".join(fautes)
