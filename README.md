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
Écrans disponibles : première configuration, connexion, gestion des connexions Proxmox, et **dashboard** : résumé du cluster, nœuds (CPU, RAM, disque), machines VM/LXC en cartes avec filtres (recherche, état, type, nœud) et actions démarrer / redémarrer / éteindre / forcer l'arrêt. Les actions destructrices demandent confirmation, l'état attendu s'affiche tout de suite et la tâche Proxmox est suivie jusqu'au bout. Les données arrivent **en temps réel** (flux SSE, indicateur « En direct ») ; si le flux est indisponible, l'interface se rabat seule sur un rafraîchissement toutes les 10 s (cadence des statistiques Proxmox). **Ctrl+K** ouvre une palette de commandes : retrouver une machine et lui appliquer une action (les actions destructrices demandent toujours confirmation), changer de thème, aller aux connexions.

**Panneau Matériel** (bouton « Matériel » sur chaque machine) : mémoire, processeurs, swap (LXC), disques (agrandissement), lecteurs CD/DVD (monter/éjecter un ISO) et cartes réseau (bridge ou VNet SDN choisi dans une liste, VLAN, firewall, MAC conservée). L'ISO se choisit dans la liste des images du nœud ; si une liste est indisponible, la saisie manuelle reste possible. Le bouton **« + Nouvelle machine »** (ou la palette Ctrl+K) propose une **VM** ou un **conteneur LXC** ; l'**assistant de création de VM** compte 4 étapes : général (nœud, nom, identifiant proposé, pool, système), matériel (cœurs, mémoire, disque et stockage, ISO), réseau (bridge ou VNet, VLAN, firewall) et récapitulatif. Windows 11 reçoit automatiquement UEFI, TPM et disque EFI. L'assistant prévient quand aucun pool n'est choisi. Un onglet **Snapshots** permet de créer, supprimer et restaurer des points de restauration (la restauration exige de retaper le nom de la machine). Le bouton **« Cloner »** (sur chaque carte, y compris les modèles) copie une machine : clone complet ou lié, vers le même nœud ou un autre. Une ligne **« Emplacement »** permet de **migrer** la machine vers un autre nœud, après les vérifications préalables de Proxmox. Une **zone dangereuse** en bas du panneau Matériel permet de supprimer une machine arrêtée : la fenêtre liste les disques détruits et exige de retaper le nom. Pour une VM, un onglet **Cloud-init** règle l'utilisateur, le mot de passe, les clés SSH, l'IP et le DNS, et ajoute ou retire le lecteur cloud-init. Les disques s'**ajoutent, se détachent (données conservées), se rattachent, se déplacent et se suppriment définitivement** (en retapant le nom de la machine). On peut aussi **ajouter ou retirer une carte réseau** et régler l'**ordre de démarrage** d'une VM. Les changements qui ne s'appliquent qu'au redémarrage sont signalés « en attente ». L'ajout/suppression de disques et de cartes réseau est prévu dans une étape suivante.

