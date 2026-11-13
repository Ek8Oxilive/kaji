"""Options du datacenter (lot #150) : faux Proxmox STRICT (méthode, paramètres, valeurs ; 400 sinon)."""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.datacenterspec import KEYBOARDS, check_proxy, digest_of, parse_migration, shape_options
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PUT_KEYS = {"keyboard", "language", "console", "description", "email_from", "http_proxy", "mac_prefix", "max_workers", "migration", "delete"}
DELETABLE = {"keyboard", "language", "console", "description", "mac_prefix", "migration", "max_workers", "email_from", "http_proxy"}
CALLS: list[tuple[str, dict]] = []
ST: dict = {}


def fresh():
    ST.clear()
    ST.update(opts={"keyboard": "fr", "language": "fr", "description": "notes d'origine\n", "migration": {"type": "secure", "network": "10.0.0.0/24"}, "max_workers": 4,
                    "ha": {"shutdown_policy": "migrate"}, "fencing": "watchdog", "bwlimit": {"default": 1000}},
              noapply=False, fail=False, string_migration=False, trailing=True)


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    if p != "/cluster/options":
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if request.method == "GET":
        o = dict(ST["opts"])
        if ST["string_migration"] and isinstance(o.get("migration"), dict):
            o["migration"] = ",".join(f"{k}={v}" for k, v in o["migration"].items())
        return httpx.Response(200, json={"data": o})
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if request.method != "PUT" or set(body) - PUT_KEYS:
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(set(body) - PUT_KEYS)}"})
    if "keyboard" in body and body["keyboard"] not in KEYBOARDS or "max_workers" in body and not (body["max_workers"].isdigit() and int(body["max_workers"]) >= 1):
        return httpx.Response(400, json={"data": None, "message": "valeur invalide"})
    if "migration" in body and not re.fullmatch(r"type=(secure|insecure)(,network=[0-9a-f:.]+/[0-9]+)?", body["migration"]):
        return httpx.Response(400, json={"data": None, "message": "migration invalide"})
    dl = [x for x in body.get("delete", "").split(",") if x]
    if set(dl) - DELETABLE:
        return httpx.Response(400, json={"data": None, "message": "delete invalide"})
    CALLS.append(("PUT", body))
    if not ST["noapply"]:
        o = ST["opts"]
        for k, v in body.items():
            if k == "delete":
                continue
            if k == "migration":
                o[k] = dict(x.split("=") for x in v.split(","))
            elif k == "max_workers":
                o[k] = int(v)
            elif k == "description":
                o[k] = v + ("\n" if ST["trailing"] else "")
            elif k == "mac_prefix":
                o[k] = v.lower()                                                                           # Proxmox peut renvoyer une autre casse
            else:
                o[k] = v
        for k in dl:
            if k == "description":
                o[k] = ""                                                                                   # constaté en réel : Proxmox renvoie une chaîne vide, pas une clé absente
            else:
                o.pop(k, None)
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid):
    return f"/api/connections/{cid}/datacenter/options"


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- lecture
def test_read_shapes_managed_fields_and_readonly(api):
    c, cid = api
    j = c.get(url(cid)).json()
    assert (j["keyboard"], j["language"], j["console"], j["max_workers"]) == ("fr", "fr", None, 4) and j["migration"] == {"type": "secure", "network": "10.0.0.0/24"}
    assert j["description"] == "notes d'origine\n" and j["readonly"] == {}                                    # ha, fencing, bwlimit sont modifiables depuis le lot #365
    assert j["ha"] == {"shutdown_policy": "migrate"} and j["fencing"] == "watchdog" and j["bwlimit"]["default"] == 1000 and j["crs"] == {"ha": None, "ha_rebalance_on_start": None}
    assert len(j["digest"]) == 40 and c.get(url(cid)).json()["digest"] == j["digest"]


def test_read_accepts_string_form_of_migration_and_legacy_flag(api):
    c, cid = api
    ST["string_migration"] = True
    assert c.get(url(cid)).json()["migration"] == {"type": "secure", "network": "10.0.0.0/24"}
    ST["opts"].pop("migration"); ST["opts"]["migration_unsecure"] = 1; ST["string_migration"] = False
    assert c.get(url(cid)).json()["migration"] == {"type": "insecure", "network": None}


