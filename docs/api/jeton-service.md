# Jeton de service du planificateur et des alertes (J2, option A du cadrage, ticket #441)

Le planificateur d'actions et les alertes tournent **sans personne de connecté** : aucun jeton personnel ne peut servir. Aujourd'hui ils utilisent le jeton partagé de la connexion, souvent trop puissant. Un **jeton de service** par connexion le remplace : **limité aux droits dont ces deux fonctions ont besoin, jamais Administrator**.

Routes sous `/api/connections/{conn_id}/service-token`. Lecture : tous les rôles (aucun secret) ; écriture : **administrateurs** (politique par défaut de `app/roles.py`).

| Route | Rôle |
|---|---|
| `GET …/service-token` | `{enabled, problem, required, max_days, allowed_privileges, token: {state, pve_user, token_id, expires_at, days_left, verified, created_by}}`. Jamais de secret. |
| `PUT …/service-token` | Enregistre (ou remplace) : `{pve_user, token_id, secret, expires_at?, privsep}`. **Refusé** si le jeton détient un droit hors de la liste blanche ou si ses droits ne peuvent pas être lus. Renvoie `lacks` : droits minimaux qui lui manquent (signalés, pas refusés). |
| `DELETE …/service-token` | Retire le jeton de Kaji (il reste valable chez Proxmox). 204 / 404. |

## Le droit en trop est refusé, pas signalé
À l'enregistrement, Kaji interroge Proxmox **avec le jeton lui-même** (`GET /access/permissions`, tous chemins) et refuse (422, audité) tout jeton qui détient **un seul** privilège hors de :

`Sys.Audit`, `VM.Audit`, `VM.PowerMgmt`, `VM.Snapshot`, `Datastore.Audit`, `Pool.Audit`

(ce que le planificateur — démarrer, arrêter, redémarrer, snapshot — et les alertes — ressources, nœuds, tâches — lisent ou font). Les privilèges en trop sont **nommés** dans le refus. **Un privilège présent compte même non propagé.** **Si Proxmox ne dit pas les droits du jeton** (403, réponse vide ou malformée), le jeton est **refusé** : un jeton de service ne s'enregistre jamais « sur parole ». Sont aussi refusés, comme pour un jeton personnel : `root@pam`, le jeton partagé de la connexion, l'absence de privilèges séparés, l'absence d'expiration chez Proxmox, une expiration au-delà de `KAJI_SERVICE_TOKEN_MAX_DAYS` (365).

Exemple côté Proxmox (à lancer en root sur un nœud ; **non essayé par un agent**) :
```bash
pveum user add kaji-service@pve --comment "Kaji : planificateur et alertes"
pveum role add Kaji-service -privs "Sys.Audit,VM.Audit,VM.PowerMgmt,VM.Snapshot,Datastore.Audit,Pool.Audit"
pveum user token add kaji-service@pve planificateur --privsep 1 --expire $(date -d '+180 days' +%s)    # le secret est affiché une seule fois
pveum acl modify / --roles Kaji-service --users 'kaji-service@pve' --tokens 'kaji-service@pve!planificateur'
```
Les machines protégées (`KAJI_PROTECTED_VMIDS`) restent refusées par Kaji quel que soit le jeton.

## Ce qui change pour les tâches de fond (`app/deps.py::service_factory`)
- **Jeton de service enregistré** : toutes les requêtes du planificateur et des alertes pour cette connexion partent avec lui.
- **Aucun** : le jeton partagé, comme avant, **sauf** `KAJI_REQUIRE_SERVICE_TOKEN=true` : rien n'est fait pour cette connexion (erreur claire dans le suivi de l'action).
- **Expiré**, **refusé par Proxmox** (401 : marqué, puis bloqué sans appeler Proxmox jusqu'au ré-enregistrement) ou **clé `KAJI_TOKEN_KEY` changée** : erreur explicite, **jamais de repli silencieux** sur le jeton partagé.
- Un test de connexion avec des identifiants saisis, une session par ticket, un hôte inconnu : jamais remplacés.
- Stockage : table `service_tokens` (un jeton par connexion), chiffré avec la **clé séparée** `KAJI_TOKEN_KEY` (comme les jetons personnels : `docs/api/jetons-utilisateur.md`) ; rotation (`rotate-token-key`), `verify` et `restore` les couvrent. Supprimer la connexion le supprime.
- Audit : `service-token-set` / `service-token-removed` (compte et identifiant du jeton, échéance, « droits limités vérifiés »), **jamais le secret**.

## Réglages
| Variable | Rôle |
|---|---|
| `KAJI_REQUIRE_SERVICE_TOKEN` | `true` : sans jeton de service, le planificateur et les alertes ne font rien pour la connexion (défaut `false`) |
| `KAJI_SERVICE_TOKEN_MAX_DAYS` | échéance maximale acceptée (défaut 365) |

## Validé en réel, et ce qui ne l'a pas été
**Aucun essai réel** : faux Proxmox strict qui authentifie les jetons, sert `/access/permissions` et note qui appelle (`backend/tests/test_service_tokens.py`), jusqu'au planificateur de bout en bout.

**Non validé en réel** : le format réel de `GET /access/permissions` appelé par un jeton à privilèges séparés (chemins et valeurs `0/1` lus comme « présent = détenu ») ; que Proxmox accepte les actions du planificateur avec exactement ces six privilèges (par exemple `VM.PowerMgmt` seul pour un redémarrage, `VM.Snapshot` pour un snapshot) ; l'interface (dialogue « Jeton de service… » de la page Connexions) dans un navigateur sur un Kaji déployé.
