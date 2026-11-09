# Notifications (M13, lot #151) : lecture (étape 1)

Préfixe `/api/connections/{conn_id}/notifications`. Section « Notifications » de la page « Datacenter » (équivalent de Datacenter → Notifications). **Lecture seule** : l'écriture (ajouter, modifier, supprimer, tester une cible ; règles) est l'étape 2 du même lot.
Droit Proxmox : `Mapping.Audit` sur `/mapping/notifications` (page « Accès » : `notifications-read`) ; sans lui, chaque sous-lecture échoue séparément (`errors`).

| Route | Contenu |
|---|---|
| `GET /` | `targets[]` (nom, type, `disable`, `comment`, `origin`, `builtin`, `used_by[]`), `endpoints{sendmail, smtp, gotify, webhook}[]`, `matchers[]`, `fields[]`, `unused_targets[]`, `errors{}` |
| `GET /field-values` | Valeurs connues des champs de règle (aide à la saisie, 500 au plus) |

## Aucun secret ne sort
Mot de passe SMTP, jeton Gotify, **valeurs** des en-têtes et des secrets d'un webhook, corps du webhook : jamais renvoyés (le test simule un Proxmox qui les renvoie en clair). Un webhook montre seulement les **noms** de ses en-têtes et de ses secrets et `body_set` (défini ou non). Chaque type n'expose que ses propres champs (liste blanche) ; valeurs hostiles écartées (type de cible inconnu, `origin`, gravité, mode…).

## Détails
- Cibles intégrées (`origin` = `builtin`, ex. `mail-to-root`) : signalées `builtin` (elles ne seront pas supprimables).
- `used_by` : règles qui visent la cible, relues dans les règles (une cible sans règle n'envoie rien : `unused_targets`).
- Règles : `match_field`, `match_severity` (`info`, `notice`, `warning`, `error`, `unknown`), `match_calendar`, `mode` (`all` ou `any`), `invert`, `targets`.

## Validation
Faux Proxmox (`backend/tests/test_notifications_read.py`) qui renvoie les secrets en clair, 19 mutations. Essais réels : voir `docs/REPRISE.md`.
