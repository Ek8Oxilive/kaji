# Actions planifiées (M13, lot #411)

Préfixe `/api/connections/{conn_id}/schedules`. **Propre à Kaji** (Proxmox n'a pas de planificateur d'alimentation de machines) : démarrer, éteindre, redémarrer, arrêter de force ou faire un snapshot d'une machine à heure fixe. Section « Actions planifiées » en bas de la page « Tâches ».

| Route | Droit | Effet |
|---|---|---|
| `GET /` | tout utilisateur de Kaji | Liste (avec `next_run`, `last_run_at`, `last_status`, `last_detail`) |
| `POST /` | **administrateurs** | Crée |
| `PUT /{id}` | **administrateurs** | Remplace (jours, heure, action, activée) ; réinitialise la minute mémorisée |
| `DELETE /{id}?confirm=true` | **administrateurs** | Supprime |

Corps : `node`, `gtype` (`qemu` / `lxc`), `vmid`, `action` (`start`, `shutdown`, `reboot`, `stop`, `snapshot`), `days` (0 = lundi à 6 = dimanche), `time` (`HH:MM`), `timezone` (`Europe/Paris` par défaut), `enabled`, `confirm`.

## Garde-fous (serveur)
- **Liste blanche d'actions** ; `stop` (arrêt forcé) exige `confirm=true` ; machines de `KAJI_PROTECTED_VMIDS` refusées **à la création ET à l'exécution** ; la machine est relue chez Proxmox (elle doit exister) ; un modèle ne se planifie pas ; 200 planifications au plus par connexion ; fuseau horaire connu (`zoneinfo`) ; saisies hostiles refusées avant tout appel Proxmox.
- **Exécution** (`app/scheduler.py`, tâche de fond lancée avec l'application, toutes les 20 s ; `KAJI_SCHEDULER=false` la coupe) : à la minute prévue dans le fuseau, **une seule fois** (la minute est mémorisée AVANT d'agir) ; **un créneau manqué n'est jamais rattrapé** (Kaji arrêté, redémarrage) ; une heure qui n'existe pas (passage à l'heure d'été) est sautée ; l'état de la machine est relu : démarrer une machine déjà en marche, ou arrêter / redémarrer une machine arrêtée, est **ignoré** (« skipped »), pas une erreur ; une erreur d'une planification n'arrête pas les autres ; aucune erreur de Proxmox n'est relayée avec ses secrets.
- **Snapshots** : nom `kaji-AAAAMMJJ-HHMM` (UTC), **aucune suppression automatique** (pas de rétention : à nettoyer à la main, une suppression automatique serait un risque de perte de données).
- Audit : `schedule-create|update|delete` (utilisateur de Kaji) et `schedule-<action>` (utilisateur « planificateur », statut `started` ou `error`, détail `#id statut : …`).
- Une seule instance de Kaji doit tourner (un seul worker, comme aujourd'hui) : sinon chaque instance exécuterait la planification.

## Validation
Faux Proxmox strict (`tests/test_scheduler.py`, `test_schedules.py`, `test_schedulespec.py` : créneau jamais rejoué, fuseau, passage à l'heure d'été, machines protégées, modèles, erreurs sans fuite, boucle, rôles, isolation par connexion), 21 mutations tuées.
**Pas essayé en réel** : voir `docs/REPRISE.md`.
