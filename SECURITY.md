# Politique de sécurité

Kaji pilote un cluster Proxmox VE : une faille peut donner accès à toute l'infrastructure. Merci de la signaler de façon **privée** plutôt que dans un ticket public.

## Signaler une vulnérabilité

1. Sur la page du dépôt `Ek8Oxilive/kaji`, onglet **Security** → **Report a vulnerability** (signalement privé GitHub). Seules les personnes qui gèrent le dépôt voient le rapport.
2. Si ce bouton n'est pas disponible, ouvre un ticket public **sans aucun détail technique** (« je souhaite signaler une vulnérabilité, comment vous contacter en privé ? ») : le propriétaire répondra pour convenir d'un canal privé. **Ne publie jamais de preuve d'exploitation dans un ticket, une pull request ou une discussion publics.**

Indique si possible : la version (étiquette ou commit), la configuration utile (HTTPS ou non, rôles, options `KAJI_*` activées), les étapes pour reproduire, et l'effet constaté. **N'envoie jamais de vrai mot de passe, jeton Proxmox ni `KAJI_SECRET_KEY`** : décris leur effet, ne les joins pas.

## Ce que tu peux attendre

Le dépôt est tenu par une seule personne, sans équipe de sécurité dédiée. **Objectifs, non garantis** : accusé de réception sous 7 jours, première évaluation (gravité, versions touchées) sous 14 jours, correctif ou contournement documenté ensuite selon la gravité. Une politique de délais ferme est prévue pour le jalon J4 (`docs/cadrage-prod-entreprise.md`). Une fois le correctif publié, la faille est mentionnée dans `CHANGELOG.md` (rubrique « Sécurité »), avec le nom du signalant s'il le souhaite.

## Versions suivies

| Version | Corrections de sécurité |
|---|---|
| `main` et la dernière étiquette publiée (aujourd'hui `v1.0.0-rc1`) | oui |
| Toute version plus ancienne | non : mets à jour |

Il n'existe pas encore de version « stable » : `v1.0.0-rc1` est une version candidate **pour un lab interne non exposé**. Ne l'expose pas sur Internet (`docs/installation-lab.md`).

## Ce qui est dans le périmètre

- Le code de Kaji (`backend/`, `frontend/`), ses fichiers de déploiement (`docker-compose*.yml`, `deploy/`) et sa documentation d'installation.
- Typiquement : contournement de l'authentification, des rôles ou de la session ; fuite d'un secret (jeton, mot de passe, clé, adresse de webhook) dans une réponse, un journal ou l'audit ; écriture vers Proxmox qui contourne un verrou ou une validation ; consoles (WebSocket) accessibles sans session ; requête forgée vers le réseau interne ; injection ; faiblesse du chiffrement des secrets au repos.

## Ce qui est hors périmètre

- Les failles de Proxmox VE, de Docker, de Caddy, de nginx ou d'une dépendance elle-même : à signaler à leurs projets (signale-nous seulement si Kaji les rend exploitables).
- Les limites déjà connues et documentées dans `docs/securite.md` (par exemple : pas de double authentification pour se connecter à Kaji, limiteur de connexions en mémoire, jeton Proxmox partagé, risque de l'option `KAJI_ADMIN_USE_KAJI_TOKEN`). Un contournement concret qui les aggrave reste bienvenu.
- Une installation volontairement exposée sur Internet, sans HTTPS, ou avec `KAJI_COOKIE_SECURE=false` hors réseau de confiance.
- Les attaques qui exigent déjà d'être administrateur de Kaji ou administrateur de Proxmox.
- Les tests intrusifs contre une installation qui n'est pas la tienne : teste sur ta propre instance.

## Où est documenté l'état de la sécurité

- `docs/securite.md` : revue de sécurité, ce qui est vérifié, corrigé et ce qui reste à décider.
- `docs/statut-fonctions.md` : ce qui est validé en réel et ce qui est expérimental.
- Aucune relecture de sécurité ni test d'intrusion par un tiers n'a encore eu lieu (jalon J3).
