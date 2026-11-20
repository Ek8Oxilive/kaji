"""`tools/proxmox-create-ct.sh` (installation express, ticket #542), essayé avec de FAUX `pct`, `pvesh`, `pveam`, `pvesm`, `qm` qui journalisent chaque appel.

Vérifié : l'ordre des commandes, les options du conteneur (non privilégié, nesting + keyctl), le refus d'un identifiant déjà pris, la destruction du SEUL conteneur créé
quand la création échoue, la conservation du conteneur quand c'est l'installation de Kaji qui échoue, les validations avant toute commande. **Pas vérifié** : un vrai nœud
(essai réel : voir `docs/REPRISE.md`).
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

FAKES = {
"pct": r"""#!/bin/sh
echo "pct $*" >> "$SHIM_LOG"
case "$1" in
  status) [ "$2" = "${SHIM_TAKEN_CT:-none}" ] && exit 0 || exit 2 ;;
  create) [ -z "${SHIM_FAIL_CREATE:-}" ] || exit 1 ;;
  start) [ -z "${SHIM_FAIL_START:-}" ] || exit 1 ;;
  exec)
    shift 2; shift   # id puis --
    case "$*" in
      *getent*) [ -z "${SHIM_NO_NET:-}" ] || exit 1 ;;
      *"hostname -I"*) echo 192.168.1.77 ;;
      *"sh /root/install.sh"*) [ -z "${SHIM_FAIL_INSTALL:-}" ] || exit 1 ; echo "Kaji est installé (faux)" ;;
    esac ;;
esac
exit 0
""",
"pvesh": "#!/bin/sh\necho \"pvesh $*\" >> \"$SHIM_LOG\"\necho \"\\\"${SHIM_NEXTID:-200}\\\"\"\n",
"pveam": r"""#!/bin/sh
echo "pveam $*" >> "$SHIM_LOG"
case "$1" in
  list) echo "Name Size"; [ -z "${SHIM_HAVE_TEMPLATE:-}" ] || echo "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst 120MB" ;;
  available) echo "system  debian-11-standard_11.7-1_amd64.tar.zst"; echo "system  debian-12-standard_12.2-1_amd64.tar.zst"; echo "system  debian-12-standard_12.7-1_amd64.tar.zst" ;;
