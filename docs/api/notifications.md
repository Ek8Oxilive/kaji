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
Faux Proxmox strict (`backend/tests/test_notifications_write.py`, secrets non relus, tableaux, base64), 53 mutations, puis 8 pour le format des en-têtes. Le test d'envoi réel n'a jamais été lancé : il attend un relais SMTP sur le nœud (`docs/v1-actions-enzo.md`) et une adresse choisie par Enzo.

## Constaté en réel (2026-11-13, lot #373)
Cibles DÉSACTIVÉES, sans identifiants, adresse de documentation `192.0.2.10`, créées, modifiées, supprimées par l'API de Kaji ; liste des cibles identique à la fin.
- **SMTP** (sans authentification) : créée, relue (`server`, `port`, `mode`, `from_address`, `mailto`), modifiée (port, `mode` `starttls`, commentaire retiré par `clear`), supprimée avec le nom retapé ; refus sans `confirm` (400), `digest` périmé (409), test d'envoi d'une cible désactivée (409, en `dry_run`).
- **Webhook** : créé, relu, modifié (`method`, corps retiré par `clear`), supprimé.
- **Défaut trouvé et corrigé** : **les en-têtes et secrets d'un webhook s'écrivent en chaîne de propriétés `name=<nom>,value=<base64>`** (schéma de Proxmox 9). Kaji envoyait `<nom>=<base64>` et Proxmox répondait 500 `unknown key "Content-Type"`. Le faux Proxmox avait la même erreur, c'est pourquoi aucun test ne la voyait. La lecture des noms accepte maintenant cette chaîne, un objet `{name}` et l'ancien `nom=valeur`.
- **Correctif revérifié en réel après déploiement (2026-11-13)** : webhook désactivé avec l'en-tête `Content-Type` créé (201), nom relu, liste remplacée par deux en-têtes, supprimé ; audit sans valeur d'en-tête. Non essayés : secrets d'un webhook (valeurs secrètes, non saisies par un agent), format brut renvoyé par Proxmox pour `header` et `secret`.
- **Piège de l'outil de test** : l'extension Chrome peut rejouer un script JavaScript ; ne mettre qu'UNE écriture par appel, sinon l'audit montre deux passages et la réponse affichée peut être celle du rejeu.
