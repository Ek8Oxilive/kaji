# M6 : cadrage de l'écriture (utilisateurs, rôles, droits, tokens)

**Statut : cadrage, aucun code.** La lecture seule est livrée (page « Accès », `docs/api/acces.md`). Ce document dit si et
comment Kaji devrait **écrire** des droits dans Proxmox, avant d'en écrire une ligne. Il se termine par les décisions
qu'il faut prendre.

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

**Recommandation : A d'abord, B seulement si un besoin réel apparaît, C non.** L'interface de Proxmox gère déjà très bien les
utilisateurs et les droits ; l'ajouter à Kaji ajouterait surtout une surface d'attaque. En revanche, **expliquer** les droits et
**préparer** Proxmox pour Kaji sont de vrais manques, et ils n'ont besoin d'aucun nouveau privilège.

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

## 5. Si l'option B est choisie plus tard : garde-fous non négociables

À figer **avant** d'écrire du code, et chacun doit avoir un test qui échoue s'il est retiré :
1. **Identifiants séparés** : l'écriture de droits passe par un **second token**, saisi pour la session et **jamais stocké**
   (ou à défaut, un token dédié aux droits, distinct de celui des machines), pour qu'un Kaji compromis au repos ne puisse pas écrire.
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
| **M6-5** | Vérifier les deux points du §2 en bac à sable, et **décider** de B | Propriétaire + PC A | — |
| *(éventuel)* **M6-6+** | Écriture bornée (§5), seulement si M6-5 conclut à un besoin et à un risque acceptable | À décider | Élevé |

## 7. Décisions à prendre

1. **Lot A (commandes à copier + profil recommandé) : on le fait ?** *(recommandé : oui)*
2. **Écriture de droits dans Kaji : on y renonce, ou on garde l'option B pour plus tard ?** *(recommandé : on la garde en réserve,
   sans rien développer tant qu'un besoin concret n'existe pas)*
3. **Si B un jour :** token séparé non stocké, ou rien. *(recommandé : token séparé non stocké)*
