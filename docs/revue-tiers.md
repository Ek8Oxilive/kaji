# Dossier pour la relecture de sécurité et le test d'intrusion (jalon J3, tickets #449 à #451)

À donner à la personne qui relit Kaji ou l'attaque. Il dit **quoi regarder, comment monter une cible jetable, ce qui est déjà connu et ce qui est hors cadre**. Lis `docs/securite.md` (revue interne et points ouverts) avec ce fichier.

## 1. Ce qu'est Kaji, en cinq lignes
Interface web (FastAPI + React, SQLite) qui pilote un cluster **Proxmox VE** à la place de son interface. Un compromis de Kaji est donc, selon la configuration, un compromis de Proxmox (jeton partagé, jetons personnels, session administrateur). Déployé par Docker Compose : `backend` (non root, non publié), `web` (nginx), `tls` (Caddy, facultatif). Carte du code : `docs/CARTE.md`. Routes : `backend/tests/routes_manifest.txt` (≈ 370).

## 2. Monter une cible jetable (15 min, aucune donnée réelle)
```
git clone <dépôt> kaji && cd kaji
printf 'KAJI_SECRET_KEY=%s\nKAJI_COOKIE_SECURE=false\n' "$(openssl rand -hex 24)" > .env
docker compose up -d --build --wait            # http://127.0.0.1:8080
curl -s -X POST http://127.0.0.1:8080/api/auth/setup -H 'content-type: application/json' -d '{"username":"admin","password":"un-mot-de-passe-de-test-12"}'
```
- **Faux Proxmox** (pour tester ce que Kaji envoie à Proxmox sans en avoir un) : `tools/fake_proxmox.py` (HTTPS, n'importe quel jeton est accepté) ; mode d'emploi en tête du fichier. **Ce n'est pas Proxmox** : les failles côté Proxmox sont hors cadre.
- **HTTPS** : `docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build` (`KAJI_TLS_SITE`, `KAJI_TLS_NAME`, `KAJI_COOKIE_SECURE=true`). Caddy répond 200 vide à tout autre nom d'hôte que ces deux-là.
- **Un vrai Proxmox** n'est utile que pour tester le jeton personnel et la session administrateur : à créer **par vous**, jamais sur le cluster de production du propriétaire.
- **Essais automatiques déjà écrits** : `tools/essai_docker.sh sonde` (sonde de sécurité, section 5), `chiffre-https`, `sauvegarde`, `mise-a-jour`.

## 3. Où regarder en priorité
| Zone | Fichiers | Questions |
|---|---|---|
| Authentification et sessions | `app/security.py`, `app/routers/auth.py` | Jeton signé relié à une ligne en base (`jti`), cookie HttpOnly / SameSite=Strict / Secure, limiteur persistant (`login_failures`), setup rejouable ? énumération de comptes ? |
| Rôles et périmètres | `app/roles.py`, `app/scope.py`, `app/deps.py` | Une route peut-elle échapper à la politique ? (un test les passe toutes en revue, mais cherchez : méthodes inhabituelles, chemins encodés, WebSocket, SSE) |
| Secrets au repos | `app/crypto.py`, `app/tokenkey.py`, `app/secretrotate.py`, `app/backup.py` | Fernet, deux clés (`KAJI_SECRET_KEY`, `KAJI_TOKEN_KEY`), rotation, la base seule ne doit pas livrer un jeton |
| Jetons Proxmox | `app/deps.py`, `app/routers/user_tokens.py`, `service_tokens.py` | Cloisonnement par utilisateur (flux temps réel compris), expiration, repli sur le jeton partagé |
| Session administrateur Proxmox | `app/adminsession.py` | En mémoire, 30 min, mot de passe jamais gardé |
| Consoles (WebSocket) | `app/routers/console.py`, `app/consolespec.py` | `Origin`, identifiant à usage unique, nombre limité, ticket Proxmox jamais renvoyé |
| SSO (OIDC) et annuaire (LDAP / AD) | `app/oidc.py`, `app/ldaplogin.py` | PKCE, état, nonce, signature de l'ID token, liaison `(émetteur, sub)`, injection de filtre LDAP, groupes → rôles |
| Webhooks et connexions | `app/routers/alerts.py`, `app/routers/connections.py` | SSRF : seules la boucle locale, le lien local et les adresses réservées sont refusés (voir « connu ») |
| Export de l'audit | `app/auditexport.py` | Injection de lignes, secrets, syslog |
| Déploiement | `docker-compose*.yml`, `deploy/`, `backend/Dockerfile`, `frontend/` | Ports publiés, utilisateur du conteneur, en-têtes nginx / Caddy |
| Chaîne de livraison | `.github/workflows/`, `tools/verify_release.sh`, `docs/signature.md`, `docs/sbom.md` | Signature sans clé (Sigstore), SBOM, épinglage des images |

## 4. Connu et assumé (inutile de le signaler comme nouveau, mais dites si vous n'êtes pas d'accord)
- **Jeton partagé** : par défaut, tous les utilisateurs agissent sous le même jeton Proxmox (option A du cadrage : jetons personnels, essai réel à faire).
- **`KAJI_ADMIN_USE_KAJI_TOKEN`** : si activé et que le jeton a `Administrator`, compromettre Kaji = compromettre Proxmox.
- **Pas de jeton CSRF** : `SameSite=Strict` + corps JSON obligatoire (la sonde teste `text/plain` et formulaire).
- **TOTP de connexion facultatif**, SSO et LDAP jamais essayés sur un vrai fournisseur OIDC ; LDAP essayé sur un AD de test.
- **Adresse d'une connexion Proxmox et webhooks libres** pour un administrateur (SSRF vers le réseau local possible par un administrateur de Kaji).
- **Un seul worker** (planificateur) : ne pas lancer deux instances.
- **Lecture du journal d'audit réservée aux administrateurs** (décision du propriétaire du 2026-11-17, #451) : lecteur et opérateur reçoivent 403 sur `/api/audit` ; la sonde doit désormais le constater.
- **Session déjà ouverte** après désactivation d'un compte SSO : elle vit jusqu'à son expiration (12 h).

## 5. Ce que la sonde automatique a déjà vérifié (2026-11-16, installation Docker neuve)
`tools/sonde_securite.py` (lancée par `tools/essai_docker.sh sonde`) : routes protégées sans session (401), schéma d'API non exposé, première configuration non rejouable, en-têtes (CSP sans script en ligne, `X-Frame-Options`, `nosniff`, `no-store`), pas d'énumération de comptes, cookie `HttpOnly` + `SameSite=Strict`, refus d'un lecteur et d'un opérateur sur la gestion des comptes et des connexions, POST `text/plain` et formulaire refusés, entrées hostiles (JSON cassé, types inattendus, traversée de chemin, entier géant, corps de 6 Mo) sans 500 ni trace de pile, cookie inutilisable après déconnexion, cookie falsifié, blocage après des échecs répétés.
**Défaut trouvé et corrigé par cette sonde** : un identifiant numérique géant dans une adresse (`/api/connections/99999999999999999999`) donnait un 500 (`OverflowError` SQLite) ; il répond maintenant 422 (`tests/test_overflow.py`).
**Limites** : une seule instance, HTTP seulement, faux Proxmox, aucune attaque sur WebSocket, SSO, LDAP ni sur les en-têtes `Host` / `X-Forwarded-*`. **Ce n'est pas un test d'intrusion.**

## 6. Règles du jeu proposées
- **Cible** : uniquement l'installation jetable que vous montez. **Jamais** le Kaji ni le cluster Proxmox du propriétaire.
- **Hors cadre** : Proxmox lui-même, déni de service volumique, ingénierie sociale, GitHub et ses actions (sauf lecture des fichiers de workflows).
- **Livrables attendus** : rapport (constat, gravité, preuve reproductible, correctif proposé) ; confidentialité jusqu'à correction ; signalement par le canal de `SECURITY.md` (signalement privé GitHub).
- **Sortie du jalon** (#449 à #451) : rapport archivé dans `docs/` (sans secret), **aucun constat ouvert de gravité moyenne ou plus**, les autres notés dans `docs/securite.md`.

## 7. Ce que le propriétaire doit fournir
Une personne tierce (compétente en sécurité web), une date, et ce dossier. L'agent corrige les constats et ajoute un test de non-régression par constat.
