#!/usr/bin/env python3
"""Sonde de sécurité de Kaji (jalon J3, préparation de la relecture et du test d'intrusion #449 à #451). NE REMPLACE PAS un test d'intrusion par un tiers.

    python3 -I tools/sonde_securite.py http://127.0.0.1:18080 ADMIN MOT_DE_PASSE

À lancer sur une installation JETABLE (`tools/essai_docker.sh sonde`) : elle crée des comptes, enchaîne des échecs de connexion (blocage de l'adresse), puis les supprime.
Chaque contrôle affiche OK ou ÉCHEC ; le code de sortie est 1 s'il y a au moins un ÉCHEC. Bibliothèque standard seulement.
"""
import http.client
import json
import sys
import urllib.parse

BASE, ADMIN, PASSWORD = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
U = urllib.parse.urlparse(BASE)
FAILS: list[str] = []


def call(method, path, body=None, cookie=None, headers=None, raw=None, ctype="application/json"):
    conn = http.client.HTTPSConnection(U.hostname, U.port, timeout=15) if U.scheme == "https" else http.client.HTTPConnection(U.hostname, U.port, timeout=15)
    h = dict(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h.setdefault("Content-Type", ctype)
    if cookie:
        h["Cookie"] = cookie
    conn.request(method, path, body=data, headers=h)
    r = conn.getresponse()
    text = r.read().decode("utf-8", "replace")
    out = (r.status, text, {k.lower(): v for k, v in r.getheaders()})
    conn.close()
    return out


def check(name, cond, detail=""):
    print(("OK    " if cond else "ÉCHEC ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        FAILS.append(name)


def login(user, pw):
    s, t, h = call("POST", "/api/auth/login", {"username": user, "password": pw})
    sc = h.get("set-cookie", "")
    return s, t, sc.split(";")[0] if sc else None


def main():
    # 1. Sans session : tout est refusé (sauf santé, état, première configuration, connexion)
    for m, p in [("GET", "/api/connections"), ("GET", "/api/kaji-users"), ("GET", "/api/audit"), ("POST", "/api/kaji-users"), ("GET", "/api/connections/1/nodes")]:
        s, _, _ = call(m, p, {} if m == "POST" else None)
        check(f"sans session : {m} {p} refusé", s in (401, 403, 404, 405), s)
    for p in ("/docs", "/redoc", "/openapi.json", "/api/docs", "/api/openapi.json"):
        s, t, _ = call("GET", p)
        check(f"schéma de l'API non exposé sans session : {p}", not (s == 200 and ("openapi" in t[:300].lower() or "swagger" in t.lower())), s)

    # 2. La première configuration ne se rejoue pas
    s, _, _ = call("POST", "/api/auth/setup", {"username": "intrus", "password": "un-mot-de-passe-de-intrus-1"})
    check("première configuration impossible une fois le compte créé", s in (400, 403, 409), s)

    # 3. En-têtes
    s, _, h = call("GET", "/")
    csp = h.get("content-security-policy", "")
    check("X-Frame-Options DENY", h.get("x-frame-options", "").upper() == "DENY", h.get("x-frame-options"))
    check("CSP sans script en ligne", "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0], csp)
    check("nosniff", h.get("x-content-type-options", "").lower() == "nosniff", h.get("x-content-type-options"))
    s, _, h = call("GET", "/api/health")
    check("API : Cache-Control no-store", "no-store" in h.get("cache-control", ""), h.get("cache-control"))
    check("pas de version de serveur détaillée", not any(c.isdigit() for c in h.get("server", "")), h.get("server"))

    # 4. Connexion : pas d'énumération, cookie bien posé
    s1, t1, _ = login(ADMIN, "mauvais-mot-de-passe-1")
    s2, t2, _ = login("n-existe-pas-du-tout", "mauvais-mot-de-passe-1")
    check("même réponse pour un compte inconnu et un mauvais mot de passe", (s1, t1) == (s2, t2), f"{s1} {t1[:60]} / {s2} {t2[:60]}")
    s, t, cookie = login(ADMIN, PASSWORD)
    check("connexion administrateur", s == 200 and cookie, s)
    s, _, h = call("POST", "/api/auth/login", {"username": ADMIN, "password": PASSWORD})
    sc = h.get("set-cookie", "").lower()
    check("cookie de session HttpOnly + SameSite=Strict", "httponly" in sc and "samesite=strict" in sc, sc)

    # 5. Rôles : un lecteur et un opérateur ne font rien d'administratif
    for role in ("viewer", "operator"):
        name = f"sonde-{role}"
        pw = "un-mot-de-passe-de-sonde-12"
        s, _, _ = call("POST", "/api/kaji-users", {"username": name, "password": pw, "role": role}, cookie=cookie)
        check(f"création du compte {name}", s == 201, s)
        _, _, ck = login(name, pw)
        check(f"connexion {name}", bool(ck))
        if not ck:
            continue
        for m, p, b in [("POST", "/api/kaji-users", {"username": "x-sonde-1", "password": pw, "role": "admin"}),
                        ("GET", "/api/kaji-users", None),
                        ("POST", "/api/connections", {"name": "x", "host": "10.9.9.9", "user": "a@pve", "token_id": "t", "token_secret": "s"})]:
            s, _, _ = call(m, p, b, cookie=ck)
            check(f"{role} refusé : {m} {p}", s in (401, 403, 404), s)
        s, _, _ = call("GET", "/api/audit", cookie=ck)
        print(f"INFO  {role} lit le journal d'audit : {'OUI (décision du propriétaire à prendre, docs/revue-tiers.md)' if s == 200 else 'non'}")
        s, _, _ = call("PATCH", "/api/kaji-users/1", {"role": "admin"}, cookie=ck)
        check(f"{role} ne change pas un rôle", s in (401, 403, 404, 405), s)

    # 6. Requêtes inter-sites : un corps JSON envoyé avec un autre type de contenu est refusé
    s, _, _ = call("POST", "/api/kaji-users", raw=json.dumps({"username": "csrf-sonde", "password": "un-mot-de-passe-de-sonde-12", "role": "viewer"}).encode(),
                   ctype="text/plain", cookie=cookie, headers={"Origin": "https://evil.example"})
    check("POST text/plain refusé (pas de CSRF par formulaire)", s in (400, 415, 422), s)
    s, _, _ = call("POST", "/api/kaji-users", raw=b"username=csrf&password=un-mot-de-passe-de-sonde-12&role=viewer",
                   ctype="application/x-www-form-urlencoded", cookie=cookie, headers={"Origin": "https://evil.example"})
    check("POST formulaire refusé", s in (400, 415, 422), s)

    # 7. Entrées hostiles : pas d'erreur 500, pas de trace de pile
    hostile = [("POST", "/api/auth/login", b"{"), ("POST", "/api/auth/login", b'{"username": ["x"], "password": 1}'), ("GET", "/api/connections/../../etc/passwd", None),
               ("GET", "/api/connections/99999999999999999999/nodes", None), ("GET", "/assets/../../etc/passwd", None), ("GET", "/%2e%2e/%2e%2e/etc/passwd", None)]
    for m, p, raw in hostile:
        s, t, _ = call(m, p, raw=raw, cookie=cookie)
        check(f"entrée hostile sans 500 ni trace : {m} {p[:40]}", s < 500 and "Traceback" not in t and "root:x:" not in t, f"{s} {t[:80]}")
    s, _, _ = call("POST", "/api/auth/login", raw=b"x" * (6 * 1024 * 1024))
    check("corps de 6 Mo refusé sans 500", s in (400, 411, 413, 415, 422), s)

    # 8. Déconnexion : le cookie ne sert plus
    s, _, ck2 = login(ADMIN, PASSWORD)
    s, _, _ = call("GET", "/api/auth/me", cookie=ck2)
    check("session valide avant déconnexion", s == 200, s)
    call("POST", "/api/auth/logout", cookie=ck2)
    s, _, _ = call("GET", "/api/auth/me", cookie=ck2)
    check("ancien cookie refusé après déconnexion", s == 401, s)
    s, _, _ = call("GET", "/api/auth/me", cookie="kaji_session=" + "a" * 60)
    check("cookie falsifié refusé", s == 401, s)

    # Nettoyage AVANT le test du limiteur (qui bloque l'adresse)
    s, t, _ = call("GET", "/api/kaji-users", cookie=cookie)
    try:
        users = json.loads(t)
    except Exception:
        users = []
    for name in ("sonde-viewer", "sonde-operator"):
        uid = next((u["id"] for u in users if u["username"] == name), None)
        if uid is not None and name != "sonde-viewer":
            call("DELETE", f"/api/kaji-users/{uid}?confirm=true&name={name}", cookie=cookie)

    # 9. Limiteur : 5 échecs puis blocage (même avec le bon mot de passe) ; en dernier
    codes = [login("sonde-viewer", "mauvais-mot-de-passe-1")[0] for _ in range(7)]
    check("blocage après des échecs répétés (429)", 429 in codes, codes)
    s, _, _ = login("sonde-viewer", "un-mot-de-passe-de-sonde-12")
    check("le bon mot de passe est lui aussi bloqué pendant la fenêtre", s == 429, s)
    print(f"\n{len(FAILS)} échec(s)  (le compte sonde-viewer reste : installation jetable, ne pas lancer sur une vraie)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
