# Options et notes du datacenter (M15, lot #150)

Préfixe `/api/connections/{conn_id}/datacenter`. Page « Datacenter » du menu. Droits Proxmox : `Sys.Audit` sur `/` (lire), `Sys.Modify` sur `/` (écrire) ; page « Accès » : `datacenter-write`.

| Route | Effet |
|---|---|
| `GET /options` | Champs gérés + champs en lecture seule + `digest` |
| `PUT /options` | Modifie (liste blanche), retire (`clear`), `dry_run` |

## Champs gérés
| Champ | Valeurs |
|---|---|
| `keyboard`, `language`, `console` | listes blanches de Proxmox (`console` : `applet`, `vv`, `html5`, `xtermjs`) |
| `description` | **Notes du datacenter** (≤ 65 536 caractères, `\n` et `\t` permis, aucun autre caractère de contrôle) |
| `mac_prefix` | `XX:XX:XX`, premier octet pair (unicast) ; mis en majuscules |
| `max_workers` | entier 1 à 64 |
| `email_from` | adresse e-mail simple |
| `http_proxy` | `http://hôte[:port]` : pas de `https`, **pas d'identifiants**, pas de chemin ni de paramètres ; boucle locale (`127.x`, `::1`, `localhost`, `*.localhost`), adresse non spécifiée, liaison locale et multicast refusées (un proxy du réseau privé reste permis) |
| `migration` | `{type: secure|insecure, network: CIDR}` ; réseau sans bits d'hôte ; `network: ""` retire le réseau ; fusionné avec l'état lu (changer le type garde le réseau) |
| `next_id` | **Plage des identifiants libres** : `{lower, upper}`, entiers 100 à 999 999 999 (booléens, chaînes et décimaux refusés), `lower` < `upper` (contrôlé aussi contre la valeur courante : changer `lower` seul garde `upper`) ; envoyé `next-id=lower=L,upper=U` |
| `tag_style` | **Style des étiquettes** : `shape` (`full`, `circle`, `dense`, `none`), `ordering` (`config`, `alphabetical`), `case_sensitive` (booléen strict), `color_map` (liste `{tag, color, text?}` : étiquette `[A-Za-z0-9_][A-Za-z0-9_.+-]{0,31}`, couleurs de 6 chiffres hexadécimaux, 50 au plus, doublons refusés ; **remplace toute la table**, liste vide = la retirer) ; sous-réglages fusionnés avec l'état lu ; envoyé `tag-style=shape=…,ordering=…,case-sensitive=1,color-map=nom:couleur[:texte];…` |
| `registered_tags` | **Étiquettes réservées** (modifiables seulement avec `Sys.Modify`) : liste de 100 au plus, chacune `[a-z0-9_][a-z0-9_.+-]{0,63}` (mise en minuscules, doublons écartés) ; liste vide = retirer le réglage ; envoyé `registered-tags=a;b` |
| `user_tag_access` | **Droits des utilisateurs sur les étiquettes** : `user_allow` (`none`, `list`, `existing`, `free`) et `user_allow_list` (étiquettes, utile seulement avec `list`, qui en exige au moins une ; la liste courante est gardée si on ne la renvoie pas) ; envoyé `user-tag-access=user-allow=list,user-allow-list=a;b` |
| `consent_text` | **Texte de consentement** affiché à tous avant la connexion : 3000 caractères au plus, `\n` et `\t` permis, aucun autre caractère de contrôle ; vide = retirer ; **jamais copié dans l'audit ni dans l'aperçu** (« défini ») |
| `ha` | **Haute disponibilité** (lot #365) : `{shutdown_policy: freeze|failover|conditional|migrate}` ; envoyé `ha=shutdown_policy=…` |
| `fencing` | **Mode de fencing** : `watchdog`, `hardware`, `both` (les deux derniers sont « EXPERIMENTAL & WIP » chez Proxmox) |
| `crs` | **Ordonnancement des ressources** : `{ha: basic|static, ha_rebalance_on_start: booléen strict}` ; fusionné avec l'état lu (changer le mode garde l'indicateur, et inversement) ; envoyé `crs=ha=static,ha-rebalance-on-start=1` |
| `bwlimit` | **Limites de débit** en Kio/s : `clone`, `default`, `migration`, `move`, `restore`, entiers 0 à 1 000 000 000 (décimaux, booléens, chaînes et négatifs refusés) ; les clés non renvoyées sont **gardées**, `remove: ["move", …]` en retire, plus aucune clé = réglage retiré ; envoyé `bwlimit=default=1000,move=500` (ordre du schéma) |
| `replication` | **Réseau de réplication** : même forme que `migration` (`type` secure / insecure, `network` CIDR sans bits d'hôte, `""` = retirer le réseau) ; fusionné avec l'état lu |
| `clear` | `keyboard`, `language`, `console`, `description`, `mac_prefix`, `migration`, `max_workers`, `email_from`, `http_proxy`, `next_id`, `tag_style`, `registered_tags`, `user_tag_access`, `consent_text`, `ha`, `fencing`, `crs`, `bwlimit`, `replication` (envoyé en `delete=` sous le nom Proxmox : `next-id`, `tag-style`, `registered-tags`, `user-tag-access`, `consent-text`) |

**Lecture seule** (`readonly` dans la lecture) : seulement ce que Kaji ne sait pas écrire sans le casser : une **sous-clé inconnue** de `ha`, `crs`, `bwlimit` ou `replication` (Proxmox plus récent) ou un mode de `fencing` inconnu. Un `PUT` remplace la chaîne entière : modifier ou retirer un réglage qui porte une sous-clé inconnue est **refusé (422)** plutôt que de la perdre. Tout champ inconnu ou hors liste est **ignoré**, jamais transmis. Schéma lu sur `apidoc.js` de Proxmox 9 (`PUT /cluster/options`).

## Verrous
- **`digest`** : Proxmox n'a pas de `digest` pour ces options. Kaji calcule le sien (empreinte des valeurs lues) ; `GET` le renvoie, `PUT` accepte `digest` et répond **409** si l'état a changé depuis (rien n'est écrit). Facultatif pour l'API, toujours envoyé par la page.
- **Migration non chiffrée** : passer `type` à `insecure` (depuis `secure` ou sans réglage) exige `confirm=true` (409 sinon) : la mémoire des machines circulerait en clair.
- **Réglage de la HA** (`ha`, `crs`, `fencing`, ou les retirer avec `clear`) : exige `confirm=true` (409 sinon) : il change ce que fait la HA à l'arrêt d'un nœud, à la reprise ou au placement des machines. Décidé par le serveur, pas seulement par la page.
- **Fencing matériel** (`hardware` ou `both`, depuis un autre mode) : en plus de `confirm`, `acknowledge_cut_access=true` et `type_name="COUPURE POSSIBLE"` (409 sinon) : sans appareils dans `/etc/pve/ha/fence.cfg`, que Kaji ne peut pas lire, la HA ne reprend plus les machines d'un nœud tombé.
- **Réplication non chiffrée** : passer `type` à `insecure` (depuis `secure` ou sans réglage) exige `confirm=true`.
- `bwlimit` et une réplication chiffrée n'exigent aucune confirmation (réversibles, sans coupure).
- `dry_run=true` : renvoie `params`, `remove` et `locks` (`insecure`, `replication_insecure`, `ha`, `fencing_experimental`) ; n'écrit rien. Rien à modifier = 422. La page l'appelle toujours d'abord et n'affiche la confirmation que si un verrou est levé.
- Après l'écriture, l'état est **relu** (502 si Proxmox n'a pas appliqué ; les notes sont comparées sans le saut de ligne final que Proxmox ajoute).

## Audit
Action `datacenter-options`, refus compris ; le contenu des notes n'est jamais copié (« défini »).

## Constaté en réel (2026-11-13, lot #365)
Cluster sans ressource HA, les cinq réglages absents au départ ; tout a été retiré à la fin (même `digest` qu'au départ, watchdog de la HA resté en `standby`).
- Débit : `bwlimit=restore=100000` écrit par la page puis relu ; ajouter `migration` garde `restore` ; retirer les deux clés supprime le réglage.
- Réplication : `type=secure,network=…` écrit, réseau retiré, réglage retiré ; `insecure` sans `confirm` : 409.
- CRS `static` par la page (aperçu, panneau, case de confirmation) puis `ha-rebalance-on-start` ajouté en gardant le mode ; `ha.shutdown_policy` et `fencing=watchdog` : 409 sans `confirm`, acceptés avec ; `clear` des trois avec `confirm`.
- Fencing `hardware` / `both` : 409 sans la phrase `COUPURE POSSIBLE` (le mode n'a pas changé) ; l'aperçu annonce `fencing_experimental`. **Jamais écrit.**
- Le format renvoyé par Proxmox est lu correctement par le parseur (`readonly` resté vide), mais le format brut (objet ou chaîne) n'a pas été noté.
- Non essayé : effet d'un débit sur une migration, `shutdown_policy` ou CRS avec de vraies ressources HA.

## Validation
Faux Proxmox strict (`backend/tests/test_datacenter.py`), 31 mutations.

## Constaté en réel (2026-11-09)
- `GET /cluster/options` renvoie ici `keyboard` (`fr`), `mac_prefix` (`BC:24:11`) et `description` (chaîne vide) ; `migration` absent tant qu'il n'est pas réglé.
- **Les notes écrites reviennent avec un saut de ligne final** (`"…\n"`) : comparées sans lui.
- **Retirer les notes (`delete=description`) laisse `description` à `""`** (clé présente, vide), pas absente : la relecture l'accepte (bug trouvé et corrigé par cet essai).
- Essais faits par l'interface web : clavier `fr` → `de` → `fr` (état identique à l'origine, même empreinte), notes écrites puis vidées. Refus constatés sans appel Proxmox : `max_workers` 0 et 500, préfixe MAC multicast, proxy avec identifiants / en `127.0.0.1` / en `https`, réseau avec bits d'hôte, clavier inconnu, requête vide (422) ; `digest` périmé et migration non chiffrée sans `confirm` (409).
