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
| `clear` | `keyboard`, `language`, `console`, `description`, `mac_prefix`, `migration`, `max_workers`, `email_from`, `http_proxy`, `next_id`, `tag_style` (envoyé en `delete=`, `next_id` et `tag_style` devenant `next-id` et `tag-style`) |

**Lus mais jamais écrits** (`readonly` dans la lecture) : `ha`, `fencing`, `crs`, `bwlimit`, `replication` : risque élevé (HA, fencing, ordonnancement) ou hors périmètre. Tout champ inconnu ou hors liste est **ignoré**, jamais transmis.

## Verrous
- **`digest`** : Proxmox n'a pas de `digest` pour ces options. Kaji calcule le sien (empreinte des valeurs lues) ; `GET` le renvoie, `PUT` accepte `digest` et répond **409** si l'état a changé depuis (rien n'est écrit). Facultatif pour l'API, toujours envoyé par la page.
- **Migration non chiffrée** : passer `type` à `insecure` (depuis `secure` ou sans réglage) exige `confirm=true` (409 sinon) : la mémoire des machines circulerait en clair.
- `dry_run=true` : renvoie `params`, `remove`, `locks.insecure` ; n'écrit rien. Rien à modifier = 422.
- Après l'écriture, l'état est **relu** (502 si Proxmox n'a pas appliqué ; les notes sont comparées sans le saut de ligne final que Proxmox ajoute).

## Audit
Action `datacenter-options`, refus compris ; le contenu des notes n'est jamais copié (« défini »).

## Validation
Faux Proxmox strict (`backend/tests/test_datacenter.py`), 31 mutations.

## Constaté en réel (2026-11-09)
- `GET /cluster/options` renvoie ici `keyboard` (`fr`), `mac_prefix` (`BC:24:11`) et `description` (chaîne vide) ; `migration` absent tant qu'il n'est pas réglé.
- **Les notes écrites reviennent avec un saut de ligne final** (`"…\n"`) : comparées sans lui.
- **Retirer les notes (`delete=description`) laisse `description` à `""`** (clé présente, vide), pas absente : la relecture l'accepte (bug trouvé et corrigé par cet essai).
- Essais faits par l'interface web : clavier `fr` → `de` → `fr` (état identique à l'origine, même empreinte), notes écrites puis vidées. Refus constatés sans appel Proxmox : `max_workers` 0 et 500, préfixe MAC multicast, proxy avec identifiants / en `127.0.0.1` / en `https`, réseau avec bits d'hôte, clavier inconnu, requête vide (422) ; `digest` périmé et migration non chiffrée sans `confirm` (409).
