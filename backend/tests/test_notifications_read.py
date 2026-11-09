"""Notifications en lecture (lot #151, étape 1) : faux Proxmox qui renvoie les SECRETS en clair ; Kaji ne doit jamais les relayer."""
import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.notificationspec import shape_endpoint, shape_field_values, shape_fields, shape_matchers, shape_targets
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
SMTP_PW = "pw-smtp-SECRET-1"
GOTIFY = "gotify-token-SECRET-2"
HDR_VAL = "QmVhcmVyIFNFQ1JFVC0z"            # valeur d'en-tête (base64 d'un jeton)
BODY_TPL = "e3sgZXNjYXBlIH19U0VDUkVULUJPRFk="
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DATA: dict = {}
CALLS: list[tuple[str, str]] = []


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p))
    if request.method != "GET":
        return httpx.Response(405, json={"data": None, "message": "lecture seule"})
    if p in DATA:
        v = DATA[p]
        return httpx.Response(v[0], json=v[1]) if isinstance(v, tuple) else httpx.Response(200, json={"data": v})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    DATA.clear(); CALLS.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def full():
    B = "/cluster/notifications"
    DATA[f"{B}/targets"] = [{"name": "mail-to-root", "type": "sendmail", "origin": "builtin", "disable": 0}, {"name": "smtp-lab", "type": "smtp", "origin": "user-created", "comment": "labo"},
                            {"name": "gotify1", "type": "gotify", "origin": "user-created"}, {"name": "hook1", "type": "webhook", "origin": "user-created", "disable": 1}]
    DATA[f"{B}/endpoints/sendmail"] = [{"name": "mail-to-root", "origin": "builtin", "mailto-user": ["root@pam"], "comment": "Send mails to root"}]
    DATA[f"{B}/endpoints/smtp"] = [{"name": "smtp-lab", "server": "smtp.example.org", "port": 587, "mode": "starttls", "username": "kaji", "password": SMTP_PW, "from-address": "pve@example.org",
                                    "mailto": ["a@example.org", "b@example.org"], "author": "Proxmox", "origin": "user-created"}]
    DATA[f"{B}/endpoints/gotify"] = [{"name": "gotify1", "server": "https://gotify.example.org", "token": GOTIFY, "origin": "user-created"}]
    DATA[f"{B}/endpoints/webhook"] = [{"name": "hook1", "url": "https://hooks.example.org/x", "method": "post", "header": [f"Authorization={HDR_VAL}", "X-Env=cHJvZA=="], "secret": [f"api-key={HDR_VAL}"],
                                       "body": BODY_TPL, "disable": 1, "origin": "user-created"}]
    DATA[f"{B}/matchers"] = [{"name": "default-matcher", "origin": "builtin", "target": ["mail-to-root"], "mode": "all", "match-severity": ["warning", "error"]},
                             {"name": "backups", "origin": "user-created", "target": ["smtp-lab", "gotify1"], "match-field": ["exact:type=vzdump"], "match-calendar": ["mon..fri 08-18"], "invert-match": 1, "mode": "any"}]
    DATA[f"{B}/matcher-fields"] = [{"name": "type"}, {"name": "hostname"}, {"name": "job-id"}]
    DATA[f"{B}/matcher-field-values"] = [{"field": "type", "value": "vzdump", "comment": "Sauvegarde"}, {"field": "type", "value": "fencing"}]


def test_aggregate_shapes_everything_and_never_leaks_a_secret(api):
    c, cid = api
    full()
    r = c.get(f"/api/connections/{cid}/notifications")
    assert r.status_code == 200
    for secret in (SMTP_PW, GOTIFY, HDR_VAL, BODY_TPL, SECRET):
        assert secret not in r.text
    j = r.json()
    assert j["errors"] == {} and [t["name"] for t in j["targets"]] == ["gotify1", "hook1", "mail-to-root", "smtp-lab"]
    root = next(t for t in j["targets"] if t["name"] == "mail-to-root")
    assert root["builtin"] is True and root["used_by"] == ["default-matcher"] and next(t for t in j["targets"] if t["name"] == "hook1")["disable"] is True
    assert j["unused_targets"] == ["hook1"]
    smtp = j["endpoints"]["smtp"][0]
    assert (smtp["server"], smtp["port"], smtp["mode"], smtp["username"], smtp["from_address"], smtp["mailto"]) == ("smtp.example.org", 587, "starttls", "kaji", "pve@example.org", ["a@example.org", "b@example.org"])
    assert "password" not in smtp and j["endpoints"]["gotify"][0]["server"] == "https://gotify.example.org" and "token" not in j["endpoints"]["gotify"][0]
    hook = j["endpoints"]["webhook"][0]
    assert hook["header_names"] == ["Authorization", "X-Env"] and hook["secret_names"] == ["api-key"] and hook["body_set"] is True and hook["method"] == "post" and "header" not in hook and "body" not in hook
    assert j["endpoints"]["sendmail"][0]["mailto_user"] == ["root@pam"]
    m = next(x for x in j["matchers"] if x["name"] == "backups")
    assert (m["invert"], m["mode"], m["targets"], m["match_field"], m["match_calendar"]) == (True, "any", ["smtp-lab", "gotify1"], ["exact:type=vzdump"], ["mon..fri 08-18"])
    assert j["fields"] == ["hostname", "job-id", "type"] and all(meth == "GET" for meth, _ in CALLS)


