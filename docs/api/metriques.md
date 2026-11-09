# Serveurs de métriques (M13, lot #149)

Préfixe `/api/connections/{conn_id}/metrics/servers`. Section « Serveurs de métriques » de la page « Datacenter » (équivalent de Datacenter → Metric Server). Droits Proxmox : `Sys.Audit` (lire), `Sys.Modify` sur `/` (écrire) ; page « Accès » : `datacenter-write`.

| Route | Effet |
|---|---|
| `GET /` | Liste : `id`, `type`, `server`, `port`, `disable` |
| `GET /{id}` | Configuration du serveur, **sans secret** (`token_set`, `otel_headers_set`), avec `digest` |
| `POST /` | Ajoute (`id`, `type`, `server`, `port`, + champs du type). Réponse 201 |
| `PUT /{id}` | Modifie ; `clear` retire des réglages ; `digest` |
| `DELETE /{id}?confirm=true&type_name={id}` | Supprime |

## Types et champs (liste blanche par type)
| Type | Champs |
|---|---|
| `influxdb` | `influxdbproto` (`udp`, `http`, `https`), `organization`, `bucket`, `token` (**secret**), `max_body_size`, `mtu` (512–65536), `verify_certificate`, `api_path_prefix` |
| `graphite` | `proto` (`udp`, `tcp`), `path` (ex. `proxmox.moncluster`), `mtu`, `timeout` (0–300) |
| `opentelemetry` | `otel_protocol`, `otel_path`, `otel_timeout` (1–10), `otel_compression` (`none`, `gzip`), `otel_verify_ssl`, `otel_max_body_size` (≥ 1024), `otel_headers` (**secret**, JSON en base64), `otel_resource_attributes` (JSON en base64) |

Tous : `server`, `port` (1–65535), `disable`. Un champ valable pour un autre type est refusé (422) ; un champ inconnu est ignoré, jamais transmis. Le type d'un serveur ne change pas. `clear` : tout sauf `server` et `port` (envoyé en `delete=`, noms Proxmox).
Le type OpenTelemetry n'était pas dans le ticket : il existe dans l'API de Proxmox 9 et dans l'écran Metric Server.

## Secrets
Le jeton InfluxDB et les en-têtes OpenTelemetry sont des `SecretStr` : **jamais renvoyés** (même si Proxmox les renvoie en clair, ce que le test simule), jamais journalisés (« défini »), jamais dans une erreur. En modification, un champ secret vide = inchangé ; `clear: ["token"]` le retire.

## Verrous
- **`server`** : nom d'hôte ou IP ; **adresses locales littérales refusées** (boucle locale, `localhost`, liaison locale, non spécifiée, multicast, réservée) : le nœud ouvrirait la connexion. Les adresses du réseau privé (192.168.x, 10.x) restent permises.
- **Créer ou activer** un serveur envoie les métriques de **tout le cluster** vers lui : `confirm=true` (400 sinon) ; créé `disable=true`, pas de confirmation. Modifier la destination d'un serveur **actif** (`server`, `port`, protocole, chemins) exige aussi `confirm` ; modifier un serveur désactivé, ou un réglage sans effet sur la destination, non ; désactiver, jamais.
- **Supprimer** : `confirm=true` ET l'identifiant retapé (`type_name`).
- `digest` : Proxmox le vérifie ; `PUT` accepte celui de la lecture et répond **409** s'il est périmé. `dry_run=true` : `params` (secrets masqués) et `needs_confirm`, rien n'est écrit.
- Après chaque écriture l'état est relu (502 si non appliqué).

## Audit
`metrics-server-create|update|delete`, refus compris ; secrets jamais copiés.

## Validation
Faux Proxmox strict (`backend/tests/test_metrics_servers.py`, il renvoie le jeton en clair), 38 mutations. Essais réels : voir `docs/REPRISE.md`.
