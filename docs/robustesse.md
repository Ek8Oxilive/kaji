# Robustesse : Proxmox lent ou injoignable, utilisateurs simultanés

Jalon J3 (`docs/cadrage-prod-entreprise.md`, ticket #457). Ce que Kaji fait quand Proxmox ralentit, ne répond plus ou répond n'importe quoi, et **combien de requêtes simultanées il encaisse** : des chiffres **mesurés**, avec leurs limites. **Ce n'est pas une promesse de capacité.**

## Ce que la mesure a révélé, et qui est corrigé
Écrire les tests et les mesures a trouvé **trois défauts réels** (corrigés dans ce lot) :

| Défaut constaté | Avant | Maintenant |
|---|---|---|
| Proxmox (ou un proxy, un portail captif, une mauvaise adresse) répond **200 avec autre chose que du JSON Proxmox** | exception non gérée : **erreur 500 brute** | **502** « Réponse inattendue : ce n'est pas l'API de Proxmox… » (`ProxmoxProtocolError`) ; le corps reçu n'est jamais recopié |
| Plus de **15 requêtes lentes** vers Proxmox en même temps : chacune garde sa connexion à la base pendant qu'elle attend, le **pool (15) se sature** | **tout se bloque 30 s**, y compris les pages qui n'ont pas besoin de Proxmox, puis des 500 | pool relevé à 150 (`app/db.py`) |
| Au-delà de 150 requêtes en cours, les threads attendent tous une connexion alors que celles qui en détiennent ne peuvent pas finir (plus de thread libre) : **blocage total** | 200 utilisateurs : **0 % de réussite**, des 500 et des blocages de 60 s | **limite de requêtes simultanées** (`KAJI_MAX_CONCURRENT_REQUESTS`, 100) : au-delà, **503 immédiat** avec `Retry-After`, le reste continue de répondre |

## Méthode
`tools/load_test.py` démarre le **vrai backend** (un seul worker uvicorn, base SQLite fichier jetable) et un **faux Proxmox HTTPS** local (`tools/fake_proxmox.py`, latence et pannes réglables), crée un compte et une connexion, puis N utilisateurs simulés **rechargent sans aucune pause** les quatre routes du tableau de bord (état, nœuds, machines, stockages) pendant 6 s. C'est un **cas pire** : un vrai utilisateur fait une requête par seconde ou moins.

- Machine : Linux-7.2.14-arch1-1-x86_64-with-glibc2.44, 8 cœurs, Python 3.14.9, **1 worker**, 2026-11-14. Le faux Proxmox est sur la **même machine** : pas de latence réseau, pas de vrai cluster.
- Rejouer : `backend/.venv/bin/python tools/load_test.py` (ou `--healthy-only --users 10,50` pour un essai court).

## Résultats mesurés
| Scénario | requêtes | req/s | 200 | p50 | p95 | p99 | max | codes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| sain, 1 utilisateur(s) | 518 | 86.4 | 100.0 % | 11 ms | 14 ms | 15 ms | 59 ms | {'200': 518} |
| sain, 10 utilisateur(s) | 668 | 110.6 | 100.0 % | 89 ms | 103 ms | 118 ms | 137 ms | {'200': 668} |
| sain, 50 utilisateur(s) | 666 | 107.6 | 100.0 % | 453 ms | 591 ms | 650 ms | 718 ms | {'200': 666} |
| sain, 100 utilisateur(s) | 1059 | 167.5 | 62.1 % | 906 ms | 1008 ms | 1383 ms | 1501 ms | {'200': 658, '503': 401} |
| sain, 150 utilisateur(s) | 485 | 66.4 | 85.2 % | 1411 ms | 5825 ms | 6476 ms | 7033 ms | {'503': 72, '200': 413} |
| sain, 200 utilisateur(s) | 513 | 65.2 | 78.0 % | 1914 ms | 6851 ms | 7339 ms | 7542 ms | {'503': 112, '200': 400, '0': 1} |
| Proxmox lent (0,5 s), 50 utilisateurs | 445 | 66.9 | 100.0 % | 752 ms | 878 ms | 938 ms | 956 ms | {'200': 445} |
| Proxmox très lent (3 s), 50 utilisateurs | 200 | 14.9 | 100.0 % | 3308 ms | 3455 ms | 3466 ms | 3485 ms | {'200': 200} |
| Proxmox répond 500, 25 utilisateurs | 682 | 112.0 | 0.0 % | 223 ms | 238 ms | 265 ms | 325 ms | {'502': 682} |
| Proxmox répond une page HTML, 25 utilisateurs | 658 | 107.9 | 0.0 % | 225 ms | 308 ms | 348 ms | 387 ms | {'502': 658} |
| Proxmox bloqué (30 utilisateurs, 20 s) | 60 | 2.0 | 0.0 % | 15216 ms | 15269 ms | 15270 ms | 15277 ms | {'504': 60} |
|   pendant ce blocage : pages sans Proxmox `/api/health` | 38 | 1.9 | 100.0 % | 11 ms | 15 ms | 33 ms | 33 ms | {'200': 38} |
|   pendant ce blocage : pages sans Proxmox `/api/auth/me` | 38 | 1.9 | 100.0 % | 7 ms | 15 ms | 106 ms | 106 ms | {'200': 38} |
| Proxmox en panne (connexion refusée), 25 utilisateurs | 977 | 161.2 | 0.0 % | 155 ms | 187 ms | 218 ms | 262 ms | {'502': 977} |
| après la panne, 10 utilisateurs (reprise) | 665 | 110.2 | 100.0 % | 90 ms | 102 ms | 109 ms | 116 ms | {'200': 665} |

Flux temps réel : 50 clients pendant 10 s → 50 événements reçus (au moins 1 par client), **9 appels à Proxmox au total** (0.18 par client : un seul interrogateur est partagé).

## Ce qu'on peut en conclure (et ce qu'on ne peut pas)
- **Débit** : environ **110 requêtes/s par worker** sur cette machine, quel que soit le nombre d'utilisateurs entre 10 et 100 ; la latence grandit alors proportionnellement (50 utilisateurs sans pause : p50 ≈ 0,45 s). **Ordre de grandeur, déduit** : à une requête par seconde et par utilisateur actif, un worker sert **de l'ordre d'une centaine d'utilisateurs actifs** sur cette machine ; non vérifié avec de vrais utilisateurs ni de vrais écrans.
- **Au-delà de 100 requêtes en cours** : les nouvelles reçoivent un **503 clair et immédiat** plutôt que de tout bloquer ; à 200 utilisateurs sans pause, 78 % de réussites, aucune erreur 500, pas de blocage de 60 s. La latence des requêtes acceptées reste de l'ordre de quelques secondes.
- **Proxmox lent** (0,5 s ou 3 s) : toutes les requêtes réussissent, plus lentement ; le débit chute en proportion (≈ 15 req/s à 3 s avec 50 utilisateurs), **les pages qui n'ont pas besoin de Proxmox ne ralentissent pas**.
- **Proxmox bloqué** (ne répond jamais) : chaque requête échoue en **504 après 15 s** (délai du client de Kaji) ; pendant ce temps `/api/health` et `/api/auth/me` répondent en **≈ 10 ms**.
- **Proxmox en panne** (connexion refusée) : **502 en ≈ 150 ms** ; il répond de nouveau **tout de suite** après le retour de Proxmox (aucun état collant : la ligne « reprise »).
- **Proxmox répond 500 ou du HTML** : 502 clair en ≈ 0,2 s, jamais de 500 ni de corps recopié.
- **Flux temps réel** : 50 clients connectés pendant 10 s ne provoquent que **9 appels à Proxmox** : **un seul interrogateur partagé** par connexion tant que tout le monde utilise le jeton partagé (un utilisateur à jeton personnel a son propre flux : `docs/api/jetons-utilisateur.md`).

## Limites de cette mesure (à lire avant de citer un chiffre)
- **Une seule machine, un seul worker**, faux Proxmox local sans vraie latence ni vraie charge côté Proxmox : les chiffres valent pour **cette** machine, pas pour votre cluster. Un vrai Proxmox est plus lent à répondre : le débit utile est plus bas.
- **Jamais mesuré** avec de vrais navigateurs, de vraies sessions longues, des consoles WebSocket ouvertes, des actions d'écriture, ni dans Docker avec HTTPS (Caddy) devant.
- **Limite connue qui reste** : une requête **garde sa connexion à la base pendant qu'elle attend Proxmox** (la session de la requête reste ouverte). Le pool et la limite de requêtes simultanées rendent cela sans danger pour l'usage visé, mais c'est une limite de conception : la supprimer demanderait de relire les ~180 appels à Proxmox.
- **Un seul worker, imposé** : le flux temps réel, le planificateur et les alertes vivent en mémoire (`docs/deploiement.md`) ; on ne gagne pas en capacité en lançant plusieurs workers.
- La **toute première requête** d'un processus coûte **0,4 à 1,4 s** selon la machine (FastAPI construit alors le routage de ses ~650 routes, mesuré au profil) ; en exploitation la sonde de santé de Docker (toutes les 15 s) réchauffe l'application au démarrage.
- Le faux Proxmox a lui-même faussé deux de mes premières mesures (un délai de 40 ms par réponse dû à l'algorithme de Nagle, et une file de connexions de 5 seulement) ; les deux sont corrigés dans l'outil et les chiffres ci-dessus sont ceux d'après correction.

## Réglages
| Variable | Rôle |
|---|---|
| `KAJI_MAX_CONCURRENT_REQUESTS` | requêtes HTTP simultanées au plus (hors `/api/health`, flux temps réel `…/events` et WebSocket) ; au-delà : 503 tout de suite ; `0` = pas de limite (défaut **100**, sous le pool de 150) |

Le délai de Kaji vers Proxmox est de **15 s** (fixe, `app/proxmox.py`) ; le pool de connexions à la base est de **50 + 100 de débordement** (fixe, `app/db.py`).

## Supervision
Quand Kaji est surchargé, il le **dit dans ses journaux** (`surcharge : N requêtes en cours (limite 100), M refusées depuis le démarrage`, au plus un message toutes les 10 s) et répond **503** avec `Retry-After: 2`. Un 503 répété = trop de monde pour un worker, ou un Proxmox si lent que les requêtes s'empilent (regarder d'abord Proxmox).