def test_a_failing_part_does_not_break_the_others_and_never_leaks(api):
    c, cid = api
    full()
    DATA["/cluster/notifications/endpoints/gotify"] = (403, {"data": None, "message": SECRET})
    DATA["/cluster/notifications/matchers"] = (500, {"data": None, "message": SECRET})
    r = c.get(f"/api/connections/{cid}/notifications")
    assert r.status_code == 200 and SECRET not in r.text
    j = r.json()
    assert set(j["errors"]) == {"endpoints/gotify", "matchers"} and "Droits insuffisants" in j["errors"]["endpoints/gotify"] and j["endpoints"]["gotify"] == []
    assert len(j["targets"]) == 4 and len(j["endpoints"]["smtp"]) == 1


def test_field_values_route(api):
    c, cid = api
    full()
    r = c.get(f"/api/connections/{cid}/notifications/field-values")
    assert r.status_code == 200 and r.json() == [{"field": "type", "value": "vzdump", "comment": "Sauvegarde"}, {"field": "type", "value": "fencing", "comment": None}]


def test_requires_authentication(client):
    assert client.get("/api/connections/1/notifications").status_code == 401 and client.get("/api/connections/1/notifications/field-values").status_code == 401


# ---------------------------------------------------------------- mise en forme (valeurs hostiles)
def test_shape_targets_drops_junk():
    rows = shape_targets([{"name": "ok", "type": "smtp", "origin": "evil"}, {"name": "../x", "type": "smtp"}, {"name": "a", "type": "smtp"}, {"name": "okok", "type": "group"}, "junk", 5, None, {"name": "b" * 70, "type": "gotify"}])
    assert [t["name"] for t in rows] == ["ok"] and rows[0]["origin"] is None and rows[0]["builtin"] is False
    assert shape_targets(None) == [] and shape_targets("x") == []


def test_shape_endpoint_whitelists_per_type_and_hides_every_secret():
    smtp = shape_endpoint({"name": "s1", "password": SMTP_PW, "token": GOTIFY, "url": "http://x", "port": "587", "mode": "bogus", "mailto": "a@b.c,d@e.f", "evil": SECRET}, "smtp")
    assert smtp["port"] == 587 and smtp["mode"] is None and smtp["mailto"] == ["a@b.c", "d@e.f"] and "url" not in smtp and SMTP_PW not in repr(smtp) and GOTIFY not in repr(smtp) and SECRET not in repr(smtp)
    hook = shape_endpoint({"name": "h1", "method": "delete", "header": ["Bad Name=x", "X-Ok=secretval", "../x=y", 5], "secret": "k1=v1,k2=v2", "body": ""}, "webhook")
    assert hook["method"] is None and hook["header_names"] == ["X-Ok"] and hook["secret_names"] == ["k1", "k2"] and hook["body_set"] is False and "secretval" not in repr(hook) and "v1" not in repr(hook)
    assert shape_endpoint({"name": "../x"}, "gotify") is None and shape_endpoint("x", "gotify") is None and "mailto" not in shape_endpoint({"name": "g1"}, "gotify")


def test_endpoint_origin_is_whitelisted_and_builtin_is_flagged():
    assert shape_endpoint({"name": "s1", "origin": "evil"}, "smtp")["origin"] is None and shape_endpoint({"name": "s1", "origin": "evil"}, "smtp")["builtin"] is False
    e = shape_endpoint({"name": "mail-to-root", "origin": "builtin"}, "sendmail")
    assert e["origin"] == "builtin" and e["builtin"] is True and shape_endpoint({"name": "x1", "origin": "modified-builtin"}, "gotify")["builtin"] is False


def test_shape_matchers_keeps_only_known_values():
    m = shape_matchers([{"name": "mm", "mode": "sometimes", "match-severity": ["warning", "fatal", "error"], "target": ["ok-target", "../x", "a b"], "invert-match": "1", "match-field": ["exact:a=b", 5]}, {"name": "../x"}, "junk"])
    assert len(m) == 1 and m[0]["mode"] == "all" and m[0]["match_severity"] == ["warning", "error"] and m[0]["targets"] == ["ok-target"] and m[0]["invert"] is True and m[0]["match_field"] == ["exact:a=b"]


def test_shape_fields_and_values_are_bounded_and_filtered():
    assert shape_fields([{"name": "b"}, {"name": "a"}, {"name": "../x"}, {"name": "a"}, "junk"]) == ["a", "b"]
    assert shape_fields([{"name": f"f{i}"} for i in range(300)]) and len(shape_fields([{"name": f"f{i}"} for i in range(300)])) == 100
    assert shape_field_values([{"field": "type", "value": "x" * 500}, {"field": "../x", "value": "y"}])[0]["value"] == "x" * 120 and len(shape_field_values([{"field": "type", "value": "y"}] * 800)) == 500
