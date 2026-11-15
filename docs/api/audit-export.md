# Export de l'audit : fichier JSON et syslog (jalon J2, ticket #445)

Kaji écrit chaque action (succès, refus, erreur) dans sa base (`audit_log`). Cet export **ajoute** une copie vers un **fichier JSON** et/ou un **serveur syslog**, pour un SIEM ou une conservation légale. Désactivé par défaut. Aucune route nouvelle : tout se règle dans `.env`.

## Réglages
| Variable | Rôle | Défaut |
|---|---|---|
| `KAJI_AUDIT_FILE` | chemin **absolu** d'un fichier (une ligne JSON par événement, droits `600`) | vide : pas de fichier |
| `KAJI_AUDIT_FILE_MAX_MB` | taille à partir de laquelle le fichier tourne (1 à 1024) | `10` |
| `KAJI_AUDIT_FILE_BACKUPS` | nombre d'anciens fichiers gardés (`audit.jsonl.1` … ; 0 à 1000 ; **0 = pas de rotation, le fichier grossit sans limite**) | `10` |
| `KAJI_AUDIT_SYSLOG` | `udp://hôte:port` ou `tcp://hôte:port` (adresse IPv6 : `udp://[::1]:514`) | vide : pas de syslog |
| `KAJI_AUDIT_RETENTION_DAYS` | conservation **dans la base** (existant ; 0 = indéfinie) | `365` |

Dans Docker, mets le fichier dans un volume (`/data/audit.jsonl` : le volume `kaji-data` existe déjà) ; sans volume, il disparaît avec le conteneur.

## Format d'un événement
Une ligne JSON, clés dans cet ordre, **stables** :
```json
{"ts":"2026-11-15T12:00:00.123Z","service":"kaji","id":4821,"user":"alice","connection_id":1,"action":"vm-start","target":"qemu/100@enzo","status":"started","upid":"UPID:enzo:…","detail":"ok"}
```
`ts` est en UTC. `status` : `started` ou `error` (selon l'action). `upid` et `detail` valent `null` s'ils sont absents. Chaque champ libre est borné à 500 caractères.

**Syslog** : RFC 5424, facility `local0`, gravité `info`, étiquette `kaji`, identifiant de message `AUDIT` :
`<134>1 2026-11-15T12:00:00.123Z hôte kaji - AUDIT - {json}`. En TCP, un message par ligne (séparateur `\n`).

## Garanties
- **Jamais de secret** : `detail`, `target` et `user` passent par un nettoyage (`password`, `token`, `ticket`, `csrf`, `authorization`, `api_key`, `cookie`, `webhook`… suivis d'une valeur ; jetons `PVEAPIToken=…` ; `utilisateur@realm!nom=secret`). C'est une seconde barrière : l'audit ne reçoit déjà aucun secret.
- **Une ligne = un événement** : une valeur contenant un saut de ligne ne peut pas fabriquer un faux événement (le JSON l'échappe).
- **Une panne de l'export ne casse jamais l'action** : l'événement reste dans la base, l'erreur est écrite **une fois par minute au plus** dans le journal de Kaji. Le syslog part par une file et un fil à part : un serveur lent ou éteint ne ralentit aucune requête ; si la file se remplit (10 000 événements), les suivants sont jetés pour le syslog.
- **Configuration invalide = Kaji ne démarre pas** (adresse syslog mal formée, chemin relatif ou contenant `..`, dossier au lieu d'un fichier, fichier non inscriptible, bornes de taille) : perdre l'audit en silence serait pire. Un serveur syslog **injoignable** n'empêche pas de démarrer (Kaji se reconnecte tout seul).
- Le fichier est créé en `600` : l'audit nomme des personnes et des machines.

## Limites connues
- **Pas de TLS pour le syslog** (UDP et TCP en clair) : à n'utiliser que sur un réseau de confiance, ou à relayer par un agent local (rsyslog, vector) qui chiffre.
- **UDP : aucune garantie de livraison.** Pour de l'audit à valeur légale, préfère le fichier (relevé par un agent) ou TCP.
- Pas de relecture des événements **passés** vers le syslog : l'export ne concerne que les événements écrits après son activation (l'historique reste dans la base).
- Le fichier tourne par taille, pas par date.

## Tests
`backend/tests/test_audit_export.py` (40 tests) : format et clés, droits `600`, rotation et nombre de sauvegardes, 10 formes de secrets, injection de lignes, bornes, syslog UDP et TCP **sur de vraies prises locales**, serveur injoignable sans blocage, panne sans casser l'action, limite d'un message d'erreur par minute, 7 adresses syslog invalides, refus de démarrer. 12 mutations tuées (3 survivantes d'abord, comblées).
**Jamais vu en réel** : un vrai SIEM, un serveur syslog distant, TCP sur plusieurs heures avec coupures du serveur.
