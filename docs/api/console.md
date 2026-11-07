# Console web (noVNC, xterm.js)

Une console est un **accès interactif à une machine** : tout est contrôlé côté serveur. Ce fichier décrit le **backend** (lot M9-1) ;
l'interface (noVNC, xterm.js) est le lot suivant.

| Route | Rôle |
|---|---|
| `POST /api/connections/{id}/guests/{node}/{type}/{vmid}/console` | Demande une console. Corps : `{"kind": "vnc" \| "term"}` (défaut `vnc`). Réponse **201** : `{session, kind, expires_in, ticket?}` |
| `WS /api/console/{session}` | Relais binaire navigateur ↔ console Proxmox |

## Demande (`POST …/console`)

- `vnc` : noVNC, pour une VM ou un conteneur (`vncproxy`, `websocket=1`). La réponse contient `ticket` : c'est le **mot de passe VNC**
  que noVNC présente (comme l'interface de Proxmox). Il est valable quelques secondes et **une seule fois**.
- `term` : xterm.js, **conteneurs seulement** (`termproxy`). Le serveur fait lui-même l'identification auprès de Proxmox : **le ticket ne
  quitte jamais le serveur** et n'est pas dans la réponse.
- La machine doit être **en marche** et ne pas être un modèle (sinon **409**, sans rien demander à Proxmox). `term` pour une VM : **400**.
- Une réponse inexploitable de Proxmox (port hors 1 à 65535, ticket vide ou démesuré…) donne **502** et aucune session.
- `session` est un identifiant aléatoire (256 bits) **à usage unique**, valable **30 s**, **lié à ta session Kaji** : un autre
  navigateur ou une autre session ne peut pas l'utiliser, et le présenter ne le détruit pas. Au plus **8** demandes en attente par
  session Kaji (sinon **429**).
- Audité : `console-open` (démarré ou erreur), sans ticket ni secret.

## WebSocket (`WS /api/console/{session}`)

Refus **avant d'accepter** (HTTP 403 à la poignée de main) si :
- l'en-tête **`Origin`** est absent, ou n'a pas exactement l'hôte (avec port) de l'en-tête `Host` : protection contre le détournement
  de WebSocket depuis un autre site (le cookie est déjà en `SameSite=Strict`) ;
- tu n'as pas de session Kaji valable ;
- l'identifiant est inconnu, expiré, déjà utilisé ou lié à une autre session.

Ensuite :
- Kaji ouvre le WebSocket chez Proxmox **avec le token** (jamais le navigateur) et relaie les octets dans les deux sens, **en gardant le
  type des trames** (texte / binaire). Sous-protocole `binary`.
- **Limites** : **4** consoles ouvertes en même temps par session Kaji ; fermeture après **30 min sans aucun octet** ; durée
  maximale **8 h** ; message de plus de **1 Mio** refusé (la console se ferme, le message n'est **pas transmis**).
- Si Proxmox ne répond pas ou refuse, la console se ferme (code 1011) **sans jamais renvoyer l'adresse** (qui contient le ticket).
- Audité : `console-close` avec la durée et la raison de fin (`client`, `proxmox`, `inactivité`, `durée maximale`, `message trop
  gros`, `error…`). **Aucun contenu de console n'est journalisé** (ni ce que tu tapes, ni ce qui s'affiche).
- L'audit de fermeture est écrit **avant** les fermetures de connexion, pour qu'une interruption du serveur ne le fasse pas perdre.

## Droits Proxmox nécessaires

`VM.Console` sur la machine (compris dans `PVEVMAdmin` ; visible dans la page Accès). Pas de `Sys.Console` : le **shell du nœud** (qui
exige `root@pam`) n'est **pas** géré.

## Validé en réel, et ce qui ne l'a pas été

Validé sur un vrai cluster (conteneur jetable du bac à sable, supprimé ensuite) : `vncproxy` et `termproxy` répondent avec le token de
Kaji, le WebSocket s'ouvre (première trame `RFB 003.008` pour noVNC, `OK` pour xterm.js après l'identification).

**Non validé en réel** : voir la description de la PR (relais complet depuis un navigateur, console d'une VM QEMU, console d'un
conteneur sans terminal configuré). **Pas d'interface dans ce lot.**
