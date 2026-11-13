"""WebAuthn dans les options du datacenter (lot #381) : faux Proxmox STRICT (`webauthn` = chaîne de propriétés `allow-subdomains`, `id`, `origin`, `rp`, schéma de Proxmox 9).

RIEN de ce fichier n'a tourné sur un vrai cluster : changer l'identifiant WebAuthn casse les credentials existants, un agent ne l'essaie pas.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.datacenterspec import check_webauthn_consistency, check_webauthn_id, check_webauthn_origin, digest_of, parse_webauthn, shape_options
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
PHRASE = "COUPURE POSSIBLE"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PUT_KEYS = {"keyboard", "webauthn", "delete"}
ITEM = r"(allow-subdomains=[01]|id=[A-Za-z0-9.\-]+|origin=https?://[A-Za-z0-9.\-]+(:[0-9]{1,5})?|rp=[^,]+)"
WA = re.compile(ITEM + "(," + ITEM + ")*")
CALLS: list[dict] = []
ST: dict = {}


def fresh():
    ST.clear()
    ST.update(opts={"keyboard": "fr"}, noapply=False, as_string=False)


def _parse(v: str) -> dict:
    d = {}
    for x in v.split(","):
        k, _, val = x.partition("=")
        d[k] = int(val) if k == "allow-subdomains" else val
    return d


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    if p != "/cluster/options":
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if request.method == "GET":
        o = dict(ST["opts"])
        if ST["as_string"] and isinstance(o.get("webauthn"), dict):
            o["webauthn"] = ",".join(f"{a}={b}" for a, b in o["webauthn"].items())
        return httpx.Response(200, json={"data": o})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if request.method != "PUT" or set(body) - PUT_KEYS:
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(set(body) - PUT_KEYS)}"})
    if "webauthn" in body:
        keys = [x.partition("=")[0] for x in body["webauthn"].split(",")]
        if not WA.fullmatch(body["webauthn"]) or len(set(keys)) != len(keys):
            return httpx.Response(400, json={"data": None, "message": "webauthn invalide"})
    dl = [x for x in body.get("delete", "").split(",") if x]
    if set(dl) - {"webauthn", "keyboard"} or set(dl) & set(body):
        return httpx.Response(400, json={"data": None, "message": "delete invalide"})
    CALLS.append(body)
    if not ST["noapply"]:
        for k, v in body.items():
            if k != "delete":
                ST["opts"][k] = _parse(v) if k == "webauthn" else v
        for k in dl:
            ST["opts"].pop(k, None)
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def put(c, cid, **b):
    return c.put(f"/api/connections/{cid}/datacenter/options", json=b)


def get(c, cid):
    return c.get(f"/api/connections/{cid}/datacenter/options").json()


FULL = {"allow-subdomains": 1, "id": "example.org", "origin": "https://pve.example.org:8006", "rp": "Kaji"}


# --- lecture --------------------------------------------------------------------------------------------------------------------------------------------
def test_unset_webauthn_reads_as_empty(api):
    c, cid = api
    j = get(c, cid)
    assert j["webauthn"] == {"allow_subdomains": None, "id": None, "origin": None, "rp": None} and j["readonly"] == {}


@pytest.mark.parametrize("as_string", [False, True])
def test_reads_objects_and_strings(api, as_string):
    c, cid = api
    ST["as_string"] = as_string
    ST["opts"]["webauthn"] = dict(FULL)
    j = get(c, cid)
    assert j["webauthn"] == {"allow_subdomains": True, "id": "example.org", "origin": "https://pve.example.org:8006", "rp": "Kaji"} and j["readonly"] == {}


def test_unreadable_or_unknown_values_are_reported_read_only_and_never_rewritten(api):
    c, cid = api
    ST["opts"]["webauthn"] = {"id": "bad id", "rp": "Kaji", "future-key": 1}
    j = get(c, cid)
    assert j["webauthn"]["id"] is None and j["webauthn"]["rp"] == "Kaji" and j["readonly"]["webauthn"] == "future-key,id"
    for body in ({"webauthn": {"rp": "Autre"}}, {"clear": ["webauthn"]}):
        r = put(c, cid, confirm=True, acknowledge_cut_access=True, type_name=PHRASE, **body)
        assert r.status_code == 422 and "future-key" in r.json()["detail"] and not CALLS


def test_parsers_and_hostile_values():
    s = shape_options({"webauthn": {"id": "127.0.0.1", "origin": "http://evil.example.org", "rp": "a,b", "allow-subdomains": "peut-être"}})
    assert s["webauthn"] == {"allow_subdomains": None, "id": None, "origin": None, "rp": None} and set(s["readonly"]["webauthn"].split(",")) == {"id", "origin", "rp"}
    assert parse_webauthn("allow-subdomains=0,id=Example.ORG,origin=https://PVE.example.org,rp=Mon Kaji") == {"allow_subdomains": False, "id": "example.org", "origin": "https://pve.example.org", "rp": "Mon Kaji"}


def test_the_digest_covers_webauthn(api):
    c, cid = api
    d0 = get(c, cid)["digest"]
    ST["opts"]["webauthn"] = {"rp": "Kaji"}
    assert get(c, cid)["digest"] != d0
    assert digest_of(shape_options({})) == digest_of(shape_options({}))


# --- écriture ---------------------------------------------------------------------------------------------------------------------------------------------
def test_first_configuration_needs_confirm_only_and_sends_the_schema_order(api):
    c, cid = api
    body = {"webauthn": {"rp": "Kaji", "origin": "https://pve.example.org:8006", "id": "example.org", "allow_subdomains": True}}
    r = put(c, cid, **body)
    assert r.status_code == 409 and "WebAuthn" in r.json()["detail"] and not CALLS
    r = put(c, cid, confirm=True, **body)
    assert r.status_code == 200 and CALLS == [{"webauthn": "allow-subdomains=1,id=example.org,origin=https://pve.example.org:8006,rp=Kaji"}]
    assert r.json()["webauthn"] == {"allow_subdomains": True, "id": "example.org", "origin": "https://pve.example.org:8006", "rp": "Kaji"} and r.json()["locks"]["webauthn_break"] is False


def test_adding_a_value_that_was_not_set_is_not_a_break(api):
    c, cid = api
    ST["opts"]["webauthn"] = {"id": "example.org", "origin": "https://pve.example.org"}
    assert put(c, cid, confirm=True, webauthn={"rp": "Kaji"}).status_code == 200
    assert CALLS[-1] == {"webauthn": "id=example.org,origin=https://pve.example.org,rp=Kaji"}                    # clés non renvoyées gardées


def test_resending_the_same_values_is_not_a_break(api):
    c, cid = api
    ST["opts"]["webauthn"] = dict(FULL)
    assert put(c, cid, webauthn={"id": "example.org", "rp": "Kaji", "allow_subdomains": True}).status_code == 409                 # confirm toujours exigé
    assert put(c, cid, confirm=True, webauthn={"id": "example.org", "rp": "Kaji", "allow_subdomains": True}).status_code == 200


@pytest.mark.parametrize("change", [{"id": "autre.org", "origin": "https://pve.autre.org"}, {"rp": "Autre nom"}, {"origin": "https://other.example.org"}, {"allow_subdomains": False, "origin": "https://example.org"}])
def test_changing_an_existing_value_needs_the_phrase(api, change):
    c, cid = api
    ST["opts"]["webauthn"] = dict(FULL)
    r = put(c, cid, confirm=True, webauthn=change)
    assert r.status_code == 409 and "credentials" in r.json()["detail"] and not CALLS
    assert put(c, cid, confirm=True, acknowledge_cut_access=True, webauthn=change).status_code == 409
    assert put(c, cid, confirm=True, type_name=PHRASE, webauthn=change).status_code == 409
    assert put(c, cid, confirm=True, acknowledge_cut_access=True, type_name="coupure possible", webauthn=change).status_code == 409
    assert put(c, cid, confirm=True, acknowledge_cut_access=True, type_name=PHRASE, webauthn=change).status_code == 200 and CALLS


def test_disabling_subdomains_alone_is_a_break_when_something_is_set(api):
    c, cid = api
    ST["opts"]["webauthn"] = {"id": "example.org", "origin": "https://example.org"}
    assert put(c, cid, confirm=True, webauthn={"allow_subdomains": False}).status_code == 409 and not CALLS


def test_removing_webauthn_needs_the_phrase_only_when_something_is_set(api):
    c, cid = api
    assert put(c, cid, clear=["webauthn"]).status_code == 409                                      # confirm
    assert put(c, cid, clear=["webauthn"], confirm=True).status_code == 200 and CALLS == [{"delete": "webauthn"}]       # rien de défini : aucune phrase
    CALLS.clear()
    ST["opts"]["webauthn"] = dict(FULL)
    assert put(c, cid, clear=["webauthn"], confirm=True).status_code == 409 and not CALLS
    r = put(c, cid, clear=["webauthn"], confirm=True, acknowledge_cut_access=True, type_name=PHRASE)
    assert r.status_code == 200 and CALLS == [{"delete": "webauthn"}] and "webauthn" not in ST["opts"]


def test_dry_run_reports_the_locks_and_writes_nothing(api):
    c, cid = api
    ST["opts"]["webauthn"] = dict(FULL)
    r = put(c, cid, webauthn={"rp": "Autre"}, dry_run=True)
    assert r.status_code == 200 and r.json()["locks"]["webauthn"] is True and r.json()["locks"]["webauthn_break"] is True and r.json()["params"]["webauthn"].endswith("rp=Autre") and not CALLS
    assert put(c, cid, webauthn={"allow_subdomains": True}, dry_run=True).json()["locks"]["webauthn_break"] is False


@pytest.mark.parametrize("webauthn", [{"id": "example.org", "origin": "https://evil.net"}, {"id": "example.org", "origin": "https://notexample.org"}, {"id": "example.org", "origin": "https://pve.example.org", "allow_subdomains": False},
                                      {"origin": "https://pve.example.org"}])
def test_an_origin_that_does_not_match_the_id_is_refused_before_anything_is_written(api, webauthn):
    c, cid = api
    if "id" not in webauthn:
        ST["opts"]["webauthn"] = {"id": "autre.org"}                                                 # l'état lu est pris en compte
    r = put(c, cid, confirm=True, acknowledge_cut_access=True, type_name=PHRASE, webauthn=webauthn)
    assert r.status_code == 422 and "sous-domaines" in r.json()["detail"] and not CALLS


def test_localhost_over_http_is_allowed_with_a_matching_id(api):
    c, cid = api
    assert put(c, cid, confirm=True, webauthn={"id": "localhost", "origin": "http://localhost:8006", "rp": "Dev"}).status_code == 200
    assert CALLS[-1] == {"webauthn": "id=localhost,origin=http://localhost:8006,rp=Dev"}


@pytest.mark.parametrize("wa", [
    {"id": "127.0.0.1"}, {"id": "10.0.0.5"}, {"id": "[::1]"}, {"id": "example.org:8006"}, {"id": "https://example.org"}, {"id": "example.org/x"}, {"id": "a b"}, {"id": ""}, {"id": "x" * 254},
    {"id": "-a.org"}, {"id": "a_b.org"}, {"id": "a..org"}, {"id": 5},
    {"origin": "http://example.org"}, {"origin": "https://user@example.org"}, {"origin": "https://example.org/chemin"}, {"origin": "https://example.org?x=1"}, {"origin": "https://example.org:0"},
    {"origin": "https://example.org:70000"}, {"origin": "ftp://example.org"}, {"origin": "https://"}, {"origin": "example.org"}, {"origin": "HTTPS://example.org"}, {"origin": "https://exa mple.org"},
    {"rp": "a,b"}, {"rp": 'a"b'}, {"rp": ""}, {"rp": "x" * 65}, {"rp": "a\x00b"}, {"rp": "a\nb"},
    {"allow_subdomains": "1"}, {"allow_subdomains": 1}, {"allow_subdomains": "true"},
])
def test_values_are_validated_before_anything_is_sent(api, wa):
    c, cid = api
    assert put(c, cid, confirm=True, acknowledge_cut_access=True, type_name=PHRASE, webauthn=wa).status_code == 422 and not CALLS


def test_an_empty_webauthn_is_an_empty_request(api):
    c, cid = api
    assert put(c, cid, webauthn={}).status_code == 422 and not CALLS


def test_not_applied_by_proxmox_is_a_bad_gateway_and_audited(api):
    c, cid = api
    ST["noapply"] = True
    r = put(c, cid, confirm=True, webauthn={"rp": "Kaji"})
    assert r.status_code == 502 and "n'a pas appliqué" in r.json()["detail"]
    assert ("datacenter-options", "error") in [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def test_audit_names_the_change_without_secrets(api):
    c, cid = api
    assert put(c, cid, confirm=True, webauthn={"id": "example.org", "rp": "Kaji"}).status_code == 200
    log = c.get("/api/audit").text
    assert "webauthn=id=example.org,rp=Kaji" in log and SECRET not in log and PWD not in log


def test_the_helpers_directly():
    assert check_webauthn_id("Example.ORG") == "example.org" and check_webauthn_origin("https://Pve.Example.org:8006") == "https://pve.example.org:8006"
    for bad in ("10.0.0.1", "a b", "x:1", "a." * 127 + "b"):                                                 # le dernier : étiquettes valides, 255 caractères au total
        with pytest.raises(ValueError):
            check_webauthn_id(bad)
    assert check_webauthn_id("a." * 126 + "b") == "a." * 126 + "b"                                         # 253 caractères : accepté
    check_webauthn_consistency("example.org", "https://example.org", False)
    check_webauthn_consistency("example.org", "https://a.b.example.org", None)
    check_webauthn_consistency(None, "https://anything.net", None)
    check_webauthn_consistency("example.org", None, None)
    with pytest.raises(ValueError):
        check_webauthn_consistency("example.org", "https://a.example.org", False)