esac
exit 0
""",
"pvesm": "#!/bin/sh\necho \"pvesm $*\" >> \"$SHIM_LOG\"\necho 'Name Type Status Total Used Available %'\necho 'frozen dir inactive 1 1 1 1%'\necho 'local-lvm lvmthin active 100 1 99 1%'\necho 'zfs zfspool active 100 1 99 1%'\n",
"qm": "#!/bin/sh\necho \"qm $*\" >> \"$SHIM_LOG\"\n[ \"$1\" = status ] && [ \"$2\" = \"${SHIM_TAKEN_VM:-none}\" ] && exit 0\nexit 2\n",
"id": "#!/bin/sh\n[ \"$1\" = -u ] && echo ${SHIM_UID:-0} || /usr/bin/id \"$@\"\n",
"sleep": "#!/bin/sh\nexit 0\n",
}


@pytest.fixture
def px(tmp_path):
    b = tmp_path / "bin"; b.mkdir()
    for n, body in FAKES.items():
        (b / n).write_text(body); (b / n).chmod(0o755)
    log = tmp_path / "log"
    env = {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "SHIM_LOG": str(log), "KAJI_CT_TRIES": "2", "KAJI_CT_PAUSE": "0"}

    def run(*args, stdin="", **extra):
        return subprocess.run(["sh", str(ROOT / "tools" / "proxmox-create-ct.sh"), *args], input=stdin, capture_output=True, text=True, env={**env, **extra}, timeout=30)

    def calls():
        return log.read_text().splitlines() if log.exists() else []

    return type("PX", (), {"run": staticmethod(run), "calls": staticmethod(calls)})


def find(calls, start):
    return [c for c in calls if c.startswith(start)]


def test_full_run_creates_a_nesting_unprivileged_container_starts_it_and_runs_install(px):
    r = px.run("--yes")
    assert r.returncode == 0, r.stderr + r.stdout
    c = px.calls()
    create = find(c, "pct create")[0]
    assert create.startswith("pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst")        # id libre de Proxmox, modèle le plus récent
    for opt in ("--unprivileged 1", "--features nesting=1,keyctl=1", "--onboot 1", "--rootfs local-lvm:16", "--net0 name=eth0,bridge=vmbr0,ip=dhcp", "--memory 2048", "--cores 2"):
        assert opt in create, opt
    assert c.index("pveam download local debian-12-standard_12.7-1_amd64.tar.zst") < c.index(create) < c.index("pct start 200")
    assert any("install.sh" in x and "--yes --address 192.168.1.77" in x for x in find(c, "pct exec 200"))
    assert "Conteneur Kaji prêt" in r.stdout and "pct enter 200" in r.stdout
    assert "pct pull 200 /root/kaji/caddy-root.crt caddy-root.crt" in r.stdout                  # le conteneur n'a pas de mot de passe : pas de scp direct


def test_rootfs_storage_skips_inactive_ones_and_template_is_not_downloaded_twice(px):
    r = px.run("--yes", SHIM_HAVE_TEMPLATE="1")
    assert r.returncode == 0
    assert "--rootfs local-lvm:16" in find(px.calls(), "pct create")[0]
    assert find(px.calls(), "pveam download") == []


def test_an_existing_ct_or_vm_id_is_refused_and_nothing_is_touched(px):
    for env in ({"SHIM_TAKEN_CT": "150"}, {"SHIM_TAKEN_VM": "150"}):
        r = px.run("--yes", "--vmid", "150", **env)
        assert r.returncode != 0 and "déjà utilisé" in r.stderr
        c = px.calls()
        assert find(c, "pct create") == [] and find(c, "pct destroy") == [] and find(c, "pct stop") == []


def test_dry_run_prints_the_commands_and_runs_no_write(px):
    r = px.run("--dry-run")
    assert r.returncode == 0 and "pct create 200" in r.stdout and "--features nesting=1,keyctl=1" in r.stdout
    c = px.calls()
    assert not any(x.startswith(("pct create", "pct start", "pct exec", "pct destroy", "pveam download")) for x in c)


def test_without_confirmation_nothing_is_created(px):
    r = px.run(stdin="n\n")
    assert r.returncode != 0 and "annulé" in r.stderr and find(px.calls(), "pct create") == []


def test_network_failure_destroys_only_the_container_it_just_created(px):
    r = px.run("--yes", "--vmid", "321", SHIM_NO_NET="1")
    assert r.returncode != 0 and "supprimé" in r.stderr
    c = px.calls()
    assert find(c, "pct destroy") == ["pct destroy 321 --purge"] and "pct stop 321" in c
    assert not any(x.startswith("pct destroy") and "321" not in x for x in c)


def test_start_failure_also_cleans_up_what_it_created(px):
    r = px.run("--yes", SHIM_FAIL_START="1")
    assert r.returncode != 0 and find(px.calls(), "pct destroy") == ["pct destroy 200 --purge"]


def test_creation_failure_destroys_nothing_because_nothing_was_created(px):
    r = px.run("--yes", SHIM_FAIL_CREATE="1")
    assert r.returncode != 0 and find(px.calls(), "pct destroy") == []


def test_kaji_install_failure_keeps_the_container_and_says_how_to_remove_it(px):
    r = px.run("--yes", SHIM_FAIL_INSTALL="1")
    assert r.returncode != 0 and "CONSERVÉ" in r.stderr and "pct enter 200" in r.stderr and "pct destroy 200 --purge" in r.stderr
    assert find(px.calls(), "pct destroy") == []                                                      # jamais de destruction automatique après l'installation


def test_options_are_forwarded_to_the_install_script(px):
    r = px.run("--yes", "--local", "--ref", "v1.0.0-rc1", "--image")
    assert r.returncode == 0
    ex = [x for x in find(px.calls(), "pct exec 200") if "install.sh --yes" in x][0]
    assert "--local" in ex and "--ref v1.0.0-rc1" in ex and "--image" in ex and "--address" not in ex
    r = px.run("--yes", "--address", "kaji.home")
    assert "--address kaji.home" in [x for x in find(px.calls(), "pct exec 200") if "install.sh --yes" in x][-1]


def test_static_address_goes_into_net0_with_its_gateway_and_pool_is_forwarded(px):
    px.run("--yes", "--ip", "192.168.1.50/24", "--gw", "192.168.1.1", "--pool", "kaji-test", "--bridge", "vmbr1", "--memory", "4096", "--disk", "32")
    create = find(px.calls(), "pct create")[0]
    assert "--net0 name=eth0,bridge=vmbr1,ip=192.168.1.50/24,gw=192.168.1.1" in create and "--pool kaji-test" in create
    assert "--memory 4096" in create and "--rootfs local-lvm:32" in create


@pytest.mark.parametrize("args", [("--ip", "192.168.1.50/24"), ("--ip", "300.1.1.1/24", "--gw", "1.1.1.1"), ("--ip", "1.2.3.4/99", "--gw", "1.1.1.1"), ("--gw", "1.1.1.1"),
                                  ("--ip", "dhcp;id"), ("--vmid", "50"), ("--vmid", "abc"), ("--name", "-x"), ("--name", "a b"), ("--name", "x;id"), ("--memory", "256"),
                                  ("--cores", "0"), ("--disk", "4"), ("--storage", "a;b"), ("--pool", "$(id)"), ("--bridge", "vm br"), ("--address", "a;b"),
                                  ("--address", "1.2.3.4", "--local"), ("--ref", "x;id")])
def test_invalid_values_are_refused_before_any_command(px, args):
    r = px.run("--yes", *args)
    assert r.returncode != 0 and px.calls() == [], r.stderr


def test_must_be_root_and_needs_proxmox_tools(px, tmp_path):
    r = px.run("--yes", SHIM_UID="1000")
    assert r.returncode != 0 and "root" in r.stderr and find(px.calls(), "pct create") == []
    vide = tmp_path / "vide"; vide.mkdir()
    r = subprocess.run(["/bin/sh", str(ROOT / "tools" / "proxmox-create-ct.sh"), "--yes"], capture_output=True, text=True, env={"PATH": f"{vide}:/usr/bin:/bin"}, timeout=30)
    assert r.returncode != 0


def test_the_script_never_pipes_the_network_into_a_shell_and_never_sets_a_password():
    t = (ROOT / "tools" / "proxmox-create-ct.sh").read_text(encoding="utf-8")
    assert "| sh" not in t and "| bash" not in t and "eval " not in t
    assert "--password" not in t and "--ssh-public-keys" not in t


def test_local_mode_does_not_mention_the_https_certificate(px):
    r = px.run("--yes", "--local")
    assert r.returncode == 0 and "pct pull" not in r.stdout
