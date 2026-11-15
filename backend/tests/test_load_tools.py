"""Outils de mesure (jalon J3, ticket #457) : faux Proxmox et outil de charge. Ce que mesure `tools/load_test.py` ne vaut que si ces outils sont corrects : un faux serveur lent ou faux fausserait tout."""
import importlib.util
import json
import re
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fake = load("fake_proxmox")
lt = load("load_test")


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = fake.serve(port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"https://127.0.0.1:{port}"
    yield base
    srv.shutdown()


@pytest.fixture(autouse=True)
def reset_state(server):
    httpx.post(f"{server}/__control", params={"mode": "ok", "latency": 0, "guests": 17}, verify=False)


def get(server, path, **kw):
    return httpx.get(f"{server}/api2/json{path}", verify=False, timeout=kw.pop("timeout", 5), **kw)


def test_the_fake_serves_what_the_dashboard_reads_in_proxmox_shape(server):
    assert get(server, "/version").json()["data"]["version"]
    nodes = get(server, "/nodes").json()["data"]
    assert [n["node"] for n in nodes] == ["n1", "n2"] and all(n["status"] == "online" for n in nodes)
    assert get(server, "/cluster/status").json()["data"][0]["type"] == "cluster"
    assert len(get(server, "/cluster/resources", params={"type": "vm"}).json()["data"]) == 17
    assert get(server, "/nodes/n1/storage").json()["data"][0]["storage"] == "local"


def test_the_guest_count_and_the_modes_are_settable_at_runtime(server):
    httpx.post(f"{server}/__control", params={"guests": 3}, verify=False)
    assert len(get(server, "/cluster/resources").json()["data"]) == 3
    httpx.post(f"{server}/__control", params={"mode": "500"}, verify=False)
    assert get(server, "/nodes").status_code == 500
    httpx.post(f"{server}/__control", params={"mode": "html"}, verify=False)
    r = get(server, "/nodes")
    assert r.status_code == 200 and "html" in r.headers["content-type"] and "portail" in r.text
    r = httpx.post(f"{server}/__control", params={"mode": "ok"}, verify=False)
    assert r.json()["mode"] == "ok" and get(server, "/nodes").status_code == 200


def test_latency_is_applied_and_a_fast_answer_does_not_pay_the_nagle_delay(server):
    httpx.post(f"{server}/__control", params={"latency": 0.3}, verify=False)
    t0 = time.perf_counter(); get(server, "/nodes"); slow = time.perf_counter() - t0
    assert 0.3 <= slow < 0.6
    httpx.post(f"{server}/__control", params={"latency": 0}, verify=False)
    with httpx.Client(verify=False, base_url=f"{server}/api2/json") as c:
        c.get("/nodes")
        t0 = time.perf_counter()
        for _ in range(20):
            c.get("/nodes")
        per_request = (time.perf_counter() - t0) / 20
    assert per_request < 0.025, f"{per_request * 1000:.0f} ms par requête : l'algorithme de Nagle fausserait toutes les mesures (≈ 40 ms constatés avant correction)"


def test_the_connection_queue_is_large_enough_for_many_simultaneous_clients(server):
    assert fake.Server.request_queue_size >= 512 and fake.Server.daemon_threads
    results = []

    def one():
        try:
            results.append(get(server, "/nodes", timeout=10).status_code)
        except httpx.HTTPError as e:
            results.append(type(e).__name__)
    threads = [threading.Thread(target=one) for _ in range(120)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert results.count(200) == 120, results


def test_percentiles_and_summaries_are_computed_correctly():
    values = list(range(1, 101))
    assert lt.percentile(values, 50) in (50, 51) and lt.percentile(values, 95) in (95, 96) and lt.percentile(values, 100) == 100 and lt.percentile([7], 99) == 7
    assert lt.percentile([], 50) != lt.percentile([], 50)                                   # NaN : pas d'échantillon, pas de faux chiffre
    samples = [("/a", 200, 0.010)] * 8 + [("/a", 502, 0.2), ("/a", 503, 0.4)]
    s = lt.summarize(samples, 2.0)
    assert s["requests"] == 10 and s["rps"] == 5.0 and s["ok_pct"] == 80.0 and s["codes"] == {"200": 8, "502": 1, "503": 1}
    assert s["p50_ms"] == 10 and s["max_ms"] == 400
    empty = lt.summarize([], 1.0)
    assert empty["requests"] == 0 and empty["ok_pct"] == 0.0 and empty["max_ms"] == 0


def test_the_markdown_table_has_one_row_per_scenario_and_the_shared_poller_sentence():
    result = {"sain, 1 utilisateur(s)": lt.summarize([("/a", 200, 0.01)], 1.0),
              "  pendant ce blocage : pages sans Proxmox": {"/api/health": lt.summarize([("/api/health", 200, 0.01)], 1.0)},
              "flux temps réel (SSE)": {"clients": 50, "seconds": 10, "events_total": 50, "events_min": 1, "proxmox_hits": 9, "hits_per_client": 0.18}}
    md = lt.markdown(result)
    assert md.count("\n| ") >= 2 and "| sain, 1 utilisateur(s) |" in md and "`/api/health`" in md
    assert "9 appels à Proxmox au total" in md and "un seul interrogateur est partagé" in md


def test_the_load_tool_drives_the_real_dashboard_routes_and_the_real_backend():
    src = (ROOT / "tools" / "load_test.py").read_text(encoding="utf-8")
    assert '"app.main:app"' in src and '"--workers", "1"' in src                               # le VRAI backend, un seul worker
    for route in ("/nodes", "/guests", "/cluster/status", "/storages"):
        assert route in src
    assert "/api/connections/1/events" in src and "mode=\"hang\"" in src and "stop_fake" in src


def test_the_doc_states_the_findings_the_limits_and_cites_real_files():
    doc = (ROOT / "docs" / "robustesse.md").read_text(encoding="utf-8")
    for needle in ("trois défauts réels", "Ce n'est pas une promesse de capacité", "Limites de cette mesure", "Jamais mesuré", "Une seule machine, un seul worker", "cas pire",
                   "KAJI_MAX_CONCURRENT_REQUESTS", "Nagle", "garde sa connexion à la base"):
        assert needle in doc, needle
    for rel in set(re.findall(r"`((?:tools|backend|docs)/[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.(?:py|md))`", doc)):
        assert (ROOT / rel).exists(), rel
    assert "@@" not in doc and "| sain, 1 utilisateur(s) |" in doc
