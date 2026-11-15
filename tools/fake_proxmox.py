#!/usr/bin/env python3
"""Faux Proxmox HTTPS pour MESURER Kaji (jalon J3, ticket #457) : latence et pannes réglables en cours de route. N'est PAS un Proxmox : il répond juste assez pour le tableau de bord.

    python tools/fake_proxmox.py --port 8643 [--guests 17]
    curl -sk -X POST 'https://127.0.0.1:8643/__control?mode=ok&latency=0.5'          # mode : ok | 500 | html | hang ; latency en secondes

Certificat auto-signé généré au démarrage (module `cryptography`, déjà une dépendance de Kaji) ; n'importe quel jeton est accepté (les en-têtes ne sont pas vérifiés). Local uniquement (127.0.0.1).
"""
import argparse
import datetime
import json
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATE = {"mode": "ok", "latency": 0.0, "hits": 0, "guests": 17}
LOCK = threading.Lock()


def make_cert(directory: Path) -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2)).sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def payload(path: str) -> object:
    n = STATE["guests"]
    if path.endswith("/cluster/status"):
        return [{"type": "cluster", "name": "faux", "quorate": 1, "nodes": 2}, {"type": "node", "name": "n1", "online": 1, "ip": "10.0.0.1"}, {"type": "node", "name": "n2", "online": 1, "ip": "10.0.0.2"}]
    if path.endswith("/cluster/resources"):
        return [{"type": "qemu", "vmid": 100 + i, "name": f"vm{i}", "node": "n1" if i % 2 else "n2", "status": "running", "cpu": 0.01, "maxcpu": 2, "mem": 1 << 29, "maxmem": 1 << 30,
                 "disk": 0, "maxdisk": 1 << 33, "uptime": 1000} for i in range(n)]
    if path.endswith("/nodes"):
        return [{"node": "n1", "status": "online", "cpu": 0.05, "maxcpu": 4, "mem": 1 << 30, "maxmem": 1 << 33, "disk": 1 << 30, "maxdisk": 1 << 36, "uptime": 99999},
                {"node": "n2", "status": "online", "cpu": 0.02, "maxcpu": 4, "mem": 1 << 29, "maxmem": 1 << 33, "disk": 1 << 30, "maxdisk": 1 << 36, "uptime": 88888}]
    if path.endswith("/storage"):
        return [{"storage": "local", "type": "dir", "content": "iso,backup", "active": 1, "total": 1 << 36, "used": 1 << 30, "avail": 1 << 35, "shared": 0, "enabled": 1}]
    if path.endswith("/version"):
        return {"version": "9.1", "release": "9.1", "repoid": "faux"}
    return []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    wbufsize = 65536                       # en-têtes ET corps partent ensemble : sinon l'algorithme de Nagle + l'ACK retardé ajoutent ~40 ms à CHAQUE réponse (constaté : fausse les mesures)
    disable_nagle_algorithm = True

    def log_message(self, *args):          # silence
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/__control":
            q = parse_qs(url.query)
            with LOCK:
                if "mode" in q:
                    STATE["mode"] = q["mode"][0]
                if "latency" in q:
                    STATE["latency"] = float(q["latency"][0])
                if "guests" in q:
                    STATE["guests"] = int(q["guests"][0])
            return self._send(200, json.dumps({k: STATE[k] for k in ("mode", "latency", "guests", "hits")}).encode())
        self._send(404, b"{}")

    def do_GET(self):
        with LOCK:
            STATE["hits"] += 1
            mode, latency = STATE["mode"], STATE["latency"]
        if mode == "hang":
            time.sleep(60)
        if latency:
            time.sleep(latency)
        if mode == "500":
            return self._send(500, b'{"data":null}')
        if mode == "html":
            return self._send(200, b"<html>portail captif</html>", "text/html")
        self._send(200, json.dumps({"data": payload(urlparse(self.path).path)}).encode())


class Server(ThreadingHTTPServer):
    request_queue_size = 1024              # 5 par défaut : au-delà, les nouvelles connexions sont retardées de plusieurs secondes (fausserait les mesures de Kaji)
    daemon_threads = True


def serve(port: int, directory: Path | None = None) -> ThreadingHTTPServer:
    directory = directory or Path(tempfile.mkdtemp(prefix="fake-proxmox-"))
    cert, key = make_cert(directory)
    server = Server(("127.0.0.1", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    return server


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8643)
    ap.add_argument("--guests", type=int, default=17)
    args = ap.parse_args()
    STATE["guests"] = args.guests
    srv = serve(args.port)
    print(f"faux Proxmox sur https://127.0.0.1:{args.port} (mode ok, latence 0)", flush=True)
    srv.serve_forever()