## Déploiement
`docker compose up -d --build` lance le backend et le frontend (nginx). Guide complet, HTTPS, sauvegarde, mise à jour et mot de passe perdu : [docs/deploiement.md](docs/deploiement.md).

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
| `POST /api/auth/setup` · `login` · `logout` · `GET /api/auth/me` | Compte admin et session. `logout` **révoque** la session côté serveur. |
| `POST /api/auth/logout-all` | Révoque toutes les sessions du compte |
| `POST /api/auth/password` | Change le mot de passe (l'actuel est exigé) ; révoque les autres sessions |
| `GET/POST /api/connections` | Lister / ajouter un cluster Proxmox |
| `GET/PATCH/DELETE /api/connections/{id}` | Voir / modifier / supprimer (le token n'est jamais renvoyé) |
| `POST /api/connections/test` | Tester des identifiants avant de les enregistrer |
| `POST /api/connections/{id}/test` | Tester une connexion enregistrée |
| `GET /api/connections/{id}/cluster/status` | Nom du cluster, quorum, nœuds en ligne ou non |
| `GET /api/connections/{id}/nodes` | Nœuds : CPU, RAM, disque, uptime |
| `GET /api/connections/{id}/guests` | Liste unifiée des VM (qemu) et LXC, filtrable par `?node=` |
| `GET /api/connections/{id}/storages` | Stockages et usage |
| `GET /api/connections/{id}/events` | Flux temps réel (SSE) : un instantané de l'état du cluster (statut, nœuds, machines) à chaque changement. Un seul interrogateur Proxmox par cluster, partagé par tous les navigateurs ; il s'arrête quand le dernier part. |
| `POST /api/connections/{id}/guests/{node}/{qemu\|lxc}/{vmid}/{action}` | `start`, `shutdown`, `reboot`, `stop`. Renvoie l'UPID de la tâche. `stop` (coupure brutale) exige `{"confirm": true}`. |
| `GET /api/connections/{id}/tasks/{node}/{upid}` | État d'une tâche (`ok` si terminée avec succès) ; `/log` pour son journal |
| `GET /api/connections/{id}/guests/{node}/{type}/{vmid}/config` | Matériel décomposé (CPU, RAM, disques, cartes réseau) et changements en attente |
| `PATCH …/config` | Modifie CPU (cœurs, sockets, type), RAM, balloon, swap (LXC), réseau (bridge, VLAN, firewall ; la MAC est conservée), ISO monté ou éjecté. Seuls des champs validés sont acceptés. |
| `POST …/guests/{node}/{type}/{vmid}/nets` · `DELETE …/nets/{netN}?confirm=true` | Ajouter une carte réseau (index libre choisi, MAC attribuée par Proxmox, IP DHCP/statique pour un LXC) / la retirer (la MAC est perdue, confirmation exigée) |
| `PATCH …/config` avec `boot` | Ordre de démarrage d'une VM (`["scsi0","ide2","net0"]`) |
| `POST …/guests/{node}/{type}/{vmid}/disks` | Ajoute un disque (VM : bus et stockage ; LXC : point de montage avec chemin validé) |
| `POST …/disks/{key}/detach` | Détache un disque : il devient « non utilisé », **données conservées** |
| `POST …/disks/unusedN/reattach` | Rattache un disque non utilisé |
| `DELETE …/disks/unusedN?confirm=true&name=<machine>` | Détruit **définitivement** un disque non utilisé ; exige le nom exact de la machine |
| `POST …/disks/{key}/move` | Déplace un disque vers un autre stockage (`confirm` exigé, ancien emplacement conservé sauf `delete_source`) |
| `POST …/guests/{node}/{type}/{vmid}/clone` | Clone une VM ou un LXC (complet, ou lié si la source est un modèle) ; nom, identifiant (libre par défaut), nœud et stockage de destination, pool |
| `DELETE …/guests/{node}/{type}/{vmid}?confirm=true&name=<machine>` | Supprime **définitivement** une machine et ses disques. Exige : machine arrêtée, nom exact, non protégée (par Proxmox ni par `KAJI_PROTECTED_VMIDS`). Options `purge`, `destroy_unreferenced`. |
| `GET …/guests/{node}/{type}/{vmid}/migrate` | Vérifications préalables de Proxmox : nœuds possibles, disques locaux, ressources bloquantes (repli sur les nœuds en ligne si indisponibles) |
| `POST …/guests/{node}/{type}/{vmid}/migrate` | Migre la machine vers un autre nœud ; une machine en marche exige `confirm` (VM : à chaud ; LXC : arrêt, migration, redémarrage) |
| `POST …/resize` | Agrandit un disque de N Go (irréversible, exige `{"confirm": true}`) |
| `GET\|POST …/guests/{node}/{type}/{vmid}/snapshots` | Lister / créer un snapshot (avec la mémoire pour une VM en marche) |
| `DELETE …/snapshots/{name}?confirm=true` | Supprimer un snapshot (confirmation exigée) |
| `POST …/snapshots/{name}/rollback` | Restaurer la machine à ce snapshot, exige `{"confirm": true}` (tout ce qui a changé depuis est perdu) |
| `GET /api/connections/{id}/nodes/{node}/bridges` | Réseaux sélectionnables pour une carte réseau : bridges locaux et VNets SDN (la liste reste utilisable si le SDN est absent ou illisible) |
| `POST /api/connections/{id}/nodes/{node}/qemu` | Crée une VM (nom, mémoire, CPU, disque, réseau, ISO, pool, type d'OS ; Windows 11 reçoit UEFI, TPM et disque EFI). Chaque champ est validé ; l'identifiant est choisi automatiquement si absent. |
| `POST /api/connections/{id}/nodes/{node}/lxc` | Crée un conteneur LXC depuis un modèle déjà présent (non privilégié par défaut). Mot de passe root et clés SSH facultatifs : **jamais journalisés**, jamais renvoyés. |
| `GET\|PATCH …/guests/{node}/qemu/{vmid}/cloudinit` | Cloud-init d'une VM : utilisateur, mot de passe (**jamais relu ni journalisé**), clés SSH (envoyées encodées en URL comme l'exige Proxmox), IP, DNS, domaine ; `clear` supprime des réglages |
| `POST\|DELETE …/cloudinit/drive` | Ajoute (bus IDE libre) ou retire le lecteur cloud-init, sans toucher aux réglages |
| `GET /api/connections/{id}/nextid` · `/pools` · `/nodes/{node}/storages?content=` | Prochain identifiant libre, pools, stockages d'un nœud acceptant un type de contenu |
| `GET /api/connections/{id}/nodes/{node}/templates` | Modèles de conteneur : déjà présents sur les stockages du nœud, et catalogue téléchargeable (avec l'architecture) |
| `GET /api/connections/{id}/nodes/{node}/isos` | Images ISO disponibles sur les stockages actifs du nœud |
| `GET /api/audit` | Journal d'audit des actions (qui, quoi, quand, résultat) |

> **Droits Proxmox (M2).** Les actions demandent plus que la lecture seule. Pour limiter les risques, donne le rôle `PVEVMAdmin` au token **uniquement sur les machines concernées** (`pveum aclmod /vms/<vmid> -user kaji@pve -role PVEVMAdmin`) et garde `PVEAuditor` sur `/`.

Côté Proxmox, crée un utilisateur et un token dédiés (`pveum user token add kaji@pve kaji --privsep 0`), puis saisis l'hôte, `kaji@pve`, l'ID `kaji` et le secret dans Kaji.

### Configuration (`.env`)
| Variable | Rôle | Défaut |
|---|---|---|
| `KAJI_SECRET_KEY` | Chiffrement des tokens et signature des sessions. **Obligatoire**, à garder secrète. Si tu la perds, les connexions enregistrées sont à ressaisir. | – |
| `KAJI_COOKIE_SECURE` | Cookie de session en `Secure`. Mettre `false` seulement en HTTP sur le réseau local. | `true` |
| `KAJI_TRUST_PROXY` | Derrière un reverse proxy **de confiance** uniquement : le limiteur de connexions utilise l'IP ajoutée par le proxy (`X-Forwarded-For`). Sinon l'en-tête est ignoré, car falsifiable. | `false` |
| `KAJI_AUDIT_RETENTION_DAYS` | Durée de conservation de l'audit ; les entrées plus anciennes sont supprimées (0 = indéfiniment) | `365` |
| `KAJI_PROTECTED_VMIDS` | Identifiants de machines que Kaji refuse de supprimer, quoi qu'il arrive (ex. `105,108`). **Recommandé** pour tes machines importantes. | vide |
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

Le bouton **« Compte »** (bas de la barre latérale) ouvre une fenêtre pour **changer le mot de passe** (l'actuel est exigé, 12 caractères minimum) et **déconnecter toutes les sessions**.

## Durcissement
- **Sessions révocables** : chaque jeton renvoie à une session enregistrée en base ; la déconnexion, le changement de mot de passe et `logout-all` les suppriment, un jeton copié devient donc inutilisable.
- **Base SQLite en `600`** (hash du mot de passe, tokens chiffrés, audit) : créée ainsi, ou resserrée au démarrage.
- **Audit purgé** au-delà de `KAJI_AUDIT_RETENTION_DAYS`.
- **En-têtes** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, et `Cache-Control: no-store` sur toute l'API.
- Dépendances **à version fixée**, mises à jour par Dependabot.
- **Migrations de schéma** : versionnées, **sauvegardées** (copie `kaji.db.bak-vN-…` en `600` avant toute migration, les 5 dernières sont gardées), **atomiques** (une transaction par migration, schéma compris) ; Kaji refuse de démarrer sur une base plus récente que le code. `python -m app.migrations status` (ou `upgrade`) depuis `backend/`.
- Non couvert : l'authentification à deux facteurs, la récupération d'un mot de passe oublié (supprimer `kaji.db` recrée le compte, mais efface aussi les connexions).

## Sécurité des secrets
Les erreurs de validation de l'API **ne renvoient jamais les valeurs saisies** (mots de passe, secrets de token) : par défaut FastAPI recopie le corps de la requête dans l'erreur, ce que Kaji désactive. Les mots de passe de conteneur ne sont ni journalisés ni écrits dans l'audit.
