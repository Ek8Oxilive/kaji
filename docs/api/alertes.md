# Alertes (M13, lot #413)

Préfixe `/api/connections/{conn_id}/alerts`. **Propre à Kaji** : surveillance du cluster avec des seuils, état durable, notification par webhook. Section « Alertes » de la page « Tâches ».
Pourquoi un webhook : l'API de notifications de Proxmox n'envoie pas de message libre (seulement un message de test d'une cible, `docs/api/notifications.md`).

| Route | Droit | Effet |
|---|---|---|
| `GET /rules` | tout utilisateur de Kaji | Règles (jamais l'adresse du webhook : `has_webhook`) |
| `POST /rules` | **administrateurs** | Crée (50 au plus par connexion) |
| `PUT /rules/{id}` | **administrateurs** | Modifie ; `webhook_url` remplace, `clear_webhook` retire, sinon l'adresse est conservée |
| `DELETE /rules/{id}?confirm=true` | **administrateurs** | Supprime la règle ET son historique |
| `GET /events?limit=` | tout utilisateur de Kaji | Alertes en cours puis historique (1 à 200, plus récentes d'abord) |
| `POST /rules/{id}/test?confirm=true` | **administrateurs** | Envoie UN message de test au webhook (une fois par minute et par règle) |

## Types de règle
| `kind` | Se déclenche quand… | Seuil |
|---|---|---|
| `cpu`, `mem` | le % CPU / RAM d'un nœud **en ligne** reste ≥ seuil pendant `minutes` | 1 à 100 |
| `storage` | le % utilisé d'un stockage **actif** reste ≥ seuil pendant `minutes` | 1 à 100 |
| `node_offline` | un nœud n'est pas « online » pendant `minutes` | aucun |
| `task_failed` | une tâche se termine en échec (une alerte par tâche, jamais rejouée ; `OK` et `WARNINGS…` ne sont pas des échecs) | aucun |

Cycle (par nœud ou stockage) : seuil dépassé → `pending` ; encore dépassé après `minutes` → `firing` + notification ; plus dépassé → `resolved` + notification (une alerte `pending` qui retombe est supprimée sans trace). La première évaluation d'une règle `task_failed` se cale sur la tâche la plus récente : **pas d'historique remonté**, 20 alertes au plus par passage.

## Garde-fous
- **Webhook** : écriture seule, **chiffré en base** (même clé que les jetons Proxmox), jamais renvoyé, jamais journalisé ni dans l'audit ni dans une erreur ; adresses locales refusées (boucle locale, `localhost`, lien local, réservée…, comme les téléchargements) **à l'enregistrement ET à l'envoi** ; `http` ou `https` sans identifiants dans l'adresse ; envoi en POST JSON `{text, kaji}` (compatible Slack, Mattermost, Teams), 5 s, **redirections jamais suivies** ; un échec est noté dans l'alerte (« notification échouée »), sans l'adresse.
- Connexion Proxmox injoignable : **rien n'est déclenché ni résolu à tort** ; une règle en erreur n'arrête pas les autres ; mesures de Proxmox traitées comme non fiables (types, bornes, noms assainis).
- Évaluation toutes les 60 s dans la boucle du planificateur (`app/scheduler.py`, coupée par `KAJI_SCHEDULER=false`). Une seule instance de Kaji doit tourner.
- Audit : `alert-rule-create|update|delete`, `alert-test` (utilisateur de Kaji) et `alert-firing|resolved` (utilisateur « alertes », texte sans adresse).

## Validation
Faux Proxmox strict + faux webhook (`tests/test_alerts.py`, `test_alert_rules.py` : durée avant déclenchement, seuil inclusif, cycle complet, tâches sans rejeu ni historique, connexion injoignable, envoi réel simulé, redirection refusée, adresses locales, fuites, rôles, isolation), 49 tests, 34 mutations tuées.
**Pas essayé en réel** : voir `docs/REPRISE.md`. **Limites** : pas d'e-mail (Kaji n'a pas de SMTP), pas d'acquittement (une alerte se résout quand la mesure revient sous le seuil), pas d'alerte par machine (nœuds, stockages et tâches seulement).
