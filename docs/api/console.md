# Console web (noVNC, xterm.js)

Une console est un **accès interactif à une machine** : tout est contrôlé côté serveur. Ce fichier décrit le **backend** (lot M9-1) ;
l'interface (onglet « Console » de la page Machine : noVNC, xterm.js) est le lot M9-2, décrite en fin de fichier.

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

## Interface (lot M9-2)

Onglet **Console** de la page Machine (adresse `#/machine/<nœud>/<type>/<id>/console`) : noVNC pour une VM ou un conteneur, xterm.js pour
un conteneur (bouton « Ouvrir le terminal », ou « Écran (noVNC) »). Boutons Déconnecter, Ctrl+Alt+Suppr (noVNC), Plein écran.
- La console se **ferme dès qu'on quitte l'onglet ou la page** (et l'audit `console-close` le journalise).
- Les bibliothèques ne se chargent **qu'à l'ouverture d'une console** (noVNC ~187 Ko, xterm ~331 Ko, hors du paquet principal).
- noVNC : le mot de passe VNC est le ticket renvoyé par la demande. xterm.js : le serveur fait l'identification ; le navigateur parle le
  protocole de Proxmox (`0:<longueur>:<données>` pour la saisie, `1:<colonnes>:<lignes>:` pour la taille, `2` toutes les 30 s).
- **nginx** (`frontend/nginx.conf`) : une route `/api/console/` dédiée relaie le WebSocket (`Upgrade`, `Connection: upgrade`, sans tampon).
  **`Host` y garde son port (`$http_host`)** : le backend compare l'en-tête `Origin` (avec port) à `Host` ; avec `$host` le port serait perdu
  et toutes les consoles seraient refusées derrière `:8080`. Un proxy placé devant (HTTPS) doit transmettre `Host` tel quel.
- Dépendances épinglées en version exacte : `@novnc/novnc` 1.7.0 (MPL-2.0), `@xterm/xterm` 6.0.0 et `@xterm/addon-fit` 0.11.0 (MIT).

## Validé en réel, et ce qui ne l'a pas été

Validé sur un vrai cluster (conteneur jetable du bac à sable, supprimé ensuite) : `vncproxy` et `termproxy` répondent avec le token de
Kaji, le WebSocket s'ouvre (première trame `RFB 003.008` pour noVNC, `OK` pour xterm.js après l'identification).

Validé aussi, **depuis l'interface** : terminal xterm.js d'un conteneur (invite de connexion), noVNC d'une VM vide (écran du BIOS) et d'une VM
réelle (Ubuntu), fermeture en quittant l'onglet.

**Non validé en réel** : le fonctionnement **derrière nginx** (pas de Docker sur la machine de test) et le CSP avec les WebSocket ; la saisie
clavier dans noVNC, le copier-coller, le redimensionnement du terminal ; la console série des VM et SPICE (non gérés) ; le **shell des nœuds**
(exige `root@pam`, voir `docs/m6-ecriture.md`, option D).
