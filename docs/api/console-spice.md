# Console SPICE (fichier `.vv` pour virt-viewer)

| Route | Rôle |
|---|---|
| `POST /api/connections/{id}/guests/{node}/{qemu\|lxc}/{vmid}/spice` | Demande un ticket SPICE à Proxmox (`POST …/spiceproxy`) et renvoie le fichier **`.vv`** (`application/x-virt-viewer`, `Content-Disposition: attachment; filename="kaji-<type>-<vmid>.vv"`). Aucun corps. |

Comme dans l'interface de Proxmox : le navigateur enregistre le fichier, et **`virt-viewer`** (`remote-viewer`) doit être installé pour l'ouvrir. Le ticket est à **usage unique et ne vaut que ~40 s** : ouvrir le fichier tout de suite.

## Garde-fous
- **Droit Proxmox** : `VM.Console` sur la machine (page « Accès » : fonction `console`).
- La machine doit être **en marche** et ne pas être un modèle (sinon **409**, rien demandé à Proxmox).
- **VM** : carte d'affichage `qxl` exigée (`vga` = `qxl`, `qxl2`… ; configuration EN COURS d'utilisation lue avec `current=1`), sinon **409** « choisis-la dans l'onglet Périphériques, puis redémarre la VM ». Un conteneur ouvre un terminal : pas de carte à vérifier.
- **Proxy** : Kaji donne à Proxmox l'hôte de la connexion (`proxy=<hôte>`), pas le nom interne du nœud, pour que `virt-viewer` joigne le nœud par l'adresse que Kaji connaît (port 3128, `spiceproxy`). L'hôte est validé (`[A-Za-z0-9._\-\[\]:]`), sinon le paramètre n'est pas envoyé.
- **Rien n'est recopié tel quel** (`spicespec.py`) : seules les clés connues sont gardées (`type`, `title`, `host`, `tls-port`, `password`, `proxy`, `ca`, `host-subject`, `delete-this-file`, `secure-attention`, `release-cursor`, `toggle-fullscreen`, `fullscreen`), chaque valeur est contrôlée en entier (`fullmatch`), **aucun saut de ligne** n'est admis (il permettrait d'ajouter une section ou une clé au fichier ; seul le certificat PEM a ses sauts de ligne écrits en `\n`), `type` doit valoir `spice`, `tls-port` est un port TCP valide. Une réponse incomplète ou suspecte donne **502** et aucun fichier, avec un message fixe qui ne cite jamais la valeur.
- **Secret** : le ticket (`password`) n'est ni journalisé ni audité ; l'audit `spice-open` (démarré ou erreur) ne dit que la machine. La réponse n'est jamais mise en cache (`Cache-Control: no-store` posé par le middleware de l'API).
- Les refus de Proxmox (droit manquant…) deviennent un message fixe (502), comme pour toutes les routes.

Interface : bouton **« SPICE (virt-viewer) »** de l'onglet Console (VM et conteneur) ; il enregistre `kaji-<type>-<vmid>.vv` et rappelle d'ouvrir le fichier aussitôt.

## Vérifier sans virt-viewer (`tools/spice_check.py`)
Client SPICE minimal (Python + `cryptography`) qui rejoue le début d'une connexion de `virt-viewer` : tunnel `CONNECT` par le proxy du nœud, TLS vérifié avec le `ca` et le `host-subject` du fichier, lien SPICE, authentification par le ticket, lecture du premier message du canal principal. Il n'affiche jamais le ticket et supprime le `.vv` dès qu'il est lu ; le ticket ne vaut que ~40 s, donc le lancer juste après avoir cliqué le bouton (`python3 tools/spice_check.py ~/Downloads/kaji-qemu-<vmid>.vv`).

Remarque : Brave et Chrome gardent un fichier d'un type inconnu en « Non confirmé … .crdownload » tant qu'on n'a pas cliqué « Conserver » : son contenu est pourtant déjà complet.

