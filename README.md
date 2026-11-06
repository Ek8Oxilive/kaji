# Kaji (舵)

Le gouvernail de ton homelab. Interface web moderne pour piloter un cluster Proxmox VE : supervision, création et gestion des VM/LXC, et paramétrage du cluster (stockage, sauvegardes, utilisateurs, réseau, firewall, HA).

**Statut : en développement (M1).** Voir [PLAN.md](PLAN.md) pour la feuille de route.

## Stack
FastAPI (Python) · React + Vite + Tailwind · SQLite · Docker Compose

## Démarrage (backend)
```bash
cp .env.example .env        # puis renseigner KAJI_SECRET_KEY
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```
Les connexions Proxmox (hôte, utilisateur, token API) sont saisies dans l'interface, jamais dans le `.env`.

## Licence
[MIT](LICENSE)
