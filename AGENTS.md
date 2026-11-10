# Règles pour les agents (Claude Code ou autre) travaillant sur Kaji

Kaji est une interface web pour piloter un cluster Proxmox VE (backend FastAPI, frontend React). Plusieurs agents
peuvent travailler en parallèle ; **le dépôt est le seul canal de coordination**. Lis ce fichier en entier avant de coder.

## 0. Qui est qui
| Agent | Étiquette | Rôle |
|---|---|---|
| **PC A** | `agent:pc-a` | Valide en réel sur le cluster (lecture seule, ou écritures réversibles avec l'accord du propriétaire) et relit les PR des autres. Lots qui exigent le cluster. |
| **PC B** | `agent:pc-b` | Développe avec le faux Proxmox **et valide aussi en réel**, dans les mêmes limites que PC A (règle d'Enzo du 2026-11-10, voir §2). Lots codables sans le cluster en priorité (voir `docs/REPRISE.md`). |

Si le propriétaire ne t'a pas dit lequel tu es, **demande-le avant de commencer**. Un agent ne prend jamais un ticket déjà pris
par l'autre (commentaire « je prends » ou label de l'autre agent).

## 1. Comment on travaille
- **Un ticket = un lot de travail** (GitHub Issues, rattaché à un milestone). Avant de commencer : commente « je prends »
  et pose ton label `agent:…`. Ne touche pas à un ticket pris par un autre agent.
- **Une branche par lot**, partie de `main` à jour : `feat/m5-stockage-lecture`, `fix/…`, `docs/…`.
- **Jamais de commit direct sur `main`** (protégée). Une PR par lot, **rattachée au milestone**, avec la CI verte.
- **Commits** : `type(Mx/zone): message` (`feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`),
  terminés par la ligne `Co-Authored-By:` de ton modèle.
- **Autonomie (règle d'Enzo, 2026-11-10) : PC A et PC B font la même chose, en boucle, jusqu'à ce qu'Enzo les arrête.** Un lot = ticket (« je prends » d'abord) → branche → code + faux Proxmox → tests (et mutations) → carte + manifeste des routes → PR → CI verte → **tu merges toi-même** (`gh pr merge N --merge`) → tu redéploies (console du CT 116, commande de `docs/REPRISE.md`) → **tu testes dans l'interface web déployée** (chaque page, bouton et fenêtre du lot, lecture seule ou écritures réversibles dans le bac à sable) → tu vérifies que **rien n'a disparu** (`test_routes_manifest`, `git diff` des suppressions, pages et boutons existants) → **captures du README** de ce qui est nouveau, y compris ce que l'autre agent a ajouté (`REPRISE.md` étape 7) → lot suivant, sans attendre.
- Toutes les PR partent du même compte GitHub, personne ne peut « approuver » : la vérification est une vraie relecture du code et des tests, à faire avant de merger (y compris pour les PR de l'autre agent, que tu peux relire et merger).
- **Avant de demander une revue** : fusionne `main` dans ta branche et résous les conflits toi-même.
- **Carte du projet** : régénère `docs/CARTE.md` (`python3 tools/carte.py > docs/CARTE.md`) avant chaque PR, et après avoir fusionné `main` (un test le vérifie). Mets aussi à jour la section « État » de `docs/REPRISE.md` si ton lot change l'état du projet.
- **PR honnête** : liste précisément ce qui n'est **pas** testé (en réel, ou du tout). Une PR qui prétend tout tester
  alors que non sera refusée.

## 2. Cluster Proxmox réel : bac à sable seulement (PC A et PC B)
- **Développe et teste avec le faux Proxmox** (`httpx.MockTransport`, voir `backend/tests/test_*.py`).
- **Règle d'Enzo (2026-11-10) : PC A et PC B travaillent tous les deux sur le vrai cluster**, par l'interface de Kaji déployée
  (jamais en tapant le token) : lecture seule, et écritures **réversibles** dans le bac à sable (pool `kaji-test`, VM 115
  `kaji-sandbox`, identifiants 117 à 119 pour des machines jetables), en remettant tout à l'identique.
- **Interdits, quoi qu'il arrive** : le CT 116 `kaji-ct` (c'est Kaji) et les machines 100 à 114 (services d'Enzo) ; activer le pare-feu du
  datacenter ou d'un nœud ; **appliquer** une configuration réseau ou SDN ; lire ou écrire un mot de passe, un token ou `KAJI_SECRET_KEY`.
- **Un seul agent à la fois sur le cluster** : annonce-le dans le ticket (« essai réel en cours ») et nettoie avant de rendre la main,
  pour que deux agents ne se marchent pas dessus. Compte-rendu honnête dans la PR de ce qui a été vu en réel et de ce qui ne l'a pas été.
- Ne demande jamais le token Proxmox, la clé `KAJI_SECRET_KEY` ni le mot de passe admin, et ne les écris nulle part.

## 3. Sécurité : non négociable
- **Aucun secret** (mot de passe, token, clé privée) dans l'audit, les journaux, les messages d'erreur, les réponses
  d'API, les commits ou les PR. Utilise `SecretStr` ; l'audit ne dit que « défini ».
- **Rien n'est transmis tel quel à Proxmox** : chaque champ est validé (regex, bornes, listes blanches) ; les champs
  inconnus sont ignorés. Pas de clé libre, jamais.
- **Toute écriture est auditée** (succès, refus, erreur) avec `audit.record`, et ses refus le sont aussi.
- **Action destructrice ou irréversible** : `confirm=true` côté API, et le **nom exact** de la machine retapé quand elle
  détruit des données. Vérifié côté serveur, pas seulement dans l'interface.
- Les erreurs de validation ne renvoient jamais la valeur saisie (gestionnaire global dans `main.py`).

## 4. Architecture en deux minutes
- `backend/app/routers/*.py` : un fichier par fonction, exposant `router`. **Il est chargé automatiquement**
  (`routers/__init__.py`) : ne modifie pas `main.py`. Si ta route a la forme `…/guests/{node}/{type}/{vmid}/<mot>`,
  garde l'ordre par défaut : `actions` (`ORDER = 90`) passe en dernier. Un test vérifie qu'aucune route n'est masquée.
- Appels Proxmox : `routers/cluster.py::_px(...)` (erreurs traduites en 502/504, sans secret).
- Paramètres de création/édition : modules `vmspec.py`, `lxcspec.py`, `hardware.py` (validation + construction).
- **Schéma de base de données** (`app/migrations.py`) : une **nouvelle table** s'ajoute dans `models.py` seulement.
  **Modifier une table existante** (colonne, index…) exige une **migration** numérotée dans `MIGRATIONS`, en plus de
  `models.py`. Sans elle, une base déjà déployée casserait au prochain démarrage. Teste-la depuis une base de l'ancienne version.
- Frontend : `frontend/src/pages`, `components`, `lib`. Données : TanStack Query ; attente d'une tâche Proxmox :
  `lib/tasks.ts` (`runTask`, `LONG_TASK_SECONDS` pour les opérations longues).
- **Types frontend** : crée un fichier par domaine (`frontend/src/lib/types/<domaine>.ts`) au lieu d'ajouter à `api.ts`.
- **Documentation d'API** : un fichier par fonction dans `docs/api/<fonction>.md`. **Ne modifie pas le README** pour
  documenter une route (c'est la première source de conflits).

## 5. Tests
- Commandes : `cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest -q` ;
  `cd frontend && npm ci && npm run build`.
- **Les tests ne doivent jamais dépendre de ton `.env`** (`conftest.py` fixe les variables utilisées).
- Teste chaque garde-fou **séparément**, y compris les refus et l'absence de fuite de secret.
- **Vérifie que tes tests ont des dents** : casse volontairement la protection testée et constate que le test échoue.
  Un test écrit d'après le code (« la requête contient bien X ») peut valider une erreur : relis ce que Proxmox
  fait réellement avant d'affirmer qu'un comportement est correct.
- Un test qui passe du premier coup est suspect : demande-toi ce qui le ferait échouer.

## 6. Ce qui fait refuser une PR
CI rouge (y compris la carte du projet périmée) · secret qui fuit · paramètre non validé transmis à Proxmox · écriture sans audit · suppression sans confirmation
serveur · route masquée par `{action}` · test qui dépend de la machine · affirmation « testé en réel » non vérifiable ·
modification de fichiers hors du périmètre du ticket (surtout `PLAN.md`, `README.md`, `main.py`, `api.ts`).
