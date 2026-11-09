"""Notifications, lecture seule (lot #151, étape 1) : faux Proxmox STRICT (GET seulement ; tout autre appel : 400 et noté).
Le faux renvoie volontairement les SECRETS (mot de passe SMTP, jeton Gotify, valeurs d'en-têtes, corps du webhook, identifiants dans l'adresse) : Kaji ne doit jamais les relayer."""
import json

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cr3t-value-xyz"}
SMTP_PASSWORD = "smtp-PASSWORD-xyz"
GOTIFY_TOKEN = "gotify-TOKEN-abc"
HEADER_VALUE = "SGVhZGVyVmFsdWVTRUNSRVQ="
SECRET_VALUE = "U2VjcmV0VmFsdWVUT0tFTg=="
WEBHOOK_BODY = "e3sgdGl0bGUgfX0gQk9EWS1TRUNSRVQ="
URL_PASSWORD = "urlpass-123"
URL_TOKEN = "tok-in-query"
LEAKS = (SMTP_PASSWORD, GOTIFY_TOKEN, HEADER_VALUE, SECRET_VALUE, WEBHOOK_BODY, URL_PASSWORD, URL_TOKEN)
CALLS: list[tuple[str, str]] = []
ST: dict = {}


def fresh():
    ST.clear()
    ST.update(fail=set(), targets=[
        {"name": "mail-to-root", "type": "sendmail", "origin": "builtin", "comment": "Send mail to root@pam's email address", "disable": 0},
        {"name": "relais", "type": "smtp", "origin": "user-created", "comment": "relais de l'entreprise"},
        {"name": "phone", "type": "gotify", "origin": "user-created"},
        {"name": "hook", "type": "webhook", "origin": "user-created", "disable": 1},
        {"name": "pas valide!", "type": "smtp"},                                    # nom invalide : écarté
        {"name": "inconnu", "type": "telegram"},                                      # type inconnu : écarté
        "pas un objet"])
    ST["endpoints"] = {
        "sendmail": [{"name": "mail-to-root", "origin": "builtin", "mailto-user": ["root@pam"], "from-address": "pve@lab.example", "author": "Proxmox VE", "comment": "x", "digest": "d"}],
        "smtp": [{"name": "relais", "origin": "user-created", "server": "smtp.example", "port": 587, "mode": "starttls", "username": "kaji", "password": SMTP_PASSWORD,
                  "from-address": "pve@lab.example", "mailto": ["a@example.org", "b@example.org"]}],
        "gotify": [{"name": "phone", "origin": "user-created", "server": f"https://u:{URL_PASSWORD}@gotify.example:8443/push?token={URL_TOKEN}#frag", "token": GOTIFY_TOKEN}],
        "webhook": [{"name": "hook", "origin": "user-created", "url": f"https://bob:{URL_PASSWORD}@hooks.example/path/x?key={URL_TOKEN}", "method": "post", "disable": 1,
                     "header": [f"name=X-Token,value={HEADER_VALUE}", f"name=Content-Type,value={HEADER_VALUE}"], "secret": [f"name=apikey,value={SECRET_VALUE}"], "body": WEBHOOK_BODY}]}
    ST["matchers"] = [
        {"name": "default-matcher", "origin": "builtin", "mode": "all", "match-severity": ["error", "warning"], "target": ["mail-to-root"]},
        {"name": "regle", "origin": "user-created", "mode": "any", "invert-match": 1, "match-field": ["exact:type=vzdump", "regex:hostname=^pve"], "match-calendar": ["mon-fri 8-18"],
         "target": ["relais", "pas valide!"], "comment": "sauvegardes"}]
    ST["fields"] = [{"name": "type"}, {"name": "hostname"}, {"name": "pas valide!"}]
    ST["values"] = [{"field": "type", "value": "vzdump", "comment": "Backup job"}, {"field": "hostname", "value": "enzo"}, {"field": "", "value": "x"}]


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p))
    if request.method != "GET" or request.url.query:
        return httpx.Response(400, json={"data": None, "message": "refusé : GET sans paramètres seulement"})
    if p in ST["fail"]:
        return httpx.Response(403, json={"data": None})
    table = {"/cluster/notifications/targets": ST["targets"], "/cluster/notifications/matchers": ST["matchers"],
             "/cluster/notifications/matcher-fields": ST["fields"], "/cluster/notifications/matcher-field-values": ST["values"]}
    for t, rows in ST["endpoints"].items():
        table[f"/cluster/notifications/endpoints/{t}"] = rows
    return httpx.Response(200 if p in table else 404, json={"data": table.get(p)})


@pytest.fixture
def api(client):
    CALLS.clear()
    fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, tail):
    return f"/api/connections/{cid}/notifications/{tail}"


@pytest.mark.parametrize("tail", ["targets", "endpoints", "endpoints/smtp", "matchers", "matcher-fields", "matcher-field-values"])
def test_requires_auth(client, tail):
    assert client.get(url(1, tail)).status_code == 401


def test_targets_keep_only_valid_known_types_sorted_with_origin(api):
    c, cid = api
    r = c.get(url(cid, "targets"))
    assert r.status_code == 200
    assert [(t["name"], t["type"], t["origin"], t["disable"]) for t in r.json()] == [
        ("hook", "webhook", "user-created", True), ("mail-to-root", "sendmail", "builtin", False), ("phone", "gotify", "user-created", False), ("relais", "smtp", "user-created", False)]
    assert next(t for t in r.json() if t["name"] == "mail-to-root")["comment"] == "Send mail to root@pam's email address"