def test_shape_drops_hostile_values_and_unknown_fields():
    s = shape_options({"keyboard": "xx", "language": ["fr"], "console": 5, "description": "ok\x00bad", "mac_prefix": "01", "max_workers": True, "email_from": "a b", "http_proxy": "http://u:p@h",
                       "migration": {"type": "bogus", "network": "999.1.1.1/8"}, "evil": SECRET, "ha": {"x": SECRET * 30}})
    assert s["keyboard"] is None and s["language"] is None and s["console"] is None and s["max_workers"] is None and s["email_from"] is None and s["http_proxy"] is None
    assert s["mac_prefix"] is None and s["migration"] == {"type": None, "network": None} and "evil" not in repr(s) and "\x00" not in s["description"] and len(s["readonly"]["ha"]) <= 200
    assert shape_options(None)["keyboard"] is None and shape_options("x")["readonly"] == {}
    assert parse_migration("type=insecure,network=10.1.0.0/16") == {"type": "insecure", "network": "10.1.0.0/16"} and parse_migration(5) == {"type": None, "network": None}


def test_digest_changes_with_any_value():
    a = shape_options({"keyboard": "fr"})
    assert digest_of(a) == digest_of(shape_options({"keyboard": "fr"})) and digest_of(a) != digest_of(shape_options({"keyboard": "de"}))


# ---------------------------------------------------------------- écriture : paramètres exacts
def test_put_sends_exact_params_and_returns_fresh_state(api):
    c, cid = api
    r = c.put(url(cid), json={"keyboard": "de", "language": "en", "console": "xtermjs", "description": "ligne 1\nligne\t2", "mac_prefix": "bc:24:12", "max_workers": 8,
                              "email_from": "kaji@example.org", "http_proxy": "http://192.168.1.10:3128"})
    assert r.status_code == 200 and r.json()["keyboard"] == "de" and r.json()["max_workers"] == 8 and sorted(r.json()["changed"]) == sorted(["keyboard", "language", "console", "description", "mac_prefix", "max_workers", "email_from", "http_proxy"])
    assert CALLS == [("PUT", {"keyboard": "de", "language": "en", "console": "xtermjs", "description": "ligne 1\nligne\t2", "mac_prefix": "BC:24:12", "max_workers": "8",
                               "email_from": "kaji@example.org", "http_proxy": "http://192.168.1.10:3128"})]
    assert r.json()["description"].startswith("ligne 1\nligne\t2")                                           # Proxmox ajoute un \n final : toléré


def test_unknown_and_out_of_scope_fields_are_never_forwarded(api):
    c, cid = api
    r = c.put(url(cid), json={"keyboard": "de", "consent-text": "x", "notify": "x", "next-id": "lower=1", "registered-tags": "a", "u2f": "x", "migration_unsecure": 1, "tag-style": "shape=full",
                              "ha-resources": "x", "replication_type": "insecure"})
    assert r.status_code == 200 and CALLS[-1][1] == {"keyboard": "de"} and ST["opts"]["fencing"] == "watchdog" and ST["opts"]["ha"] == {"shutdown_policy": "migrate"}


