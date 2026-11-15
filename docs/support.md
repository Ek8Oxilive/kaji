# Politique de support (jalon J4, ticket #460)

> **Statut : PROPOSITION, non engageante.** Les versions maintenues et les délais ci-dessous sont des **valeurs proposées** par un agent. **Seul le propriétaire du projet peut s'y engager** (critère de sortie du ticket #460 : « les délais sont ceux que le propriétaire s'engage à tenir »). Tant qu'il ne les a pas confirmés ici (ligne « Confirmé par »), ce sont des **objectifs, pas des promesses**, comme dans `SECURITY.md`. Ce qui est factuel (la procédure de mise à jour et de retour arrière, ce que le support ne couvre pas) est déjà vrai aujourd'hui.

**Confirmé par le propriétaire le :** ⬜ (jamais) · **Valeurs modifiées :** ⬜

## Ce que ce support est, et n'est pas
- Kaji est tenu par **une seule personne**, sans astreinte, sans équipe de sécurité dédiée. **Aucun accord de niveau de service** (SLA) ; la licence (MIT) est « sans garantie ».
- Il couvre : les **corrections de sécurité** et les **défauts bloquants** des versions suivies ; l'aide à la mise à jour ; la **documentation** d'exploitation (`docs/runbook.md`).
- Il ne couvre pas : l'installation sur ta machine, la configuration de ton Proxmox, un déploiement exposé sur Internet (Kaji est une « V1 candidate pour un lab interne non exposé », `docs/installation-lab.md`), les versions modifiées localement.

## Versions suivies (proposition)
| Version | Corrections de sécurité | Défauts bloquants |
|---|---|---|
| `main` et la **dernière** étiquette publiée | oui | oui |
| L'étiquette **précédente**, **30 jours** après la sortie de la dernière | oui (critiques et élevées seulement) | non |
| Toute version plus ancienne | non : mets à jour | non |
| Une version candidate (`-rcN`) | seulement jusqu'à la version suivante | jusqu'à la version suivante |

`SECURITY.md` donne aujourd'hui « `main` et la dernière étiquette » seulement : cette ligne **s'ajoutera** si le propriétaire confirme.

## Délais de correction visés (proposition)
À partir de la **première évaluation** (accusé sous 7 jours, première évaluation sous 14 jours : inchangé, `SECURITY.md`) :

| Gravité | Correctif ou contournement documenté | Publication |
|---|---|---|
| **Critique** (exécution de code à distance, contournement de l'authentification, fuite de secrets) | **7 jours** | version corrective, annonce dans `CHANGELOG.md` (rubrique « Sécurité ») |
| **Élevée** (élévation de droits, fuite de données limitée) | **14 jours** | idem |
| **Moyenne** | **30 jours** | prochaine version |
| **Faible** | prochaine version | prochaine version |

Une faille dans une image de base ou une dépendance : le workflow « SBOM et audit » (`docs/sbom.md`) la signale chaque lundi ; la conduite à tenir est au runbook § 6.7.

## Mettre à jour, et revenir en arrière
La procédure existe et ne dépend d'aucun engagement : `docs/runbook.md` § 5 (sauvegarde, `git checkout <étiquette>`, reconstruction **avec les deux fichiers Compose** si le HTTPS est actif, `migrations status`, `verify`). 

**Retour arrière : les migrations de la base ne se défont pas.** Une base plus récente que le code est **refusée au démarrage**. Revenir à une ancienne étiquette exige donc de **restaurer la sauvegarde faite avant la mise à jour** (`tools/restore.sh`) : tout ce qui a été écrit depuis cette sauvegarde est perdu. **Toujours sauvegarder avant de mettre à jour** ; la CI migre des bases d'exemple de chaque version vers le code courant, mais **la procédure complète n'a pas été essayée avec le vrai Docker** (`docs/runbook.md`).

## Fin de support d'une version
Annoncée dans `CHANGELOG.md` à la sortie de la version qui la remplace (proposition : 30 jours de recouvrement pour les corrections critiques et élevées, voir plus haut).

## Ce que le propriétaire doit trancher (pour que ceci devienne une politique)
1. Les **versions suivies** (la dernière seule, ou la dernière et la précédente pendant combien de temps).
2. Les **délais** par gravité : tenables par **une seule personne, sans astreinte** ? (si non, les allonger : un engagement manqué est pire qu'un engagement modeste).
3. Le **canal** du signalement (celui de `SECURITY.md`) et qui répond.
4. Une fois décidé : mettre à jour `SECURITY.md` (tableau des versions et délais), `CHANGELOG.md` (rubrique « Ajouté »), remplacer le statut en tête de cette page, puis fermer #460.
