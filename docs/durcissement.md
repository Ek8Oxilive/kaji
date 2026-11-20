# Durcissement et sécurité des secrets

> Retour au [README](../README.md). La revue de sécurité complète est dans [securite.md](securite.md).

## Durcissement
- **Sessions révocables** : chaque jeton renvoie à une session enregistrée en base ; la déconnexion, le changement de mot de passe et `logout-all` les suppriment, un jeton copié devient donc inutilisable.
- **Base SQLite en `600`** (hash du mot de passe, tokens chiffrés, audit) : créée ainsi, ou resserrée au démarrage.
- **Audit purgé** au-delà de `KAJI_AUDIT_RETENTION_DAYS`.
- **En-têtes** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, et `Cache-Control: no-store` sur toute l'API.
- Dépendances **à version fixée**, mises à jour par Dependabot.
- **Migrations de schéma** : versionnées, **sauvegardées** (copie `kaji.db.bak-vN-…` en `600` avant toute migration, les 5 dernières sont gardées), **atomiques** (une transaction par migration, schéma compris) ; Kaji refuse de démarrer sur une base plus récente que le code. `python -m app.migrations status` (ou `upgrade`) depuis `backend/`.
- **Rôles** vérifiés par le serveur à chaque requête ; tout ce qui n'est pas explicitement permis à un rôle est refusé.
- Non couvert : l'authentification à deux facteurs **pour se connecter à Kaji** (la gestion de celle des comptes Proxmox existe) ; mot de passe oublié : `python -m app.admin_cli reset-password --user <nom>` sur le serveur (voir [docs/deploiement.md](deploiement.md)).

## Sécurité des secrets
Les erreurs de validation de l'API **ne renvoient jamais les valeurs saisies** (mots de passe, secrets de token) : par défaut FastAPI recopie le corps de la requête dans l'erreur, ce que Kaji désactive. Les mots de passe de conteneur ne sont ni journalisés ni écrits dans l'audit.
