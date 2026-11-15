#!/usr/bin/env python3
"""Mesure Kaji sous charge et pannes de Proxmox (jalon J3, ticket #457) : ordre de grandeur MESURÉ, pas une promesse (docs/robustesse.md).

    backend/.venv/bin/python tools/load_test.py [--duration 6] [--users 1,10,25,50,100] [--json sortie.json]

Démarre le VRAI backend (un seul worker uvicorn, base SQLite fichier jetable) et un faux Proxmox local (`tools/fake_proxmox.py`), crée un compte et une connexion, puis joue des scénarios avec N
utilisateurs simulés qui rechargent sans pause les routes du tableau de bord : sain, Proxmox lent, très lent, bloqué, en panne (connexion refusée), qui répond 500 ou une page HTML ; et le flux temps réel
(SSE) partagé. Pendant la panne « bloqué », deux pages qui n'ont PAS besoin de Proxmox sont sondées. Tout tourne sur CETTE machine : les chiffres valent pour elle, pas pour votre cluster.
"""
import argparse
import asyncio
import json
import os
import platform
import secrets
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROUTES = ["/api/connections/1/nodes", "/api/connections/1/guests", "/api/connections/1/cluster/status", "/api/connections/1/storages"]
PWD = "mot-de-passe-de-charge-12"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


def summarize(samples: list[tuple[str, int, float]], seconds: float) -> dict:
    lat = [s[2] for s in samples]
    ms = lambda v: 0 if v != v else round(v * 1000)                     # noqa: E731  (NaN = aucun échantillon : 0, pas une exception)
    codes: dict[str, int] = {}
    for _, code, _ in samples:
        codes[str(code)] = codes.get(str(code), 0) + 1
    ok = codes.get("200", 0)
    return {"requests": len(samples), "rps": round(len(samples) / seconds, 1) if seconds else 0, "ok_pct": round(100 * ok / len(samples), 1) if samples else 0.0, "codes": codes,
            "p50_ms": ms(percentile(lat, 50)), "p95_ms": ms(percentile(lat, 95)), "p99_ms": ms(percentile(lat, 99)), "max_ms": ms(max(lat)) if lat else 0}


