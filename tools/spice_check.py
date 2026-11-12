#!/usr/bin/env python3
"""Vérifie un fichier `.vv` de Kaji SANS virt-viewer : client SPICE minimal qui fait ce que virt-viewer fait au début d'une connexion (sans afficher d'écran).

Lit le fichier, se connecte au proxy du nœud (`CONNECT`), établit le TLS en vérifiant le certificat avec le `ca` du fichier et le `host-subject`,
envoie l'en-tête de lien SPICE (canal principal), authentifie avec le ticket (RSA-OAEP avec la clé publique du serveur) et lit le premier message
(`SPICE_MSG_MAIN_INIT`, type 103). N'affiche JAMAIS le ticket, l'hôte signé ni le certificat, et SUPPRIME le fichier `.vv` dès qu'il est lu.
Le ticket ne vaut que ~40 s : lancer le script tout de suite après avoir cliqué « SPICE (virt-viewer) » (voir `docs/api/console-spice.md`).
Constaté en réel : le proxy de Proxmox refuse `CONNECT … HTTP/1.0` sans `Host` (401 « invalid ticket ») et accepte `HTTP/1.1` avec `Host` : le script essaie les deux.
usage : python3 tools/spice_check.py fichier.vv        (dépend de `cryptography`, déjà dans le venv du backend)
"""
import os
import socket
import ssl
import struct
import sys
import time
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

path = sys.argv[1]
t0 = time.time()
steps: list[str] = []


def ok(msg):
    steps.append("OK   " + msg)
    print(steps[-1], flush=True)


def ko(msg):
    steps.append("ECHEC " + msg)
    print(steps[-1], flush=True)
    sys.exit(1)


age = time.time() - os.stat(path).st_mtime                      # âge du fichier à la lecture : le ticket ne vaut que ~40 s
try:
    raw = open(path, encoding="utf-8").read()
finally:
    try:
        os.remove(path)                                          # le ticket n'est plus nulle part sur le disque
    except FileNotFoundError:
        pass
ok(f"fichier .vv lu puis supprimé (écrit {age:.1f} s avant la lecture ; ticket valable ~40 s)")
cfg = {}
for line in raw.splitlines()[1:]:
    k, _, v = line.partition("=")
    cfg[k] = v
need = ("host", "tls-port", "password", "ca", "proxy", "host-subject")
if raw.splitlines()[0] != "[virt-viewer]" or any(k not in cfg for k in need):
    ko("fichier .vv incomplet")
ok(f"format .vv : {len(cfg)} clés, section [virt-viewer], port TLS {cfg['tls-port']}")

proxy = urlsplit(cfg["proxy"])
try:
    s = socket.create_connection((proxy.hostname, proxy.port or 3128), timeout=10)
except OSError as e:
    ko(f"connexion TCP au proxy {proxy.hostname}:{proxy.port} impossible ({type(e).__name__})")
ok(f"TCP vers le proxy {proxy.hostname}:{proxy.port}")

target = f"{cfg['host']}:{cfg['tls-port']}"
VARIANTS = [
    ("CONNECT host:tls-port, HTTP/1.0 (forme de virt-viewer)", f"CONNECT {target} HTTP/1.0\r\n\r\n"),
    ("CONNECT host:tls-port, HTTP/1.1 + Host", f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n"),
    ("CONNECT host:tls-port, HTTP/1.1 + Proxy-Connection", f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\nProxy-Connection: keep-alive\r\n\r\n"),
    ("CONNECT host seul (le port est déjà dans le ticket)", f"CONNECT {cfg['host']} HTTP/1.0\r\n\r\n"),
]
status = ""
for label, req in VARIANTS:
    s2 = socket.create_connection((proxy.hostname, proxy.port or 3128), timeout=10)
    s2.sendall(req.encode())
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 4096:
        chunk = s2.recv(1024)
        if not chunk:
            break
        head += chunk
    status = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
    print(f"  variante « {label} » -> {status[:50]}", flush=True)
    if " 200" in status:
        s = s2
        break
    s2.close()
ok(f"tunnel CONNECT accepté par le proxy ({status.strip()})")

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False                                       # SPICE vérifie le sujet du certificat (host-subject), pas le nom d'hôte
ctx.verify_mode = ssl.CERT_REQUIRED
ctx.load_verify_locations(cadata=cfg["ca"].replace("\\n", "\n"))
try:
    tls = ctx.wrap_socket(s, server_hostname=None)
except ssl.SSLError as e:
    ko(f"TLS : certificat refusé ({e.reason})")
cert = x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))
subject = {a.rfc4514_string() for a in cert.subject}
wanted = {p.strip() for p in cfg["host-subject"].split(",")}
if not wanted <= subject:
    ko("le sujet du certificat ne correspond pas à host-subject")
ok(f"TLS établi ({tls.version()}), certificat signé par l'autorité du fichier, sujet conforme à host-subject")


def recvn(n):
    buf = b""
    while len(buf) < n:
        c = tls.recv(n - len(buf))
        if not c:
            ko("connexion fermée par le serveur")
        buf += c
    return buf


# --- lien SPICE, canal principal (type 1), sans capacité optionnelle : authentification classique par ticket
mess = struct.pack("<IBBIII", 0, 1, 0, 0, 0, 18)                 # connection_id, type, id, nb caps communes, nb caps canal, offset
tls.settimeout(10)
tls.sendall(struct.pack("<4sIII", b"REDQ", 2, 2, len(mess)) + mess)
magic, major, minor, size = struct.unpack("<4sIII", recvn(16))
if magic != b"REDQ":
    ko("le serveur ne parle pas SPICE (pas de REDQ) : pas d'écran SPICE sur ce port ?")
reply = recvn(size)
err, = struct.unpack_from("<I", reply, 0)
if err != 0:
    ko(f"SPICE refuse le lien (code {err})")
ok(f"serveur SPICE a répondu (protocole {major}.{minor}, canal principal)")
pub = serialization.load_der_public_key(reply[4:4 + 162])
enc = pub.encrypt(cfg["password"].encode() + b"\0", padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
tls.sendall(enc)
result, = struct.unpack("<I", recvn(4))
if result != 0:
    ko(f"ticket refusé par SPICE (code {result})")
ok("ticket accepté par le serveur SPICE : session authentifiée")
try:
    serial, mtype, msize, nsub = struct.unpack("<QHII", recvn(18))
    ok(f"premier message du canal principal reçu (type {mtype}, {msize} octets) : la session est ouverte")
except Exception:
    ok("authentifié (le premier message n'a pas été lu à temps)")
tls.close()
print(f"TERMINÉ en {time.time() - t0:.1f} s")
