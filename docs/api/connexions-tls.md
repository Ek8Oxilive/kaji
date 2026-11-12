# Épinglage du certificat d'une connexion (V1)

Trois routes sous `/api/connections/{id}/tls` (session obligatoire). Justification et menace : `docs/securite.md` ; usage : `docs/deploiement.md`.

| Route | Rôle |
|---|---|
| `GET` | **Lecture seule** : le certificat que le serveur présente maintenant (`fingerprint` SHA-256 en majuscules séparé par `:`, `subject`, `issuer`, `self_signed`, `not_before`, `not_after`) et l'état : `pinned`, `pinned_fingerprint`, `matches` (`true` / `false` / `null` sans épingle), `verify_ssl`, `reachable`. Injoignable : `reachable: false`, sans détail d'erreur. |
| `PUT` `{fingerprint, confirm}` | Épingle le certificat présenté **si son empreinte est celle que l'utilisateur a vue** : le serveur relit le certificat au moment d'épingler (409 s'il a changé entre-temps). `confirm=true` obligatoire (400 sinon). Audit `tls-pin` (empreinte publique seulement). |
| `DELETE ?confirm=true` | Retire l'épingle (la connexion retrouve `verify_ssl`). 400 sans `confirm`, 409 si rien n'est épinglé. Audit `tls-unpin`. |

`GET /api/connections` et `/{id}` renvoient `tls_pinned` et `tls_fingerprint`. **Le certificat PEM n'est jamais renvoyé** ; seul le certificat public est stocké (colonne `connections.tls_cert_pem`, migration n° 2).

## Comment c'est vérifié (`app/tlspin.py`)
Le certificat épinglé devient **l'unique ancre de confiance** du client (`VERIFY_X509_PARTIAL_CHAIN` : une feuille signée par une autorité privée, comme le certificat par défaut de Proxmox, peut servir d'ancre), le **nom n'est pas vérifié** (on reconnaît le certificat à son contenu ; l'adresse d'un nœud est souvent une IP). Il prime sur `verify_ssl`. Même règle pour les appels REST, les consoles (WebSocket) et la session administrateur.

Quand le serveur présente un autre certificat, les appels répondent **502** « Le certificat de Proxmox ne correspond pas à celui épinglé (ou n'est pas approuvé) » : renouvellement légitime ou usurpation, il faut comparer l'empreinte sur le nœud et épingler le nouveau.

## Limites
- Avec un seul certificat épinglé par connexion, un cluster dont chaque nœud a son propre certificat n'est protégé que pour le nœud de la connexion (l'hôte enregistré).
- Le **premier** épinglage reste un acte de confiance (« TOFU ») : il vaut ce que vaut la comparaison faite par l'utilisateur avec son nœud.
- Un certificat illisible dans la base fait échouer la connexion (erreur 500) au lieu de retomber silencieusement sur « non vérifié ».
