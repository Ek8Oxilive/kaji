# Double authentification des utilisateurs (M6, lot #384)

Préfixe `/api/connections/{conn_id}/access/tfa`. Équivalent de Datacenter → Permissions → Two Factor. Bouton **« Double authentification… »** du panneau « Session administrateur » de la page « Accès ».
Schéma lu sur `apidoc.js` de Proxmox 9 (`/access/tfa`). Validation : `backend/app/tfaspec.py`.

| Route | Droit | Effet |
|---|---|---|
| `GET /` | Kaji | Entrées de tous les utilisateurs que le jeton de Kaji peut voir (Proxmox renvoie tout ou seulement les siennes, selon ses privilèges) |
| `GET /{userid}` | Kaji | Entrées d'un utilisateur |
| `POST /totp-setup` | session Kaji | Génère un secret TOTP et son URI. **Rien n'est gardé côté serveur**, réponse `no-store` |
| `POST /` | session administrateur | Ajoute un **TOTP** ou des **codes de secours** |
| `PUT /{userid}/{entry}` | session administrateur | Active, désactive ou change la description |
| `DELETE /{userid}/{entry}` | session administrateur | Supprime une entrée |
| `POST /{userid}/unlock` | session administrateur | Débloque la double authentification d'un compte verrouillé après trop d'échecs (`PUT /access/users/{userid}/unlock-tfa`, **`allowtoken: 1`** : accepté avec un jeton) |

Les écritures passent par la **session administrateur** (`User.Modify`). **Hors périmètre, volontairement** : enregistrer une clé **WebAuthn** ou **U2F** (cérémonie du navigateur), **YubiKey OTP**, et le champ `password` de Proxmox (le mot de passe de l'utilisateur : Kaji n'en demande ni n'en transmet jamais).

## Ajouter
- **TOTP** : `POST /totp-setup` renvoie `{secret, uri}` (20 octets aléatoires, base32 ; URI `otpauth://totp/…`, SHA1, 6 chiffres, 30 s). Le titulaire entre le secret dans son application ; on renvoie `POST /` avec `type: "totp"`, `totp` (l'URI) et `value` (le code de 6 à 8 chiffres affiché). L'URI ne revient jamais, n'est jamais journalisée (`SecretStr`).
- **Codes de secours** : `type: "recovery"`, sans `totp` ni `value` (422 sinon). Proxmox renvoie les codes **une seule fois** ; Kaji les relaie dans la réponse (`recovery`, 20 au plus, forme vérifiée) sans jamais les journaliser ni les relire.
- Validation de l'URI : `otpauth://totp/…` à secret base32 (16 caractères au moins), `algorithm` SHA1, `digits` 6 à 8, `period` 30, `issuer` sûr ; paramètre inconnu, double ou vide refusé. `description` : 255 caractères au plus, sans caractère de contrôle. Types `u2f`, `webauthn`, `yubico` : 422.

## Verrous (décidés par le serveur)
- **Session administrateur** exigée (401 ou 403 sinon).
- **Comptes protégés** : `root@pam`, le compte de Kaji et celui de la session administrateur ne sont jamais modifiés (403).
- **`confirm=true` et l'identifiant de l'utilisateur retapé** (`type_name`, ou `name` pour `DELETE`), 400 sinon. `dry_run` renvoie les verrous sans rien écrire.
- **Coupure possible** : ajouter une entrée ou activer une entrée sur un compte qui n'a AUCUNE entrée active **active la double authentification** sur ce compte : si son titulaire n'a pas le secret ou les codes, il ne peut plus se connecter. Exige en plus `acknowledge_cut_access=true` et `phrase="COUPURE POSSIBLE"` (409 sinon). Un compte qui a déjà une entrée active n'est pas concerné.
- **Désactiver ou supprimer** une entrée ne verrouille personne (c'est une baisse de sécurité, pas une coupure) : `confirm` + identifiant suffisent ; `locks.turns_off` signale que la dernière entrée active disparaît.
- Relecture après chaque écriture (502 si Proxmox n'a pas appliqué).

## Audit
`tfa-totp-setup`, `tfa-add`, `tfa-update`, `tfa-delete`, refus compris. Le secret, l'URI, le code et les codes de secours n'y figurent jamais (« défini », type et identifiant d'entrée seulement).

## Validation
Faux Proxmox strict (`backend/tests/test_tfa.py` : clés autorisées, URI et code validés, `password` refusé, secrets non relus). **Jamais écrit en réel** : le jeton d'administration de Kaji n'a pas `User.Modify` sur `/access/groups`, et activer la double authentification peut verrouiller un compte.
## Essai réel du 2026-11-13 : les écritures sont IMPOSSIBLES avec un jeton
Session administrateur ouverte avec le jeton de Kaji (rôle `Administrator` sur `/`, utilisateur ET jeton), compte jetable `kajitest@pve` : la lecture (`GET`) répond, l'aperçu `dry_run` aussi, mais l'écriture (`POST /access/tfa/{userid}`, codes de secours) est refusée par Proxmox (« Droits insuffisants »). **Cause lue dans le schéma de Proxmox 9 (`apidoc.js`)** : `POST`, `PUT` et `DELETE` de `/access/tfa/{userid}[/{id}]` ont **`allowtoken: 0`** : aucun jeton d'API ne peut les appeler, quels que soient ses droits (alors que ACL, realms, utilisateurs, groupes, rôles et jetons ont `allowtoken: 1`). Kaji le dit désormais dans le message (403). Faire marcher la TFA demanderait une session par **ticket** (connexion par mot de passe, avec code TFA si le compte en a, et `password` du compte pour certaines écritures) : non fait, décision à prendre. En attendant : lecture seule dans Kaji ; écriture dans l'interface de Proxmox ou `pvesh` en root. `PUT /access/users/{userid}/unlock-tfa` accepte les jetons (`allowtoken: 1`) : piste pour débloquer un compte, non implémentée.

## Débloquer un compte (lot #399)
`POST /{userid}/unlock` : `confirm=true` et l'identifiant retapé (`type_name`), `dry_run` possible. Refusé (409) si le compte n'est pas verrouillé (lu avec `GET /access/tfa` : `totp-locked` ou `tfa-locked-until`) ; relecture après l'appel (502 si Proxmox n'a pas débloqué). Pas de phrase : débloquer ne baisse pas la sécurité (le compte garde ses entrées). Audit `tfa-unlock`. Option « Débloquer un compte verrouillé » de la fenêtre « Double authentification… ».
**Jamais essayé en réel** : aucun compte verrouillé sur le cluster (il faudrait enchaîner des échecs de TOTP sur un compte jetable).
