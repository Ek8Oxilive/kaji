# Notifications (M13, lot #151) : lecture (étape 1) et écriture (étape 2)

Préfixe `/api/connections/{conn_id}/notifications`. Section « Notifications » de la page « Datacenter » (équivalent de Datacenter → Notifications). Étape 1 : lecture. Étape 2 (plus bas) : écrire les cibles et les règles, tester une cible.
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

## Écriture (étape 2)
Droit Proxmox : `Mapping.Modify` sur `/mapping/notifications` (plus `Sys.Audit` ou `Sys.Modify` sur `/`) ; page « Accès » : `notifications-write`. **Toute écriture exige `confirm=true`** (400 sinon, booléen strict) ; `dry_run=true` renvoie `params` (secrets masqués) sans rien écrire.

| Route | Effet |
|---|---|
| `GET /targets/{type}/{name}` | Détail d'une cible (sans secret) + `digest` de Kaji, pour l'éditer |
| `POST /targets/{type}` | Crée une cible (`sendmail`, `smtp`, `gotify`, `webhook`) ; le nom est unique tous types confondus (409) |
| `PUT /targets/{type}/{name}` | Modifie ; `clear` retire des réglages (envoyés en `delete=`, noms Proxmox) ; `digest` |
| `DELETE /targets/{type}/{name}?confirm=true&type_name={name}` | Supprime : **refusé** pour une cible intégrée (`mail-to-root`, 422) ou **utilisée par une règle** (409, relue) |
| `POST /targets/{name}/test` | **Envoie réellement un message de test** |
| `GET /matchers/{name}` · `POST /matchers` · `PUT /matchers/{name}` · `DELETE /matchers/{name}` | Règles ; supprimer exige `confirm` + nom retapé ; une règle intégrée ne se supprime pas (422), mais se modifie ou se désactive |

Champs par type (liste blanche, un champ d'un autre type = 422 ; tableaux envoyés en clés répétées) :
- `sendmail` : `author`, `comment`, `disable`, `from_address`, `mailto`, `mailto_user`.
- `smtp` : idem + `server` et `from_address` **obligatoires**, `port` (1–65535), `mode` (`insecure`, `starttls`, `tls`), `username`, `password` (**secret**).
- `gotify` : `server` (URL http(s)) et `token` (**secret**) **obligatoires**, `comment`, `disable`.
- `webhook` : `url` et `method` (`post`, `put`, `get`) **obligatoires**, `headers` et `secrets` (listes `{name, value}`, valeurs **secrètes** saisies en clair, encodées en base64 par Kaji), `body` (modèle, encodé en base64), `comment`, `disable`.
- Règles : `match_field` (`exact:champ=valeur` ou `regex:champ=valeur`), `match_severity`, `match_calendar`, `mode` (`all`/`any`), `invert_match`, `target` (au moins une, **relue** : une cible inconnue = 422), `comment`, `disable`.

## Verrous
- **Secrets** : mot de passe SMTP, jeton Gotify, valeurs d'en-têtes et de secrets de webhook, corps : jamais renvoyés, journalisés (« défini ») ni dans une erreur ; Proxmox ne les relit pas (non vérifiés après écriture). En modification, un champ secret absent = inchangé ; **`headers` et `secrets` d'un webhook REMPLACENT toute la liste** (leurs valeurs ne sont pas relues).
- **Adresses** : `server` SMTP (nom ou IP) et URL Gotify / webhook : adresses locales littérales refusées (le nœud ouvrirait la connexion), pas d'identifiants dans l'URL.
- **Commentaires en ASCII imprimable** : Proxmox altère les accents des commentaires de la HA (constaté en réel) ; par prudence la même restriction s'applique ici (non vérifiée pour les notifications).
- **Test d'envoi** : `confirm=true` ET nom de la cible retapé (`type_name`) ; **une fois par minute et par cible** (429) ; compté dès l'envoi (un échec ne permet pas de réessayer en boucle) ; cible désactivée = 409 ; `dry_run` vérifie sans envoyer. L'audit ne contient pas les destinataires.
- `digest` : celui de Kaji (empreinte des valeurs lues) ; périmé = 409 ; celui de Proxmox, s'il existe, est transmis. Relecture après chaque écriture (502 si non appliqué).

## Audit
`notif-target-create|update|delete`, `notif-matcher-create|update|delete`, `notif-test`, refus compris.

## Validation
Faux Proxmox strict (`backend/tests/test_notifications_write.py`, secrets non relus, tableaux, base64), 53 mutations. **Jamais écrit en réel** : le token de Kaji n'a (probablement) pas `Mapping.Modify` ; ajouter une cible ou une règle puis la supprimer se fera avec l'accord d'Enzo, et le **test d'envoi** seulement vers une adresse qu'il indique.
