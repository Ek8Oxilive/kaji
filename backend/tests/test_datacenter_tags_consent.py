"""Options du datacenter, fin (lot #243) : étiquettes réservées (`registered-tags`), droits des utilisateurs sur les étiquettes (`user-tag-access`),
texte de consentement (`consent-text`). Faux Proxmox STRICT (méthode, chemin et paramètres exacts). Formats tirés du schéma de `datacenter.cfg`
de Proxmox VE, À CONFIRMER en réel (voir la PR).
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.datacenterspec import parse_tag_list, parse_user_tag_access, shape_options
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
CONSENT = "Accès réservé aux administrateurs.\nToute connexion est journalisée."
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PUT_KEYS = {"keyboard", "registered-tags", "user-tag-access", "consent-text", "delete"}
TAGS = re.compile(r"[a-z0-9_][a-z0-9_\-+.]{0,63}(;[a-z0-9_][a-z0-9_\-+.]{0,63})*")
UTA = re.compile(r"user-allow=(none|existing|free)|user-allow=list,user-allow-list=" + TAGS.pattern)
CALLS: list[dict] = []
ST: dict = {}


def fresh():
    ST.clear()
    ST.update(opts={"keyboard": "fr", "ha": {"shutdown_policy": "migrate"}}, noapply=False, as_dict=False, trailing=False)


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    if p != "/cluster/options":
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if request.method == "GET":
        o = dict(ST["opts"])
        if ST["as_dict"] and isinstance(o.get("user-tag-access"), str):
            o["user-tag-access"] = dict(x.partition("=")[::2] for x in o["user-tag-access"].split(",") if "=" in x)
        return httpx.Response(200, json={"data": o})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if request.method != "PUT" or set(body) - PUT_KEYS:
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(set(body) - PUT_KEYS)}"})
    if "registered-tags" in body and not TAGS.fullmatch(body["registered-tags"]):
        return httpx.Response(400, json={"data": None, "message": "registered-tags invalide"})
    if "user-tag-access" in body and not UTA.fullmatch(body["user-tag-access"]):
        return httpx.Response(400, json={"data": None, "message": "user-tag-access invalide"})
    if "consent-text" in body and (not body["consent-text"] or len(body["consent-text"]) > 3000):
        return httpx.Response(400, json={"data": None, "message": "consent-text invalide"})
    dl = [x for x in body.get("delete", "").split(",") if x]
    if set(dl) - {"registered-tags", "user-tag-access", "consent-text", "keyboard"}:
        return httpx.Response(400, json={"data": None, "message": "delete invalide"})
    CALLS.append(body)
    if not ST["noapply"]:
        for k, v in body.items():
            if k != "delete":
                ST["opts"][k] = v + ("\n" if ST["trailing"] and k == "consent-text" else "")
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


# --- lecture --------------------------------------------------------------------------------------------------------------------------------------------

def test_reads_the_three_settings_in_string_and_object_forms(api):
    c, cid = api
    ST["opts"].update({"registered-tags": "prod;Dev;prod;mauvais tag", "user-tag-access": "user-allow=list,user-allow-list=a;b", "consent-text": CONSENT})
    for as_dict in (False, True):
        ST["as_dict"] = as_dict
        j = get(c, cid)
        assert j["registered_tags"] == ["prod", "dev"]                                       # minuscules, sans doublon, valeur mal formée écartée
        assert j["user_tag_access"] == {"user_allow": "list", "user_allow_list": ["a", "b"]}
        assert j["consent_text"] == CONSENT
        for k in ("registered-tags", "user-tag-access", "consent-text"):
            assert k not in j["readonly"]


def test_absent_or_garbage_values_give_empty_structures():
    s = shape_options({})
    assert s["registered_tags"] == [] and s["user_tag_access"] == {"user_allow": None, "user_allow_list": []} and s["consent_text"] is None
    assert parse_tag_list(None) == [] and parse_tag_list(["a", 5, "B", "a b"]) == ["a", "b"]
    assert parse_tag_list(";".join(f"t{i}" for i in range(300))) == [f"t{i}" for i in range(100)]
    assert parse_user_tag_access("user-allow=bizarre")["user_allow"] is None


# --- registered-tags ------------------------------------------------------------------------------------------------------------------------------------

def test_registered_tags_written_normalized_and_read_back(api):
    c, cid = api
    r = put(c, cid, registered_tags=["Prod", "dev", "prod"])
    assert r.status_code == 200 and CALLS == [{"registered-tags": "prod;dev"}] and r.json()["registered_tags"] == ["prod", "dev"]


def test_empty_registered_tags_removes_the_setting(api):
    c, cid = api
    ST["opts"]["registered-tags"] = "prod"
    r = put(c, cid, registered_tags=[])
    assert r.status_code == 200 and CALLS == [{"delete": "registered-tags"}] and r.json()["registered_tags"] == []


@pytest.mark.parametrize("tags", [["a b"], ["a;b"], ["a,b"], [""], ["é"], ["-a"], ["x" * 65], ["a=b"], [5], "prod", [f"t{i}" for i in range(101)]])
def test_registered_tags_invalid_refused_without_write(api, tags):
    c, cid = api
    assert put(c, cid, registered_tags=tags).status_code == 422 and not CALLS


# --- user-tag-access ------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("allow", ["none", "existing", "free"])
def test_user_tag_access_simple_modes_ignore_the_list(api, allow):
    c, cid = api
    r = put(c, cid, user_tag_access={"user_allow": allow, "user_allow_list": ["x"]})
    assert r.status_code == 200 and CALLS == [{"user-tag-access": f"user-allow={allow}"}]
    assert r.json()["user_tag_access"]["user_allow"] == allow


def test_user_tag_access_list_mode_needs_a_list_and_merges(api):
    c, cid = api
    assert put(c, cid, user_tag_access={"user_allow": "list"}).status_code == 422 and not CALLS
    assert put(c, cid, user_tag_access={"user_allow": "list", "user_allow_list": []}).status_code == 422 and not CALLS
    r = put(c, cid, user_tag_access={"user_allow": "list", "user_allow_list": ["Dev", "ops", "dev"]})
    assert r.status_code == 200 and CALLS[-1] == {"user-tag-access": "user-allow=list,user-allow-list=dev;ops"}
    assert put(c, cid, user_tag_access={"user_allow_list": ["qa"]}).status_code == 200            # mode gardé, liste remplacée
    assert CALLS[-1] == {"user-tag-access": "user-allow=list,user-allow-list=qa"}
    assert put(c, cid, user_tag_access={"user_allow": "none"}).status_code == 200
    assert CALLS[-1] == {"user-tag-access": "user-allow=none"}


def test_user_tag_access_mode_alone_keeps_the_current_list(api):
    c, cid = api
    ST["opts"]["user-tag-access"] = "user-allow=list,user-allow-list=a;b"
    r = put(c, cid, user_tag_access={"user_allow": "list"})                                       # liste non renvoyée : on garde celle de Proxmox
    assert r.status_code == 200 and CALLS == [{"user-tag-access": "user-allow=list,user-allow-list=a;b"}]


def test_user_tag_access_list_alone_without_a_mode_is_refused(api):
    c, cid = api
    assert put(c, cid, user_tag_access={"user_allow_list": ["qa"]}).status_code == 422 and not CALLS


@pytest.mark.parametrize("uta", [{"user_allow": "all"}, {"user_allow": "LIST"}, {"user_allow": "list", "user_allow_list": ["a b"]},
                                 {"user_allow": "list", "user_allow_list": ["a;b"]}, {"user_allow": "list", "user_allow_list": ["a,user-allow=free"]},
                                 {"user_allow": "list", "user_allow_list": [f"t{i}" for i in range(101)]}])
def test_user_tag_access_invalid_refused_without_write(api, uta):
    c, cid = api
    assert put(c, cid, user_tag_access=uta).status_code == 422 and not CALLS


# --- consent-text ---------------------------------------------------------------------------------------------------------------------------------------

def test_consent_text_written_with_newlines_and_read_back_without_the_trailing_one(api):
    c, cid = api
    ST["trailing"] = True                                                                    # Proxmox peut ajouter un saut de ligne final
    r = put(c, cid, consent_text=CONSENT)
    assert r.status_code == 200 and CALLS == [{"consent-text": CONSENT}]


def test_blank_consent_text_removes_the_setting(api):
    c, cid = api
    ST["opts"]["consent-text"] = CONSENT
    for blank in ("", "   \n"):
        ST["opts"]["consent-text"] = CONSENT
        CALLS.clear()
        assert put(c, cid, consent_text=blank).status_code == 200 and CALLS == [{"delete": "consent-text"}]


@pytest.mark.parametrize("text", ["x" * 3001, "a\x00b", "a\x1bb", "a\x7fb"])
def test_consent_text_invalid_refused_without_write(api, text):
    c, cid = api
    assert put(c, cid, consent_text=text).status_code == 422 and not CALLS


def test_consent_text_is_never_copied_to_the_audit_or_the_dry_run(api):
    c, cid = api
    r = put(c, cid, consent_text=CONSENT, dry_run=True)
    assert r.json()["params"] == {"consent-text": "défini"} and not CALLS
    assert put(c, cid, consent_text=CONSENT).status_code == 200
    log = c.get("/api/audit").text
    assert "datacenter-options" in log and "consent-text=défini" in log and "Accès réservé" not in log and SECRET not in log


# --- clear, retour, digest ------------------------------------------------------------------------------------------------------------------------------

def test_clear_uses_the_proxmox_names(api):
    c, cid = api
    ST["opts"].update({"registered-tags": "prod", "user-tag-access": "user-allow=none", "consent-text": CONSENT})
    r = put(c, cid, clear=["registered_tags", "user_tag_access", "consent_text"])
    assert r.status_code == 200 and CALLS == [{"delete": "registered-tags,user-tag-access,consent-text"}]
    j = get(c, cid)
    assert j["registered_tags"] == [] and j["user_tag_access"]["user_allow"] is None and j["consent_text"] is None
    assert put(c, cid, clear=["registered-tags"]).status_code == 422


def test_modified_and_cleared_at_once_is_refused(api):
    c, cid = api
    assert put(c, cid, registered_tags=["a"], clear=["registered_tags"]).status_code == 422
    assert put(c, cid, consent_text="x", clear=["consent_text"]).status_code == 422
    assert not CALLS


def test_proxmox_not_applying_is_a_502(api):
    c, cid = api
    ST["noapply"] = True
    assert put(c, cid, registered_tags=["a"]).status_code == 502
    assert put(c, cid, user_tag_access={"user_allow": "none"}).status_code == 502
    assert put(c, cid, consent_text="x").status_code == 502
    ST["opts"]["registered-tags"] = "a"
    assert put(c, cid, clear=["registered_tags"]).status_code == 502


def test_digest_covers_the_new_settings(api):
    c, cid = api
    d0 = get(c, cid)["digest"]
    ST["opts"]["registered-tags"] = "prod"
    assert get(c, cid)["digest"] != d0
    assert put(c, cid, registered_tags=["a"], digest=d0).status_code == 409 and not CALLS


def test_webauthn_is_still_never_written(api):
    c, cid = api
    ST["opts"]["webauthn"] = "rp=x,origin=https://x"
    r = put(c, cid, webauthn={"rp": "y"}, keyboard="fr")
    assert r.status_code == 200 and CALLS == [{"keyboard": "fr"}]