@pytest.mark.parametrize("b", [
    {"keyboard": "xx"}, {"keyboard": ""}, {"keyboard": 5}, {"language": "xx"}, {"console": "java"}, {"mac_prefix": "01:00:00"}, {"mac_prefix": "BC:24"}, {"mac_prefix": "BC:24:11:00"},
    {"mac_prefix": "GG:00:00"}, {"mac_prefix": "bc-24-11"}, {"max_workers": 0}, {"max_workers": 65}, {"max_workers": 500}, {"max_workers": "4"}, {"max_workers": True}, {"max_workers": 4.5},
    {"email_from": "pas un mail"}, {"email_from": "a@b c"}, {"email_from": "x" * 260 + "@a.fr"},
    {"http_proxy": "https://proxy:3128"}, {"http_proxy": "http://user:pw@proxy:3128"}, {"http_proxy": "http://user@proxy"}, {"http_proxy": "http://127.0.0.1:3128"}, {"http_proxy": "http://localhost"},
    {"http_proxy": "http://sub.localhost:80"}, {"http_proxy": "http://[::1]:80"}, {"http_proxy": "http://0.0.0.0"}, {"http_proxy": "http://169.254.1.1"}, {"http_proxy": "http://224.0.0.1"},
    {"http_proxy": "http://h:99999"}, {"http_proxy": "http://h:0"}, {"http_proxy": "http://h/chemin"}, {"http_proxy": "http://h?x=1"}, {"http_proxy": "http://h:8080/x"}, {"http_proxy": "http:// h"},
    {"http_proxy": "http://h\n"}, {"http_proxy": ""},
    {"migration": {"type": "bogus"}}, {"migration": {"network": "10.0.0.1/24"}}, {"migration": {"network": "abc"}}, {"migration": {"network": "10.0.0.0/33"}}, {"migration": "secure"},
    {"description": "a\x00b"}, {"description": "a\rb"}, {"description": "x" * 65537}, {"clear": ["../x"]}, {"clear": ["u2f"]},
    {"keyboard": "de", "clear": ["keyboard"]}, {}, {"clear": []}, {"dry_run": "yes", "keyboard": "de"}, {"confirm": "true", "keyboard": "de"}, {"digest": "x" * 65, "keyboard": "de"},
])
def test_invalid_input_is_refused_without_any_proxmox_write(api, b):
    c, cid = api
    assert c.put(url(cid), json=b).status_code == 422 and not CALLS


def test_valid_proxies_are_accepted(api):
    c, cid = api
    for proxy in ("http://192.168.1.10:3128", "http://proxy.lan:8080/", "http://proxy.example.org", "http://[2001:db8::1]:3128"):
        assert c.put(url(cid), json={"http_proxy": proxy}).status_code == 200
        assert CALLS[-1][1]["http_proxy"] == proxy
    assert check_proxy("http://10.0.0.1") == "http://10.0.0.1"


# ---------------------------------------------------------------- migration : fusion et chiffrement
def test_migration_merges_with_the_current_state(api):
    c, cid = api
    assert c.put(url(cid), json={"migration": {"network": "10.9.0.0/16"}}).status_code == 200
    assert CALLS[-1][1] == {"migration": "type=secure,network=10.9.0.0/16"}                                  # type conservé
    assert c.put(url(cid), json={"migration": {"network": ""}}).status_code == 200
    assert CALLS[-1][1] == {"migration": "type=secure"} and ST["opts"]["migration"] == {"type": "secure"}   # réseau retiré
    assert c.put(url(cid), json={"migration": {}}).status_code == 422                                        # rien à changer


def test_insecure_migration_needs_confirm_and_is_flagged_in_dry_run(api):
    c, cid = api
    r = c.put(url(cid), json={"migration": {"type": "insecure"}})
    assert r.status_code == 409 and "non chiffrée" in r.json()["detail"] and not CALLS and ST["opts"]["migration"]["type"] == "secure"
    d = c.put(url(cid), json={"migration": {"type": "insecure"}, "dry_run": True}).json()
    assert d["dry_run"] is True and d["locks"]["insecure"] is True and d["params"]["migration"] == "type=insecure,network=10.0.0.0/24" and not CALLS
    assert c.put(url(cid), json={"migration": {"type": "insecure"}, "confirm": False}).status_code == 409
    assert c.put(url(cid), json={"migration": {"type": "insecure"}, "confirm": True}).status_code == 200 and CALLS[-1][1]["migration"].startswith("type=insecure")
    assert c.put(url(cid), json={"migration": {"network": "10.5.0.0/16"}}).status_code == 200                # déjà non chiffrée : pas de nouvelle confirmation
    assert CALLS[-1][1] == {"migration": "type=insecure,network=10.5.0.0/16"}                                # et le type non chiffré est conservé, jamais remis à « secure » en douce


def test_secure_type_never_needs_confirm(api):
    c, cid = api
    assert c.put(url(cid), json={"migration": {"type": "secure", "network": "10.1.0.0/16"}}).status_code == 200