def test_endpoints_return_the_settings_of_each_type(api):
    c, cid = api
    e = c.get(url(cid, "endpoints")).json()
    assert e["unavailable"] == []
    send, smtp, gotify, hook = (e["endpoints"][t][0] for t in ("sendmail", "smtp", "gotify", "webhook"))
    assert (send["from_address"], send["mailto_user"], send["author"], send["origin"]) == ("pve@lab.example", ["root@pam"], "Proxmox VE", "builtin")
    assert (smtp["server"], smtp["port"], smtp["mode"], smtp["username"], smtp["mailto"]) == ("smtp.example", 587, "starttls", "kaji", ["a@example.org", "b@example.org"])
    assert gotify["server"] == "https://gotify.example:8443/push"
    assert (hook["method"], hook["disable"], hook["header_names"], hook["secret_names"], hook["body_set"]) == ("post", True, ["X-Token", "Content-Type"], ["apikey"], True)


@pytest.mark.parametrize("tail", ["targets", "endpoints", "endpoints/smtp", "endpoints/gotify", "endpoints/webhook", "endpoints/sendmail", "matchers", "matcher-fields", "matcher-field-values"])
def test_no_secret_is_ever_relayed(api, tail):
    """Mot de passe SMTP, jeton Gotify, valeurs d'en-têtes, de secrets, corps du webhook, identifiants et paramètres d'adresse : jamais dans une réponse."""
    c, cid = api
    text = json.dumps(c.get(url(cid, tail)).json())
    assert not [s for s in LEAKS if s in text]
    assert "password" not in text and "token" not in text.lower().replace("x-token", "")


def test_webhook_url_is_cleaned_of_credentials_query_and_fragment(api):
    c, cid = api
    assert c.get(url(cid, "endpoints/webhook")).json()[0]["url"] == "https://hooks.example/path/x"
    ST["endpoints"]["webhook"][0]["url"] = "ftp://hooks.example/x"
    assert c.get(url(cid, "endpoints/webhook")).json()[0]["url"] is None                      # schéma refusé
    ST["endpoints"]["webhook"][0]["url"] = "https://[::1/x"
    assert c.get(url(cid, "endpoints/webhook")).json()[0]["url"] is None                      # adresse illisible


@pytest.mark.parametrize("typ", ["sendmail", "smtp", "gotify", "webhook"])
def test_each_type_route(api, typ):
    c, cid = api
    r = c.get(url(cid, f"endpoints/{typ}"))
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["type"] == typ


@pytest.mark.parametrize("typ", ["telegram", "SMTP", "..", "smtp;x"])
def test_unknown_type_is_refused_without_calling_proxmox(api, typ):
    c, cid = api
    assert c.get(url(cid, f"endpoints/{typ}")).status_code in (404, 422) and CALLS == []


def test_one_unreadable_type_does_not_hide_the_others(api):
    c, cid = api
    ST["fail"].add("/cluster/notifications/endpoints/webhook")
    e = c.get(url(cid, "endpoints")).json()
    assert e["unavailable"] == ["webhook"] and e["endpoints"]["webhook"] == [] and len(e["endpoints"]["smtp"]) == 1


def test_all_types_unreadable_is_a_clear_error(api):
    c, cid = api
    ST["fail"].update(f"/cluster/notifications/endpoints/{t}" for t in ("sendmail", "gotify", "smtp", "webhook"))
    r = c.get(url(cid, "endpoints"))
    assert r.status_code == 502 and "Mapping.Audit" in r.json()["detail"]


def test_matchers_are_shaped_and_targets_validated(api):
    c, cid = api
    m = {x["name"]: x for x in c.get(url(cid, "matchers")).json()}
    d, r = m["default-matcher"], m["regle"]
    assert (d["mode"], d["match_severity"], d["target"], d["origin"], d["invert_match"]) == ("all", ["error", "warning"], ["mail-to-root"], "builtin", False)
    assert (r["mode"], r["invert_match"], r["match_field"], r["match_calendar"], r["target"], r["comment"]) == (
        "any", True, ["exact:type=vzdump", "regex:hostname=^pve"], ["mon-fri 8-18"], ["relais"], "sauvegardes")


def test_matcher_mode_unknown_falls_back_to_all(api):
    c, cid = api
    ST["matchers"][0]["mode"] = "n'importe quoi"
    assert c.get(url(cid, "matchers")).json()[0]["mode"] == "all"


def test_matcher_fields_and_values(api):
    c, cid = api
    assert c.get(url(cid, "matcher-fields")).json() == ["hostname", "type"]
    assert c.get(url(cid, "matcher-field-values")).json() == [{"field": "type", "value": "vzdump", "comment": "Backup job"}, {"field": "hostname", "value": "enzo", "comment": None}]


def test_nothing_but_get_is_ever_sent(api):
    c, cid = api
    for tail in ("targets", "endpoints", "matchers", "matcher-fields", "matcher-field-values", "endpoints/webhook"):
        c.get(url(cid, tail))
    assert CALLS and {m for m, _ in CALLS} == {"GET"}
    assert not [p for _, p in CALLS if not p.startswith("/cluster/notifications")]


def test_rows_are_bounded(api):
    c, cid = api
    ST["targets"] = [{"name": f"cible{i}", "type": "smtp"} for i in range(500)]
    assert len(c.get(url(cid, "targets")).json()) == 200


def test_proxmox_garbage_does_not_crash(api):
    c, cid = api
    ST.update(targets="n'importe quoi", matchers={"x": 1}, fields=None, values=42)
    for tail in ("targets", "matchers", "matcher-fields", "matcher-field-values"):
        assert c.get(url(cid, tail)).json() == []


def test_proxmox_refusal_is_a_clean_error_without_secret(api):
    c, cid = api
    ST["fail"].add("/cluster/notifications/targets")
    r = c.get(url(cid, "targets"))
    assert r.status_code in (403, 502) and BODY["token_secret"] not in r.text
