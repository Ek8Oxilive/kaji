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
- Messages de commit en [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`).
- La CI (pytest) doit être verte avant merge.

## Licence
[MIT](LICENSE)
