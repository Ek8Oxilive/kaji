# Kaji

Le gouvernail de ton homelab (« kaji » signifie gouvernail en japonais). Interface web moderne pour piloter un cluster Proxmox VE : supervision, création et gestion des VM/LXC, et paramétrage du cluster (stockage, sauvegardes, utilisateurs, réseau, firewall, HA).

**Statut : en développement (jalon M1).** La feuille de route complète est dans [PLAN.md](PLAN.md).

## Fonctionnement
- Au premier lancement, tu crées le compte admin du dashboard (mot de passe de 12 caractères minimum).
- Les clusters Proxmox s'ajoutent depuis l'interface (hôte, utilisateur, token API) : rien à mettre dans un fichier de configuration.
- Les tokens sont stockés **chiffrés** en base (Fernet, clé dérivée de `KAJI_SECRET_KEY`). Les mots de passe sont hachés en argon2id.
- Session par cookie HttpOnly / SameSite=Strict.

> **Sécurité :** Kaji détient un token Proxmox aux droits étendus. Ne l'expose pas sur Internet : réseau local ou VPN, derrière HTTPS. Crée le compte admin avant toute exposition réseau.

## Stack
FastAPI (Python) · SQLAlchemy / SQLite · React + Vite + Tailwind (à venir) · Docker Compose (à venir)

## Interface web
Deux thèmes commutables depuis l'en-tête (le choix est mémorisé dans le navigateur) : **Sombre** et **Glass**. Pour en ajouter un, il suffit de définir un jeu de variables CSS dans `frontend/src/index.css` et de l'inscrire dans `frontend/src/lib/theme.tsx`.

Pour l'essayer en local (Node 20+), après avoir lancé le backend :
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (les appels /api sont relayés vers le backend)
```
Écrans disponibles : première configuration, connexion, gestion des connexions Proxmox. Le dashboard des machines arrive à l'étape suivante du jalon M3.

## Démarrage (backend)
Prérequis : Python 3.12+.

```bash
git clone https://github.com/Ek8Oxilive/kaji.git && cd kaji
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # colle le résultat dans KAJI_SECRET_KEY
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```
La documentation interactive de l'API est sur http://127.0.0.1:8000/docs.

### API (jalon M1)
Toutes les routes, sauf `/api/health` et `/api/auth/*`, demandent une session.

| Route | Rôle |
|---|---|
| `POST /api/auth/setup` · `login` · `logout` · `GET /api/auth/me` | Compte admin et session |
| `GET/POST /api/connections` | Lister / ajouter un cluster Proxmox |
| `GET/PATCH/DELETE /api/connections/{id}` | Voir / modifier / supprimer (le token n'est jamais renvoyé) |
| `POST /api/connections/test` | Tester des identifiants avant de les enregistrer |
| `POST /api/connections/{id}/test` | Tester une connexion enregistrée |
| `GET /api/connections/{id}/cluster/status` | Nom du cluster, quorum, nœuds en ligne ou non |
| `GET /api/connections/{id}/nodes` | Nœuds : CPU, RAM, disque, uptime |
| `GET /api/connections/{id}/guests` | Liste unifiée des VM (qemu) et LXC, filtrable par `?node=` |
| `GET /api/connections/{id}/storages` | Stockages et usage |
| `POST /api/connections/{id}/guests/{node}/{qemu\|lxc}/{vmid}/{action}` | `start`, `shutdown`, `reboot`, `stop`. Renvoie l'UPID de la tâche. `stop` (coupure brutale) exige `{"confirm": true}`. |
| `GET /api/connections/{id}/tasks/{node}/{upid}` | État d'une tâche (`ok` si terminée avec succès) ; `/log` pour son journal |
| `GET /api/connections/{id}/guests/{node}/{type}/{vmid}/config` | Matériel décomposé (CPU, RAM, disques, cartes réseau) et changements en attente |
| `PATCH …/config` | Modifie CPU (cœurs, sockets, type), RAM, balloon, swap (LXC), réseau (bridge, VLAN, firewall ; la MAC est conservée), ISO monté ou éjecté. Seuls des champs validés sont acceptés. |
| `POST …/resize` | Agrandit un disque de N Go (irréversible, exige `{"confirm": true}`) |
| `GET /api/audit` | Journal d'audit des actions (qui, quoi, quand, résultat) |

> **Droits Proxmox (M2).** Les actions demandent plus que la lecture seule. Pour limiter les risques, donne le rôle `PVEVMAdmin` au token **uniquement sur les machines concernées** (`pveum aclmod /vms/<vmid> -user kaji@pve -role PVEVMAdmin`) et garde `PVEAuditor` sur `/`.

Côté Proxmox, crée un utilisateur et un token dédiés (`pveum user token add kaji@pve kaji --privsep 0`), puis saisis l'hôte, `kaji@pve`, l'ID `kaji` et le secret dans Kaji.

### Configuration (`.env`)
| Variable | Rôle | Défaut |
|---|---|---|
| `KAJI_SECRET_KEY` | Chiffrement des tokens et signature des sessions. **Obligatoire**, à garder secrète. Si tu la perds, les connexions enregistrées sont à ressaisir. | – |
| `KAJI_COOKIE_SECURE` | Cookie de session en `Secure`. Mettre `false` seulement en HTTP sur le réseau local. | `true` |
| `DATABASE_URL` | Base de données | `sqlite:///./kaji.db` |
| `KAJI_SESSION_HOURS` | Durée de session | `12` |

## Tests
```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

## Contribuer
- Une branche par fonctionnalité (`feat/...`, `fix/...`), une PR par bloc cohérent, aucun commit direct sur `main`.
- Messages de commit en [Conventional Commits](https://www.conventionalcommits.org/), avec le **jalon** de [PLAN.md](PLAN.md) et la zone en scope : `type(Mx/zone): message`.
  - Exemples : `feat(M2/actions): démarrer et arrêter une VM`, `fix(M1/auth): expiration du cookie`, `docs(M0): précise le démarrage`.
  - Types : `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`. Hors jalon (outillage, docs générales) : `chore(repo): ...`.
- Chaque PR est rattachée au **milestone GitHub** correspondant (M0 à M10).
- La CI (pytest) doit être verte avant merge.

## Licence
[MIT](LICENSE)
