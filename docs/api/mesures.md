# Historique des mesures (graphiques)

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/nodes/{node}/metrics?timeframe=` | Processeur, charge, mémoire, swap et réseau d'un nœud dans le temps |
| `GET /api/connections/{id}/guests/{node}/{type}/{vmid}/metrics?timeframe=` | Processeur, mémoire, réseau et disque d'une machine (`type` : `qemu` ou `lxc`) |

Lecture seule (`GET` seulement, droit `Sys.Audit` déjà accordé). `timeframe` : `hour` (défaut), `day`, `week`, `month` ou `year` ; toute autre
valeur donne **422** et rien n'est envoyé à Proxmox. Les données viennent du RRD de Proxmox (`rrddata`, moyenne).

Réponse : `{"timeframe", "step", "points": [...]}`. `step` : écart typique entre deux points, en secondes (`null` s'il y a moins de deux points).

| Champ d'un point (nœud) | Sens |
|---|---|
| `t` | Horodatage (secondes depuis 1970) |
| `cpu`, `iowait` | Fractions de la capacité (0 à 1) |
| `load` | Charge moyenne du système |
| `mem_used`, `mem_total`, `swap_used`, `swap_total` | Octets |
| `net_in`, `net_out` | Octets par seconde |

| Champ d'un point (machine) | Sens |
|---|---|
| `t`, `cpu` | Comme ci-dessus (`cpu` : 1 = tous les vCPU) |
| `cpus` | Nombre de vCPU |
| `mem_used`, `mem_total` | Octets |
| `net_in`, `net_out`, `disk_read`, `disk_write` | Octets par seconde |

Règles de prudence :
- **Liste blanche** : les autres champs de Proxmox (pressions, `arcsize`…) ne sont pas repris.
- **Une valeur absente, non numérique, `NaN`, infinie ou négative devient `null`, jamais 0** : une machine arrêtée donne un **trou**, pas une courbe à zéro.
  Un zéro mesuré reste un zéro. Les horodatages absurdes (avant 1970 ou après 2100) et les doublons de date sont écartés ; les points sont triés.
- **Réduction à 400 points au plus** (moyenne par tranche, les valeurs absentes sont ignorées, une tranche entièrement vide reste vide : le trou est conservé).
  Proxmox renvoie jusqu'à 1440 points ; sans réduction la page ralentirait.
- Une réponse de Proxmox qui n'est pas une liste donne `points: []`. Une erreur de Proxmox est traduite en 502 ou 504, jamais en graphique vide.

## Interface

Un composant de graphique **sans dépendance** (SVG), conforme au guide de visualisation du projet : une seule échelle par graphique, lignes de 2 px, quadrillage
discret, lavis de 10 % pour une série seule, **survol** (trait vertical et infobulle avec toutes les séries), **clavier** (flèches, Échap), **légende** pour
deux séries ou plus, **tableau équivalent** (« Afficher le tableau »), **résumé accessible** (minimum, maximum, dernière valeur), l'image précédente est
gardée, atténuée, pendant un rechargement. Couleurs : emplacements 1 (bleu) et 2 (orange) de la palette catégorielle, **validés avec le script du guide**
sur les deux surfaces (écart pour le daltonisme 26,8 ; contraste suffisant). Rafraîchissement toutes les 30 s (heure), 1 min (jour), 5 min (autres).
Page **Nœud** : section « Historique » (processeur, mémoire, réseau, charge) ; page **Machine** : onglet « Performances » (processeur, mémoire, réseau, disque).

## Validé en réel, et ce qui ne l'a pas été

Validé sur un vrai cluster (lecture seule) : un nœud, une VM qui tourne, et une VM arrêtée depuis plus d'une semaine (« Aucune mesure sur cette période », sans zéro
trompeur) ; les périodes heure, jour et année ; le survol, le clavier et le tableau ; le rendu dans le thème Glass.

**Non validé en réel** : un **conteneur** dans l'interface (la route est testée sur le faux Proxmox et le RRD d'un conteneur a été lu) ; les périodes semaine et
mois à l'écran ; un **trou au milieu d'une courbe** (machine arrêtée puis redémarrée) à l'écran ; le thème **Sombre** (mêmes couleurs, surface validée) ;
l'écran étroit ; plusieurs milliers de points.