class Rig:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="kaji-load-")
        self.fake_port, self.kaji_port = free_port(), free_port()
        self.fake: subprocess.Popen | None = None
        self.kaji: subprocess.Popen | None = None
        self.cookies: httpx.Cookies | None = None

    def start_fake(self):
        self.fake = subprocess.Popen([sys.executable, str(ROOT / "tools" / "fake_proxmox.py"), "--port", str(self.fake_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                httpx.post(f"https://127.0.0.1:{self.fake_port}/__control", verify=False, timeout=1)
                return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("le faux Proxmox ne démarre pas")

    def stop_fake(self):
        if self.fake:
            self.fake.terminate()
            self.fake.wait(5)
            self.fake = None

    def start_kaji(self):
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{self.tmp}/kaji.db", "KAJI_SECRET_KEY": secrets.token_urlsafe(48), "KAJI_COOKIE_SECURE": "false", "KAJI_SCHEDULER": "false"}
        self.kaji = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.kaji_port), "--workers", "1", "--log-level", "warning"],
                                     cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(150):
            try:
                if httpx.get(self.base + "/api/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("Kaji ne démarre pas")

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.kaji_port}"

    def setup(self):
        with httpx.Client(base_url=self.base, timeout=10) as c:
            assert c.post("/api/auth/setup", json={"username": "charge", "password": PWD}).status_code == 201
            r = c.post("/api/connections", json={"name": "faux", "host": "127.0.0.1", "port": self.fake_port, "user": "kaji@pve", "token_id": "kaji", "token_secret": "secret-de-charge",
                                                 "verify_ssl": False})
            assert r.status_code == 201, r.text
            self.cookies = c.cookies

    def control(self, **params) -> dict:
        return httpx.post(f"https://127.0.0.1:{self.fake_port}/__control", params=params, verify=False, timeout=5).json()

    def stop(self):
        for p in (self.kaji, self.fake):
            if p:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()


async def hammer(rig: Rig, users: int, seconds: float, routes=DASHBOARD_ROUTES) -> tuple[list, float]:
    samples: list[tuple[str, int, float]] = []
    stop = time.perf_counter() + seconds
    limits = httpx.Limits(max_connections=users + 20, max_keepalive_connections=users + 20)
    async with httpx.AsyncClient(base_url=rig.base, cookies=rig.cookies, timeout=60, limits=limits) as c:
        async def user(i: int):
            n = i
            while time.perf_counter() < stop:
                path = routes[n % len(routes)]
                n += 1
                t0 = time.perf_counter()
                try:
                    code = (await c.get(path)).status_code
                except httpx.HTTPError as e:
                    code = 0 if not isinstance(e, httpx.TimeoutException) else -1
                samples.append((path, code, time.perf_counter() - t0))
        t0 = time.perf_counter()
        await asyncio.gather(*[user(i) for i in range(users)])
        return samples, time.perf_counter() - t0


async def probe_independent(rig: Rig, seconds: float) -> dict:
    """Sonde deux pages qui n'ont pas besoin de Proxmox pendant qu'il est bloqué."""
    out: dict[str, list] = {"/api/health": [], "/api/auth/me": []}
    stop = time.perf_counter() + seconds
    async with httpx.AsyncClient(base_url=rig.base, cookies=rig.cookies, timeout=60) as c:
        while time.perf_counter() < stop:
            for path in out:
                t0 = time.perf_counter()
                try:
                    code = (await c.get(path)).status_code
                except httpx.HTTPError:
                    code = 0
                out[path].append((path, code, time.perf_counter() - t0))
            await asyncio.sleep(0.5)
    return {path: summarize(s, seconds) for path, s in out.items()}


async def sse_scenario(rig: Rig, clients: int, seconds: float) -> dict:
    before = rig.control()["hits"]
    events = [0] * clients
    stop = time.perf_counter() + seconds

    async def one(i: int):
        async with httpx.AsyncClient(base_url=rig.base, cookies=rig.cookies, timeout=None) as c:
            try:
                async with c.stream("GET", "/api/connections/1/events") as r:
                    async for line in r.aiter_lines():
                        if line.startswith("event: "):
                            events[i] += 1
                        if time.perf_counter() > stop:
                            return
            except httpx.HTTPError:
                return
    await asyncio.gather(*[one(i) for i in range(clients)])
    after = rig.control()["hits"]
    return {"clients": clients, "seconds": seconds, "events_total": sum(events), "events_min": min(events), "proxmox_hits": after - before, "hits_per_client": round((after - before) / clients, 2)}


def scenarios(rig: Rig, duration: float, user_counts: list[int], healthy_only: bool = False) -> dict:
    result: dict = {}
    rig.control(mode="ok", latency=0, guests=17)
    for n in user_counts:
        samples, took = asyncio.run(hammer(rig, n, duration))
        result[f"sain, {n} utilisateur(s)"] = summarize(samples, took)
    if healthy_only:
        return result
    for label, latency, users in (("Proxmox lent (0,5 s), 50 utilisateurs", 0.5, 50), ("Proxmox très lent (3 s), 50 utilisateurs", 3.0, 50)):
        rig.control(mode="ok", latency=latency)
        samples, took = asyncio.run(hammer(rig, users, max(duration, latency * 4)))
        result[label] = summarize(samples, took)
    rig.control(mode="ok", latency=0)
    for mode, label in (("500", "Proxmox répond 500, 25 utilisateurs"), ("html", "Proxmox répond une page HTML, 25 utilisateurs")):
        rig.control(mode=mode)
        samples, took = asyncio.run(hammer(rig, 25, duration))
        result[label] = summarize(samples, took)
    rig.control(mode="ok")
    rig.control(mode="hang")                                                                           # bloqué : ne répond jamais (le client de Kaji coupe à 15 s)

    async def hang():
        return await asyncio.gather(hammer(rig, 30, 20), probe_independent(rig, 20))
    (samples, took), probes = asyncio.run(hang())
    result["Proxmox bloqué (30 utilisateurs, 20 s)"] = summarize(samples, took)
    result["  pendant ce blocage : pages sans Proxmox"] = probes
    rig.control(mode="ok")
    rig.stop_fake()                                                                                    # panne franche : connexion refusée
    samples, took = asyncio.run(hammer(rig, 25, duration))
    result["Proxmox en panne (connexion refusée), 25 utilisateurs"] = summarize(samples, took)
    rig.start_fake()
    rig.control(mode="ok", latency=0, guests=17)
    time.sleep(8)                                                                                     # laisser le temps aux connexions bloquées de se libérer
    samples, took = asyncio.run(hammer(rig, 10, duration))
    result["après la panne, 10 utilisateurs (reprise)"] = summarize(samples, took)
    result["flux temps réel (SSE)"] = asyncio.run(sse_scenario(rig, 50, 10))
    return result


def markdown(result: dict) -> str:
    rows = ["| Scénario | requêtes | req/s | 200 | p50 | p95 | p99 | max | codes |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for name, r in result.items():
        if "clients" in r:
            continue
        if "p50_ms" in r:
            rows.append(f"| {name} | {r['requests']} | {r['rps']} | {r['ok_pct']} % | {r['p50_ms']} ms | {r['p95_ms']} ms | {r['p99_ms']} ms | {r['max_ms']} ms | {r['codes']} |")
        else:
            for path, s in r.items():
                rows.append(f"| {name} `{path}` | {s['requests']} | {s['rps']} | {s['ok_pct']} % | {s['p50_ms']} ms | {s['p95_ms']} ms | {s['p99_ms']} ms | {s['max_ms']} ms | {s['codes']} |")
    sse = result.get("flux temps réel (SSE)")
    if sse:
        rows.append("")
        rows.append(f"Flux temps réel : {sse['clients']} clients pendant {sse['seconds']} s → {sse['events_total']} événements reçus (au moins {sse['events_min']} par client), "
                    f"**{sse['proxmox_hits']} appels à Proxmox au total** ({sse['hits_per_client']} par client : un seul interrogateur est partagé).")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--users", default="1,10,25,50,100")
    ap.add_argument("--json")
    ap.add_argument("--healthy-only", action="store_true", help="seulement les scénarios sains (plus court)")
    args = ap.parse_args()
    rig = Rig()
    try:
        rig.start_fake()
        rig.start_kaji()
        rig.setup()
        result = scenarios(rig, args.duration, [int(x) for x in args.users.split(",")], args.healthy_only)
    finally:
        rig.stop()
    meta = {"machine": platform.platform(), "cpus": os.cpu_count(), "python": platform.python_version(), "workers": 1, "duration_s": args.duration}
    print(json.dumps(meta, ensure_ascii=False))
    print(markdown(result))
    if args.json:
        Path(args.json).write_text(json.dumps({"meta": meta, "results": result}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