# ---------------------------------------------------------------- retrait, digest, relecture
def test_clear_sends_delete_and_verifies(api):
    c, cid = api
    r = c.put(url(cid), json={"clear": ["keyboard", "migration", "max_workers", "keyboard"]})
    assert r.status_code == 200 and r.json()["removed"] == ["keyboard", "migration", "max_workers"]
    assert CALLS[-1][1] == {"delete": "keyboard,migration,max_workers"} and "keyboard" not in ST["opts"] and "migration" not in ST["opts"]
    j = c.get(url(cid)).json()
    assert j["keyboard"] is None and j["migration"] == {"type": None, "network": None}


def test_removing_the_notes_succeeds_when_proxmox_returns_an_empty_string(api):
    c, cid = api
    r = c.put(url(cid), json={"clear": ["description"]})
    assert r.status_code == 200 and r.json()["removed"] == ["description"] and CALLS[-1][1] == {"delete": "description"}
    assert ST["opts"]["description"] == "" and r.json()["description"] == ""


def test_stale_digest_is_refused_with_409_and_nothing_is_written(api):
    c, cid = api
    d = c.get(url(cid)).json()["digest"]
    ST["opts"]["language"] = "de"                                                                           # quelqu'un d'autre a modifié entre-temps
    r = c.put(url(cid), json={"keyboard": "de", "digest": d})
    assert r.status_code == 409 and "digest périmé" in r.json()["detail"] and not CALLS
    new = c.get(url(cid)).json()["digest"]
    assert new != d and c.put(url(cid), json={"keyboard": "de", "digest": new}).status_code == 200
    assert c.put(url(cid), json={"language": "fr", "digest": "0" * 40}).status_code == 409


def test_digest_in_the_response_matches_a_new_read(api):
    c, cid = api
    r = c.put(url(cid), json={"keyboard": "it"})
    assert r.json()["digest"] == c.get(url(cid)).json()["digest"]


def test_unapplied_change_is_a_502(api):
    c, cid = api
    ST["noapply"] = True
    r = c.put(url(cid), json={"keyboard": "de"})
    assert r.status_code == 502 and "n'a pas" in r.json()["detail"] and audit_pairs(c)[-1] == ("datacenter-options", "error")
    r = c.put(url(cid), json={"clear": ["keyboard"]})
    assert r.status_code == 502 and "retiré" in r.json()["detail"]


def test_notes_with_trailing_newline_from_proxmox_are_accepted(api):
    c, cid = api
    ST["trailing"] = True
    assert c.put(url(cid), json={"description": "mes notes\n\n"}).status_code == 200
    ST["trailing"] = False
    assert c.put(url(cid), json={"description": "mes notes"}).status_code == 200


def test_mac_prefix_case_is_normalised(api):
    c, cid = api
    assert c.put(url(cid), json={"mac_prefix": "bc:24:11"}).status_code == 200 and CALLS[-1][1]["mac_prefix"] == "BC:24:11"


# ---------------------------------------------------------------- audit, secrets, droits
def test_audit_records_success_and_refusals_without_notes_content(api):
    c, cid = api
    c.put(url(cid), json={"description": "texte-prive-xyz", "keyboard": "de"})
    c.put(url(cid), json={"migration": {"type": "insecure"}})
    c.put(url(cid), json={"keyboard": "xx"})                                                                 # 422 de validation : pas d'écriture, pas d'entrée d'audit nécessaire
    assert audit_pairs(c).count(("datacenter-options", "started")) == 1 and ("datacenter-options", "error") in audit_pairs(c)
    txt = c.get("/api/audit").text
    assert "texte-prive-xyz" not in txt and SECRET not in txt and "description=défini" in txt


def test_proxmox_error_never_leaks_its_message(api):
    c, cid = api
    ST["fail"] = True
    r = c.put(url(cid), json={"keyboard": "de"})
    assert r.status_code == 502 and SECRET not in r.text and SECRET not in c.get("/api/audit").text


def test_requires_authentication(client):
    assert client.get(url(1)).status_code == 401 and client.put(url(1), json={"keyboard": "de"}).status_code == 401
