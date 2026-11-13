"""Options du datacenter, suite (lot #237) : plage des identifiants libres (`next-id`) et style des étiquettes (`tag-style`).

Faux Proxmox STRICT : méthode, chemin et paramètres exacts ; les chaînes de propriétés sont validées par des motifs. RIEN n'a tourné sur un vrai cluster
au moment de l'écriture de ces tests : les formats viennent du schéma de `datacenter.cfg` de Proxmox VE (à confirmer en réel, voir la PR).
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.datacenterspec import parse_color_map, parse_next_id, parse_tag_style, shape_options
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PUT_KEYS = {"keyboard", "next-id", "tag-style", "delete"}
NEXT_ID = re.compile(r"(lower=[0-9]{3,9})?(,)?(upper=[0-9]{3,9})?")
TAG_STYLE = re.compile(r"(shape=(full|circle|dense|none)|ordering=(config|alphabetical)|case-sensitive=1|color-map=[A-Za-z0-9_][A-Za-z0-9_.+\-]{0,31}:[0-9a-f]{6}(:[0-9a-f]{6})?"
                       r"(;[A-Za-z0-9_][A-Za-z0-9_.+\-]{0,31}:[0-9a-f]{6}(:[0-9a-f]{6})?)*)(,(shape=\w+|ordering=\w+|case-sensitive=1|color-map=[^,]+))*")
CALLS: list[dict] = []
ST: dict = {}


def fresh():
    ST.clear()
    ST.update(opts={"keyboard": "fr", "ha": {"shutdown_policy": "migrate"}}, noapply=False, as_dict=False, uppercase=False)


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    if p != "/cluster/options":
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if request.method == "GET":
        o = dict(ST["opts"])
        if ST["as_dict"]:
            for k in ("next-id", "tag-style"):
                if isinstance(o.get(k), str):
                    o[k] = dict(x.partition("=")[::2] for x in o[k].split(",") if "=" in x)
        return httpx.Response(200, json={"data": o})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if request.method != "PUT" or set(body) - PUT_KEYS:
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(set(body) - PUT_KEYS)}"})
    if "next-id" in body and not (body["next-id"] and NEXT_ID.fullmatch(body["next-id"])):
        return httpx.Response(400, json={"data": None, "message": "next-id invalide"})
    if "tag-style" in body and not TAG_STYLE.fullmatch(body["tag-style"]):
        return httpx.Response(400, json={"data": None, "message": "tag-style invalide"})
    dl = [x for x in body.get("delete", "").split(",") if x]
    if set(dl) - {"next-id", "tag-style", "keyboard"}:
        return httpx.Response(400, json={"data": None, "message": "delete invalide"})
    CALLS.append(body)
    if not ST["noapply"]:
        for k, v in body.items():
            if k != "delete":
                ST["opts"][k] = re.sub(r":([0-9a-f]{6})", lambda m: ":" + m.group(1).upper(), v) if (ST["uppercase"] and k == "tag-style") else v
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

def test_reads_both_settings_from_strings_and_objects_and_they_are_no_longer_readonly(api):
    c, cid = api
    ST["opts"].update({"next-id": "lower=200,upper=900", "tag-style": "shape=dense,ordering=config,case-sensitive=1,color-map=prod:FF0000:ffffff;dev:00ff00"})
    for as_dict in (False, True):
        ST["as_dict"] = as_dict
        j = get(c, cid)
        assert j["next_id"] == {"lower": 200, "upper": 900}
        assert j["tag_style"] == {"shape": "dense", "ordering": "config", "case_sensitive": True,
                                  "color_map": [{"tag": "prod", "color": "ff0000", "text": "ffffff"}, {"tag": "dev", "color": "00ff00", "text": None}]}
        assert "next-id" not in j["readonly"] and "tag-style" not in j["readonly"] and j["readonly"] == {}


def test_absent_or_garbage_values_give_empty_structures():
    assert shape_options({})["next_id"] == {"lower": None, "upper": None}
    assert shape_options({"next-id": "lower=5,upper=abc"})["next_id"] == {"lower": None, "upper": None}                        # hors bornes ou illisible
    assert parse_next_id("lower=true") == {"lower": None, "upper": None}
    assert parse_tag_style(None) == {"shape": None, "ordering": None, "case_sensitive": None, "color_map": []}
    assert parse_tag_style("shape=bizarre,ordering=x")["shape"] is None
    assert parse_color_map("a:zzzzzz;b:ff0000:12;c:00ff00") == [{"tag": "c", "color": "00ff00", "text": None}]                # entrées mal formées écartées
    assert len(parse_color_map(";".join(f"t{i}:ff0000" for i in range(80)))) == 50


# --- next-id --------------------------------------------------------------------------------------------------------------------------------------------

def test_next_id_is_written_and_read_back(api):
    c, cid = api
    r = put(c, cid, next_id={"lower": 200, "upper": 900})
    assert r.status_code == 200 and CALLS == [{"next-id": "lower=200,upper=900"}] and r.json()["next_id"] == {"lower": 200, "upper": 900}


def test_next_id_merges_with_the_current_range(api):
    c, cid = api
    ST["opts"]["next-id"] = "lower=200,upper=900"
    assert put(c, cid, next_id={"lower": 300}).status_code == 200
    assert CALLS[-1] == {"next-id": "lower=300,upper=900"}
    assert put(c, cid, next_id={"upper": 5000}).status_code == 200
    assert CALLS[-1] == {"next-id": "lower=300,upper=5000"}


@pytest.mark.parametrize("nid", [{"lower": 99}, {"upper": 1_000_000_000}, {"lower": 500, "upper": 500}, {"lower": 900, "upper": 200}, {"lower": "200"}, {"lower": True}, {"lower": 200.5}])
def test_next_id_invalid_is_refused_without_any_write(api, nid):
    c, cid = api
    assert put(c, cid, next_id=nid).status_code == 422 and not CALLS


def test_next_id_merged_range_is_checked_too(api):
    c, cid = api
    ST["opts"]["next-id"] = "lower=200,upper=900"
    r = put(c, cid, next_id={"lower": 950})                                      # 950 >= 900 (valeur courante de upper)
    assert r.status_code == 422 and "inférieur" in r.json()["detail"] and not CALLS


# --- tag-style ------------------------------------------------------------------------------------------------------------------------------------------

def test_tag_style_is_written_with_exact_string(api):
    c, cid = api
    r = put(c, cid, tag_style={"shape": "full", "ordering": "config", "case_sensitive": True,
                               "color_map": [{"tag": "prod", "color": "FF0000", "text": "ffffff"}, {"tag": "dev", "color": "00ff00"}]})
    assert r.status_code == 200
    assert CALLS == [{"tag-style": "shape=full,ordering=config,case-sensitive=1,color-map=prod:ff0000:ffffff;dev:00ff00"}]
    assert r.json()["tag_style"]["color_map"][0] == {"tag": "prod", "color": "ff0000", "text": "ffffff"}


def test_tag_style_merges_subsettings_and_color_map_is_replaced_as_a_whole(api):
    c, cid = api
    ST["opts"]["tag-style"] = "shape=circle,color-map=a:111111"
    assert put(c, cid, tag_style={"ordering": "alphabetical"}).status_code == 200
    assert CALLS[-1] == {"tag-style": "shape=circle,ordering=alphabetical,color-map=a:111111"}              # forme et couleurs gardées
    assert put(c, cid, tag_style={"color_map": [{"tag": "b", "color": "222222"}]}).status_code == 200
    assert CALLS[-1] == {"tag-style": "shape=circle,ordering=alphabetical,color-map=b:222222"}               # table remplacée en entier
    assert put(c, cid, tag_style={"color_map": []}).status_code == 200
    assert CALLS[-1] == {"tag-style": "shape=circle,ordering=alphabetical"}                                   # table retirée, le reste intact
    assert put(c, cid, tag_style={"case_sensitive": True}).status_code == 200
    assert CALLS[-1] == {"tag-style": "shape=circle,ordering=alphabetical,case-sensitive=1"}
    assert put(c, cid, tag_style={"case_sensitive": False}).status_code == 200
    assert CALLS[-1] == {"tag-style": "shape=circle,ordering=alphabetical"}


@pytest.mark.parametrize("ts", [
    {"shape": "carre"}, {"ordering": "random"}, {"case_sensitive": "oui"}, {"case_sensitive": 1},
    {"color_map": [{"tag": "a b", "color": "ff0000"}]}, {"color_map": [{"tag": "a;b", "color": "ff0000"}]}, {"color_map": [{"tag": "a:b", "color": "ff0000"}]},
    {"color_map": [{"tag": "", "color": "ff0000"}]}, {"color_map": [{"tag": "x" * 33, "color": "ff0000"}]},
    {"color_map": [{"tag": "a", "color": "#ff0000"}]}, {"color_map": [{"tag": "a", "color": "ff00"}]}, {"color_map": [{"tag": "a", "color": "gg0000"}]},
    {"color_map": [{"tag": "a", "color": "ff0000", "text": "nope"}]},
    {"color_map": [{"tag": "a", "color": "ff0000"}, {"tag": "A", "color": "00ff00"}]},                    # doublon (insensible à la casse)
    {"color_map": [{"tag": f"t{i}", "color": "ff0000"} for i in range(51)]},
])
def test_tag_style_invalid_is_refused_without_any_write(api, ts):
    c, cid = api
    assert put(c, cid, tag_style=ts).status_code == 422 and not CALLS


def test_tag_style_color_map_entries_cannot_inject_other_properties(api):
    c, cid = api
    for tag in ("a,shape=none", "a=b", "x\ny", "é"):
        assert put(c, cid, tag_style={"color_map": [{"tag": tag, "color": "ff0000"}]}).status_code == 422
    assert not CALLS


# --- retrait, relecture, dry_run, digest, audit ---------------------------------------------------------------------------------------------------------

def test_clear_uses_the_proxmox_names(api):
    c, cid = api
    ST["opts"].update({"next-id": "lower=200,upper=900", "tag-style": "shape=full"})
    r = put(c, cid, clear=["next_id", "tag_style"])
    assert r.status_code == 200 and CALLS == [{"delete": "next-id,tag-style"}]
    j = get(c, cid)
    assert j["next_id"] == {"lower": None, "upper": None} and j["tag_style"]["shape"] is None
    assert put(c, cid, clear=["next-id"]).status_code == 422                          # le nom Proxmox n'est pas accepté côté Kaji


def test_removing_the_last_subsetting_removes_the_whole_setting(api):
    c, cid = api
    ST["opts"]["tag-style"] = "shape=full"
    assert put(c, cid, tag_style={"shape": "none"}).status_code == 200 and CALLS[-1] == {"tag-style": "shape=none"}
    ST["opts"]["tag-style"] = "case-sensitive=1"
    assert put(c, cid, tag_style={"case_sensitive": False}).status_code == 200
    assert CALLS[-1] == {"delete": "tag-style"} and get(c, cid)["tag_style"]["case_sensitive"] is None


def test_modified_and_cleared_at_once_is_refused(api):
    c, cid = api
    assert put(c, cid, next_id={"lower": 200}, clear=["next_id"]).status_code == 422 and not CALLS


def test_readback_tolerates_case_and_object_form(api):
    c, cid = api
    ST["uppercase"] = True                                                                  # Proxmox renvoie les couleurs en majuscules
    ST["as_dict"] = True
    assert put(c, cid, tag_style={"color_map": [{"tag": "prod", "color": "ff00aa"}]}).status_code == 200
    assert put(c, cid, next_id={"lower": 200, "upper": 900}).status_code == 200


def test_proxmox_not_applying_is_a_502(api):
    c, cid = api
    ST["noapply"] = True
    assert put(c, cid, next_id={"lower": 200}).status_code == 502
    assert put(c, cid, tag_style={"shape": "full"}).status_code == 502
    ST["opts"]["next-id"] = "lower=200"
    assert put(c, cid, clear=["next_id"]).status_code == 502                               # réglage qui reste en place


def test_dry_run_writes_nothing_and_shows_the_strings(api):
    c, cid = api
    r = put(c, cid, next_id={"lower": 200, "upper": 900}, tag_style={"shape": "dense"}, dry_run=True)
    assert r.status_code == 200 and r.json()["params"] == {"next-id": "lower=200,upper=900", "tag-style": "shape=dense"} and not CALLS


def test_digest_covers_the_new_settings_and_stale_digest_is_refused(api):
    c, cid = api
    d0 = get(c, cid)["digest"]
    ST["opts"]["next-id"] = "lower=200,upper=900"
    assert get(c, cid)["digest"] != d0
    assert put(c, cid, next_id={"lower": 300}, digest=d0).status_code == 409 and not CALLS


def test_unknown_subkeys_of_the_cluster_settings_are_ignored(api):
    c, cid = api
    r = put(c, cid, ha={"x": "freeze"}, crs={"x": "static"}, bwlimit={"x": 1}, replication={"x": 1}, keyboard="fr")
    assert r.status_code == 200 and CALLS == [{"keyboard": "fr"}]                      # seul le clavier est envoyé : aucune sous-clé reconnue (les réglages ont leur fichier : test_datacenter_cluster_settings.py)


def test_audit_records_without_leaking_the_secret(api):
    c, cid = api
    assert put(c, cid, next_id={"lower": 99}).status_code == 422
    assert put(c, cid, next_id={"lower": 200, "upper": 900}).status_code == 200
    log = c.get("/api/audit").text
    assert "datacenter-options" in log and "lower=200,upper=900" in log and SECRET not in log
