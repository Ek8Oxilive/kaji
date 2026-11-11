"""Moniteur QEMU d'une VM (`qm monitor`), EN LECTURE SEULE : liste blanche de commandes « info … » et nettoyage de la sortie (lot #273).

Jamais une commande libre : seules les commandes ci-dessous sont acceptées, exactement (aucun argument). Les commandes qui agissent sur la VM
(`quit`, `stop`, `cont`, `system_*`, `drive_*`, `device_*`, `migrate`, `savevm`, `loadvm`, `human-monitor-command`, `object_add`…) n'y figurent pas.
Aucun réseau ici.
"""
import re

# commande -> libellé affiché (français). Chaque entrée est une commande `info` de QEMU sans argument et sans effet de bord.
COMMANDS: dict[str, str] = {
    "info status": "État d'exécution",
    "info version": "Version de QEMU",
    "info name": "Nom de la machine",
    "info uuid": "UUID",
    "info kvm": "Accélération KVM",
    "info cpus": "Processeurs virtuels",
    "info hotpluggable-cpus": "Processeurs ajoutables à chaud",
    "info numa": "Topologie NUMA",
    "info memory-devices": "Modules mémoire",
    "info balloon": "Ballon mémoire",
    "info block": "Disques et lecteurs",
    "info blockstats": "Statistiques des disques",
    "info network": "Réseau",
    "info pci": "Bus PCI",
    "info usb": "Périphériques USB",
    "info chardev": "Périphériques caractères (série…)",
    "info vnc": "Serveur VNC",
    "info iothreads": "Threads d'entrées-sorties",
    "info migrate": "État de la migration",
    "info snapshots": "Instantanés",
    "info roms": "ROM",
}
SAFE_COMMAND = re.compile(r"^info [a-z][a-z-]{0,30}$")                # forme attendue, vérifiée AVANT la liste blanche
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")             # tout sauf \t \n \r
MAX_OUTPUT = 65536


def check_command(command: str) -> str | None:
    """Renvoie la commande normalisée si elle est autorisée, sinon None."""
    cmd = " ".join(command.split()) if isinstance(command, str) else ""
    return cmd if SAFE_COMMAND.fullmatch(cmd) and cmd in COMMANDS else None


def clean_output(value) -> tuple[str, bool]:
    """Sortie de Proxmox -> texte sûr (sans caractère de contrôle, `\\r\\n` normalisé), tronquée à `MAX_OUTPUT` ; renvoie `(texte, tronqué)`."""
    text = value if isinstance(value, str) else ""
    text = CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    return (text[:MAX_OUTPUT], True) if len(text) > MAX_OUTPUT else (text, False)
