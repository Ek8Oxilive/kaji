# M6 : cadrage de l'écriture (utilisateurs, rôles, droits, tokens)

**Statut : cadrage, aucun code.** La lecture seule est livrée (page « Accès », `docs/api/acces.md`). Ce document dit si et
comment Kaji devrait **écrire** des droits dans Proxmox, avant d'en écrire une ligne. Il se termine par les décisions
qu'il faut prendre.

## 0. But du projet (précisé par le propriétaire)

**Kaji doit permettre de ne plus avoir à ouvrir l'interface de Proxmox.** Cela change l'éclairage de ce cadrage : gérer les
droits depuis Kaji n'est plus un confort, c'est une pièce du but. Le risque décrit plus bas **reste le même** ; ce qui change,
c'est qu'il faut le **maîtriser** au lieu de le refuser. L'interface de Proxmox reste utile comme **accès de secours** (si Kaji est
en panne, c'est la seule porte) et pour la création ou la jonction de nœuds (M10, que le plan juge plus sûre dans Proxmox).

## 1. Faits vérifiés sur le cluster réel (lecture seule, Proxmox 9.1.9)

- **Seul `Administrator` contient `Permissions.Modify`** parmi les rôles intégrés lus : `PVEAdmin` (40 privilèges) et
  `PVEUserAdmin` (3) ont `User.Modify`, `Group.Allocate` et `Realm.AllocateUser`, mais **pas** `Permissions.Modify`.
- Le token de Kaji **n'a ni `Permissions.Modify` ni `User.Modify`**. La liste des tokens d'un utilisateur lui est refusée (403).
- Aujourd'hui Kaji peut déjà beaucoup (administrer les machines et les stockages, `Sys.Modify` sur `/`) mais **il ne peut pas se
  donner de nouveaux droits ni en donner à quelqu'un d'autre**. C'est une barrière réelle, pas seulement une convention.

## 2. Ce qui change si Kaji écrit des droits

Écrire des ACL demande `Permissions.Modify` sur le chemin visé. **Un porteur de ce droit sur `/` peut s'attribuer `Administrator`
et créer un utilisateur ou un token de secours** : le compromis de Kaji (ou de son token) devient alors un compromis total et
**durable** du cluster, y compris après la révocation du token de Kaji. Les autres droits de Kaji sont déjà larges, mais ils
sont bornés et réversibles ; celui-ci ne l'est pas.

Deux points **à vérifier en bac à sable avant toute décision technique** (je ne les connais pas avec certitude) :
1. Proxmox empêche-t-il de déléguer des privilèges que l'on ne possède pas soi-même ? **On suppose que non**, par prudence.
2. Un `Permissions.Modify` posé seulement sur un sous-chemin (ex. `/pool/kaji-test`) borne-t-il bien ce que Kaji peut s'accorder ?

## 3. Trois options

| | A. Commandes à copier | B. Écriture bornée, droit limité | C. Écriture complète |
|---|---|---|---|
| Idée | Kaji **génère** les commandes `pveum` exactes (jamais exécutées) pour corriger un droit manquant ou préparer Proxmox | Kaji écrit, avec `Permissions.Modify` seulement sur des **sous-chemins choisis** (pool de test…) | Kaji écrit partout, avec `Permissions.Modify` sur `/` |
| Nouveau droit pour Kaji | **Aucun** | `Permissions.Modify` (+ `User.Modify`) borné | `Permissions.Modify` sur `/` ≈ `Administrator` |
| Risque si Kaji est compromis | **Inchangé** | Limité au sous-chemin (si le point 2 est vérifié) | **Total et durable** |
| Valeur | Élevée : c'est exactement ce qui nous a coûté du temps (héritage des ACL, `Sys.Modify`, pools invisibles) | Moyenne : peu d'usages courants hors du pool de test | Faible face à l'interface de Proxmox, qui le fait déjà bien |
| Effort / risque de développement | Faible, aucune écriture | Élevé | Très élevé |

### D. Option retenue pour le but « plus d'interface Proxmox » : **mode administrateur par session**

Le vrai danger n'est pas que Kaji écrive des droits, c'est qu'il **détienne en permanence** le droit de le faire. D'où une
quatrième option, qui combine B et C sans leur défaut :

- Le token **permanent** de Kaji reste **limité** (voire plus étroit qu'aujourd'hui, grâce au profil du lot A2). Il ne peut pas
  écrire de droits : un Kaji compromis **au repos** ne peut pas se donner de droits.
