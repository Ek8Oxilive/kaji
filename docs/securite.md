# Revue de sécurité de Kaji (2026-11-12, en vue de la V1)

Relecture du code d'authentification, des sessions, du chiffrement, des en-têtes, des consoles, du déploiement et des dépendances. Ce qui a été **vérifié**, ce qui a été **corrigé**, et ce qu'il **reste à décider** avant d'annoncer une V1. Aucun mot de passe, jeton ni `KAJI_SECRET_KEY` n'a été lu pour cela.

## Vérifié (et gardé par un test)
| Point | Constat |
|---|---|
| **Toute route exige une session** | **Nouveau test** `tests/test_all_routes_need_session.py` : les 318 routes protégées de l'API (sur 323) répondent **401 sans session** ; 5 sont publiques par choix (`GET /api/auth/status`, `POST /api/auth/setup`, `/login`, `/logout`, `GET /api/health`). Un futur routeur qui oublierait l'authentification fait échouer ce test. |
| Mots de passe | Argon2 (paramètres par défaut de `argon2-cffi`), 12 caractères au moins à la création et au changement, vérification à temps constant même pour un utilisateur inconnu (pas d'énumération). |
| Sessions | Jeton signé (HS256, clé dérivée par HKDF) **qui renvoie à une ligne en base** : révocable (déconnexion, « tout déconnecter », changement de mot de passe), expiration serveur (12 h). Un jeton volé ne sert plus après la déconnexion, et une signature seule ne suffit pas (il faut un `jti` existant en base). |
| Cookie | `HttpOnly`, `SameSite=Strict`, `Secure` par défaut. |
| Limiteur de connexions | 5 échecs par 5 minutes et par IP (aussi sur le changement de mot de passe) ; l'IP vient de nginx, jamais d'un en-tête fourni par le client. |
| Secrets au repos | Jetons Proxmox chiffrés (Fernet, clé dérivée par HKDF) ; jamais renvoyés par l'API, jamais dans l'audit, les journaux ni les erreurs (tests dans chaque lot) ; les erreurs de validation ne recopient pas la valeur saisie. |
| Consoles (WebSocket) | `Origin` comparé à `Host`, session Kaji vérifiée, identifiant à usage unique lié à la session, nombre de consoles limité, ticket Proxmox jamais renvoyé. |
| En-têtes | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` sur toute l'API ; CSP stricte (sans script en ligne), `Permissions-Policy` sur l'application. |
| Écritures | Chaque champ est validé (regex `fullmatch`, bornes, listes blanches), aucune clé libre vers Proxmox ; actions destructrices : `confirm` et nom retapé **vérifiés côté serveur** ; machines protégées (`KAJI_PROTECTED_VMIDS`) ; audit de chaque écriture, refus compris. |
| Conteneur | Backend sans privilèges (uid 10001), un seul processus, non publié sur le réseau, base en `600`. |
| Dépendances | `pip-audit -r requirements.txt` : aucune vulnérabilité connue ; `npm audit --omit=dev` : 0 (2026-11-12). Pas d'`eval`, `exec`, `pickle`, `shell=True` ni de sous-processus dans le backend. |

## Corrigé dans cette revue
- **`KAJI_SECRET_KEY` d'exemple** : `.env.example` contient `changeme`, que le backend acceptait pour signer les sessions. Il **refuse maintenant de démarrer** avec une valeur vide ou d'exemple (message qui explique comment en générer une) et **signale** (sans bloquer) une clé de moins de 32 caractères, pour ne pas faire tomber un déploiement existant. Tests : `tests/test_secret_key_check.py`.

## À décider avant la V1
| Gravité | Point | Pourquoi | Recommandation |
|---|---|---|---|
| **Moyenne** | **Le certificat de Proxmox n'est pas vérifié par défaut** (`verify_ssl=false`) et il n'existe pas d'**épinglage d'empreinte**. | Un attaquant placé sur le réseau entre Kaji et le nœud peut se faire passer pour Proxmox et **récupérer le jeton API**. Le certificat par défaut de Proxmox est auto-signé : activer `verify_ssl` ne marche que si Enzo installe un certificat valide. | Ajouter l'**épinglage de l'empreinte SHA-256** du certificat par connexion (retenue à la création, refus si elle change, avertissement affiché). C'est un lot de code à part (backend + écran « Connexions »), à faire avant d'ouvrir Kaji à d'autres réseaux. |
| **Moyenne** | **Kaji est servi en HTTP** sur le réseau (déploiement actuel : `http://192.168.1.214:8080` derrière le VPN). | Le mot de passe et le cookie de session circulent en clair (cookie `Secure` désactivé pour que cela marche en HTTP). | Mettre le TLS devant (Tailscale `serve`, Caddy, Traefik : `docs/deploiement.md`), puis remettre `KAJI_COOKIE_SECURE=true`. Gardé par le VPN aujourd'hui. |
| **Moyenne** | **La première configuration est ouverte** : `POST /api/auth/setup` crée le compte admin pour le premier venu tant qu'aucun compte n'existe. | Sur une installation neuve, quelqu'un qui joint le port avant le propriétaire prend le contrôle. | Créer le compte **tout de suite** après `docker compose up` (le déploiement actuel a déjà son compte). Option à coder : un `KAJI_SETUP_TOKEN` à fournir pour la première configuration. |
| Faible | Pas de **double authentification** pour se connecter à Kaji. | Un seul facteur (mot de passe) devant un outil qui pilote tout un cluster. | Annoncer « non fournie » (déjà dit dans `docs/deploiement.md`) ; TOTP en lot ultérieur. |
| Faible | Limiteur de connexions **en mémoire**, par IP. | Remis à zéro au redémarrage ; derrière un proxy non configuré, tous les clients partagent une IP. | Acceptable pour un usage perso ; documenté dans `docs/deploiement.md`. |
| Faible | Pas de jeton **CSRF** : la protection repose sur `SameSite=Strict` et sur le type JSON des requêtes. | Deux services sur le même hôte (ports différents) sont « du même site » pour le navigateur. | Ne pas héberger d'autre application non fiable sur le même nom d'hôte que Kaji. |
| Faible | L'adresse d'une connexion Proxmox est libre (l'admin peut viser n'importe quelle machine). | Un seul utilisateur, déjà administrateur : pas d'élévation possible. | Rien à faire tant qu'il n'y a pas de comptes multiples. |
| Info | Images de base désignées par étiquette, non par empreinte. | Reconstruction non reproductible. | Épingler les empreintes au moment de figer la V1. |

## Ce qui n'a pas été fait
- Pas de test d'intrusion actif, pas d'analyse de la configuration TLS de nginx (il n'y a pas de TLS dans le déploiement fourni), pas d'audit du code de Proxmox lui-même.
- Les droits du jeton de Kaji sur Proxmox : la page « Accès » compare ce qu'il a à ce que chaque fonction demande ; le principe du moindre privilège reste la décision d'Enzo (`docs/api/acces.md`).
