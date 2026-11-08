# Téléverser ou télécharger une ISO, un modèle, une image

Préfixe : `/api/connections/{id}/nodes/{node}`. Droit Proxmox : `Datastore.AllocateTemplate` sur le stockage ; le téléchargement par URL et la lecture des
métadonnées exigent en plus `Sys.AccessNetwork` sur le nœud. Contenus : `iso`, `vztmpl`, `import`. Audit : `storage-upload`, `storage-download` (refus compris).

| Route | Rôle |
|---|---|
| `GET /url-metadata?url=&verify_certificates=` | `{filename, mimetype, size}` d'un fichier distant (HEAD fait par le nœud, rien n'est téléchargé) |
| `POST /storage/{storage}/download-url` | le **nœud** télécharge : `{url, filename, content, checksum_algorithm?, checksum?, verify_certificates?}` → 202 `{upid, node}` |
| `POST /storage/{storage}/upload?filename=&content=&checksum_algorithm=&checksum=` | le **corps de la requête est le fichier** → 202 `{upid, node}` |

## Téléversement
- Envoi **en flux** : Kaji reconstruit un multipart vers Proxmox sans garder le fichier (ni en mémoire ni sur disque). `Content-Length` obligatoire (411 sinon), 20 Gio au plus (413).
- Un corps plus gros que la taille annoncée est refusé (400) ; un envoi interrompu est journalisé « Envoi interrompu ».
- Proxmox réalise ensuite l'import dans une tâche : attendre l'UPID (l'interface le fait).

## Garde-fous
- **Nom de fichier** : `[A-Za-z0-9][A-Za-z0-9._+()-]{0,200}`, sans `..`, extension imposée selon le contenu (`.iso/.img` ; `.tar.gz/.xz/.zst/.bz2` ; `.qcow2/.raw/.vmdk/.ova/.ovf`). Un guillemet ou un saut de ligne ne peut pas casser le multipart.
- **URL** : http ou https seulement, sans identifiants, ≤ 2000 caractères imprimables. Refus des adresses locales littérales (loopback, lien local, non spécifiée, multicast, réservée) et de `localhost` : le nœud télécharge lui-même, et le test réel a montré qu'il atteint sa propre API sur 127.0.0.1. Les adresses du réseau local (NAS) restent permises. **Limite** : un nom DNS qui pointe vers une adresse locale n'est pas détecté.
- **Somme de contrôle** : algorithme et valeur vont ensemble, longueur et hexadécimal vérifiés (md5, sha1, sha224, sha256, sha384, sha512).
- L'audit note « sha256 exigé » (la vérification se fait ensuite sur le nœud, dans la tâche : une somme fausse fait échouer la tâche).
- L'URL n'est jamais journalisée en entier (elle peut porter un jeton) : seul l'hôte l'est.
- Les erreurs Proxmox sont traduites (502/504) sans message brut.