- Pour une action d'administration des droits, **tu t'identifies pour une courte session** (par exemple 15 minutes) : soit en te
  connectant à Proxmox avec ton compte (ticket Proxmox, comme l'interface native, sans stocker de mot de passe), soit en collant
  un token d'administration. L'identifiant vit **en mémoire du serveur, jamais en base ni dans un journal**, et expire seul.
- Les écritures s'exécutent **avec cette identité** ; l'audit de Kaji garde qui, quoi, quand, sans secret ; les garde-fous du §5
  s'appliquent en plus.

| | D. Mode administrateur par session |
|---|---|
| Nouveau droit permanent pour Kaji | **Aucun** |
| Risque si Kaji est compromis au repos | **Inchangé** (rien de stocké) ; risque seulement pendant une session ouverte |
| Valeur pour le but | **Élevée** : les droits se gèrent depuis Kaji, avec quelques secondes d'identification |
| Points à trancher | Ticket Proxmox (gérer l'authentification à deux facteurs de ton compte) ou token d'administration collé ; durée de session |
| Effort / risque de développement | Élevé (gestion de session sensible), mais mieux borné que B ou C |

**Recommandation mise à jour : A d'abord (rapide, sans nouveau droit), puis D pour l'écriture.** C (droit permanent sur `/`) reste
écartée ; B n'apporte plus rien si D est faite.

## 4. Lot A en détail (recommandé)

**A1. « Corriger un droit manquant »** : pour chaque fonction `missing` de la page Accès, un bouton « Voir la commande » affiche
la commande `pveum` à lancer **sur un nœud, en root**, avec un bouton copier. La commande est **construite côté serveur à partir
de constantes** (chemins, rôles) et de l'utilisateur de la connexion, validé ; aucune saisie libre n'entre dedans. Kaji
**n'exécute rien**. Exemple : `pveum aclmod / -user kaji@pve -role KajiSys` précédé de la création du rôle si besoin.

**A2. « Préparer Proxmox pour Kaji »** : un profil de droits **minimal** pour Kaji (un rôle personnalisé `KajiOperator` au lieu de
`PVEVMAdmin` + `PVEDatastoreAdmin` + `PVEPoolAdmin` + `PVEAuditor`…), affiché comme un petit script à copier, avec l'explication
de chaque privilège. Cela **réduit** les droits de Kaji aujourd'hui larges. Limite connue : la liste des privilèges nécessaires
(`accessspec.py`, `FEATURES`) vient de la documentation et d'un seul constat réel ; **elle doit être éprouvée en retirant chaque
droit un par un en bac à sable** avant d'être proposée comme « minimale ». Tant que ce n'est pas fait, le profil s'appelle
« recommandé », pas « minimal ».

**Garde-fous du lot A** : commandes construites sur liste blanche ; l'utilisateur et le jeton vérifiés par la même regex que les
connexions ; jamais de secret dans une commande ; chaque affichage de commande **n'est pas** une écriture (pas d'audit
nécessaire, mais le contenu est testé) ; tests « avec des dents » (une commande avec un caractère interdit est refusée, une
commande ne contient jamais `Administrator` ni `/` avec `Permissions.Modify`).

## 5. Garde-fous non négociables pour toute écriture de droits (options B, C ou D)

À figer **avant** d'écrire du code, et chacun doit avoir un test qui échoue s'il est retiré :
1. **Identifiants séparés** : l'écriture de droits passe par une **identité de session** (§D), **jamais stockée**, distincte du
   token permanent des machines, pour qu'un Kaji compromis au repos ne puisse pas écrire.
2. **Interdits absolus, vérifiés côté serveur** : toucher aux entrées ACL de Kaji lui-même, supprimer ou désactiver `root@pam` ou
   le compte de Kaji, accorder `Administrator` ou tout rôle contenant `Permissions.Modify`, écrire sur `/` ou `/access`.
3. **Liste blanche de chemins** et de rôles (configurée, pas libre) ; rien d'autre n'est transmis à Proxmox.
4. **Aperçu avant application** : la réponse dit « voici les droits effectifs avant/après » ; l'écriture exige `confirm=true`
   **et** le nom exact de l'utilisateur ou du chemin retapé.
5. **Pas de suppression en masse** ; une entrée à la fois ; audit de chaque écriture, refus et erreur, **sans secret**.
6. **Secret d'un token** affiché **une seule fois**, jamais journalisé, jamais renvoyé par une autre route.
7. Validation en réel **uniquement sur un utilisateur et un chemin jetables** du bac à sable, jamais sur un compte existant.

## 6. Découpage proposé

| Lot | Contenu | Qui | Risque |
|---|---|---|---|
| **M6-3** | A1 : commandes de correction (API + bouton dans la page Accès) | PC A | Faible |
| **M6-4** | Éprouver chaque privilège en bac à sable, puis profil recommandé / minimal (A2) | PC A | Faible, mais demande des essais réels |
| **M6-5** | Vérifier les deux points du §2 en bac à sable (utile pour borner le mode administrateur) | PC A | Faible, essais réels |
| **M6-6** | **Mode administrateur par session** (§D) : socle (identification, expiration, jamais stocké) | PC A | Élevé |
| **M6-7+** | Écriture des droits et des tokens par-dessus M6-6, avec les garde-fous du §5 ; une écriture à la fois | PC A | Élevé |

## 7. Décisions à prendre

1. **Lot A (commandes à copier + profil recommandé) : on le fait en premier ?** *(recommandé : oui)*
2. **Écriture des droits : on prend l'option D (mode administrateur par session) ?** *(recommandé : oui, après le lot A)*
3. **Identification de la session : ton compte Proxmox (ticket, avec gestion de ton éventuelle double authentification) ou un token
   d'administration collé ?** *(à discuter : le ticket est plus proche de l'interface native, le token est plus simple à écrire)*
4. **Durée de session** *(proposé : 15 minutes, renouvelable)*.
