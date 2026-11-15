# Rôles par périmètre : restreindre un compte à un groupe de machines (jalon J2, ticket #447)

Un compte de Kaji (opérateur ou lecture seule) peut être **restreint à un groupe de machines** : il ne voit et ne touche que celles-ci. C'est le **serveur** qui décide, à chaque requête (`app/scope.py`, branché dans la session après la politique des rôles) ; l'interface ne fait que refléter. Le rôle (`docs/api/roles-kaji.md`) s'applique **en plus** : un opérateur restreint ne fait que démarrer, arrêter, redémarrer, créer un snapshot, et seulement sur SES machines.

## Principe : tout est refusé par défaut
Pour un compte restreint, n'est permis que ce que `app/scope.py` liste explicitement :

| Permis | Condition |
|---|---|
| Libre-service : `/api/auth/…`, `/api/me/…` (changer son mot de passe, son TOTP, son jeton Proxmox) | toujours (le rôle décide du reste) |
| `GET /api/connections` | **filtrée** aux connexions de son périmètre |
| `GET …/guests` et `GET …/events` (flux temps réel) | connexion dans son périmètre ; **filtrés** aux machines du périmètre |
| Toute route d'UNE machine : `…/guests/{nœud}/{qemu\|lxc}/{vmid}/…` et `…/firewall/guests/…` | `vmid` dans le périmètre de cette connexion |
| `GET …/tasks/{nœud}/{upid}` et `…/log` | la tâche est une tâche de machine (`qm…`, `vz…`, consoles) **dont le vmid est dans le périmètre** |

**Tout le reste est refusé** (403, audité `scope-refused`, **avant tout appel à Proxmox**) : stockage, réseau, droits, tâches du cluster, HA, alertes, planifications, audit, connexions (écriture), administration. Une route ajoutée plus tard est donc refusée pour ces comptes tant qu'on ne la déclare pas : `tests/test_scope.py` passe **toutes les routes de l'application** à la politique (≈ 370) et vérifie qu'elles sont refusées sauf la liste ci-dessus, dans le périmètre comme hors périmètre.

Chemins louches refusés : `..`, `//`, caractères hors ASCII ou de contrôle, tâche dont l'identifiant numérique n'est pas une machine (par exemple `cephstartosd:115`).
**Un administrateur n'a jamais de périmètre** (refusé à la création, effacé s'il est promu).

## Le flux temps réel
Un compte restreint reçoit **son propre canal**, jamais le flux commun : chaque instantané est réduit aux machines du périmètre et aux nœuds qui les portent, **sans l'état du cluster** (quorum, adresses des nœuds, nom). Le périmètre est relu à chaque tour : modifié ou retiré, il s'applique tout de suite ; retiré, le flux ne diffuse **rien** (jamais l'état complet).

## Gérer un périmètre (administrateurs seulement)
| Route | Rôle |
|---|---|
| `GET /api/kaji-users/{id}/scope` | `{restricted, entries: [{conn_id, vmids}]}` |
| `PUT /api/kaji-users/{id}/scope` `{entries: [{conn_id, vmids}]}` | **remplace** le périmètre ; jamais pour un administrateur (409) ; connexions connues, sans doublon ; `vmids` : entiers stricts de 1 à 999 999 999, sans doublon, 500 au plus par connexion, 20 connexions au plus ; **liste vide refusée (422)** : retirer la restriction est une action à part |
| `DELETE /api/kaji-users/{id}/scope?confirm=true&name=…` | retire la restriction (élargit les droits : `confirm` + nom retapé) ; 409 s'il n'y en a pas |

Un opérateur ne peut pas modifier son propre périmètre (403). Promouvoir un compte en administrateur efface son périmètre (sinon il réapparaîtrait à la rétrogradation) ; supprimer un compte efface le sien. Audit : `kaji-user-scope`, `kaji-user-scope-clear`, `scope-refused`. `GET /api/auth/me` renvoie `restricted`, et `GET /api/kaji-users` renvoie `scoped` par compte.

Interface : « Compte » → « Gérer les utilisateurs… » → **« Périmètre… »** (cases à cocher par connexion). « Ajouter les machines du pool » ajoute d'un coup celles que le pool contient **maintenant** : le périmètre garde des machines, **pas le pool** (un pool modifié ensuite ne le change pas : résoudre un pool à chaque requête exigerait un appel à Proxmox par requête, donc une authentification asynchrone). Un compte restreint n'a que le tableau de bord et les pages de ses machines : menu réduit, pas de barre de tâches, pas de page Nœud.

## Limites connues
- **Pas de pool dynamique** (voir plus haut) : un groupe de machines explicite.
- **Les onglets d'une machine** appellent parfois des routes globales (par exemple la liste des stockages pour ajouter un disque) : un opérateur ou un lecteur restreint les voit alors **en erreur 403**, sans rien exposer. Les fonctions de lecture et d'alimentation de ses machines marchent.
- **L'onglet « Permissions »** d'une machine liste les droits Proxmox qui s'y appliquent (noms d'utilisateurs, de jetons) : un compte restreint les lit pour SES machines (un lecteur non restreint les lisait déjà pour toutes).
- **Le périmètre limite l'accès à KAJI, pas à Proxmox** : les actions partent avec le jeton partagé de la connexion (ou avec le jeton personnel du compte, `docs/api/jetons-utilisateur.md` si présent : alors Proxmox applique en plus SES droits).
- Un compte restreint **ne voit pas les nouvelles machines** tant qu'on ne les ajoute pas ; une machine supprimée reste dans la liste (« absente du cluster ») jusqu'à retrait.
- Les consoles (WebSocket) restent réservées aux administrateurs (politique des rôles).
- Le périmètre est **par connexion** ; un compte restreint ne voit aucune connexion où il n'a pas de machine.

## Tests
`backend/tests/test_scope.py` (476 tests) : politique pure (accepté et refusé, ~60 chemins dont les tours de passe-passe), **balayage de toutes les routes de l'application** (dans et hors périmètre), de bout en bout sur un faux Proxmox (liste filtrée, connexions filtrées, pages globales refusées et auditées avant tout appel, un opérateur n'agit que sur sa machine et le rôle s'applique en plus, un lecteur lit mais n'agit pas, effet immédiat d'un changement de périmètre, administrateur jamais restreint même avec des lignes parasites, journal d'une tâche d'une autre machine), flux (canal propre, interrogateur filtré, plus rien après retrait), API de gestion (validation stricte, jamais pour un administrateur, liste vide refusée, retrait confirmé, seuls les administrateurs, promotion et suppression). **38 mutations testées, 37 tuées** (5 survivantes d'abord, comblées ; 1 équivalente : le contrôle `//`, que la regex des routes refuse déjà).
**Un défaut trouvé par les tests** : `true` était accepté comme identifiant de machine (converti en 1) ; entiers stricts depuis.
**Jamais vu** : sur le déploiement réel, avec un vrai pool, dans le navigateur (compte restreint) ; l'interface en anglais.
