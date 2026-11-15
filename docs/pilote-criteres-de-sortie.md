# Jalon J2 « pilote en entreprise » : critères de sortie, état réel (ticket #448)

**Date : 2026-11-15.** Un tableau par ticket du jalon J2, avec ce que chaque critère exige et **où on en est vraiment**. Légende : ✅ vu **en réel** sur le Kaji déployé · 🧪 vérifié par des tests automatisés sur faux Proxmox (avec mutations), **pas encore en réel** · ⬜ pas fait. Source de chaque ligne : la doc d'API du ticket et `docs/essais-j2-a-faire-par-enzo.md`.

**Verdict : J2 n'est PAS terminé.** Le code des six fonctions codables est livré et testé. Il manque la **preuve en réel** pour la plupart (elle exige un compte avec un mot de passe, un jeton créé par le propriétaire ou un réglage système : jamais fait par un agent), et le **SSO** (#443) qui attend un fournisseur d'identité de test.

| Ticket | Critère de sortie | État |
|---|---|---|
| **#440** jeton Proxmox par utilisateur | Une action de l'utilisateur A apparaît **sous son nom dans le journal de Proxmox** | ⬜ **jamais vu en réel** (la doc du lot le dit : « aucun essai réel à ce jour ») |
| | La base seule ne permet pas de lire un jeton (clé séparée) | 🧪 |
| | Rotation de la clé essayée sur une base contenant des jetons, documentée | 🧪 (`rotate-token-key`, `docs/runbook.md`) |
| | Jeton expiré ou révoqué signalé clairement, sans fuite | 🧪 |
| **#441** jeton de service | Le planificateur tourne avec ce seul jeton ; **refus constaté pour tout le reste** | ⬜ **jamais vu en réel** (« aucun essai réel », `docs/api/jeton-service.md`) |
| | Droits du jeton de service documentés par fonction | ✅ (doc) |
| | Sans jeton de service, le planificateur le dit au lieu d'échouer en silence | 🧪 repli sur le jeton partagé (ou refus si le jeton de service est exigé) testé ; ⬜ le message d'avertissement n'a pas été relu |
| **#442** création assistée des jetons | Un utilisateur sans jeton en reçoit un par l'interface | 🟡 **expiration obligatoire vue en réel par l'API** (2026-11-15) ; ⬜ le **formulaire** dans le navigateur |
| | Le secret n'apparaît ni dans l'audit, ni dans les journaux, ni dans une réponse ultérieure | ✅ **réel** (liste, audit, session administrateur) + 🧪 |
| | Les opérations interdites aux jetons passent par la session par mot de passe, essai réel | ⬜ (mot de passe à taper par le propriétaire) |
| **#443** SSO (OIDC, LDAP) | Une personne se connecte par le SSO (fournisseur de test) | ⬜ (code en cours, testé contre un faux fournisseur : voir `docs/api/sso.md` quand il existe) |
| | Compte désactivé ou retiré : plus de session ; aucun secret ; repli par un compte local | ⬜ |
| **#444** TOTP de connexion | Un compte avec TOTP ne s'ouvre pas avec le seul mot de passe | 🧪 (68 tests) |
| | Enrôlement et réinitialisation essayés dans le navigateur | 🟡 vus sur un serveur **local** de test ; ⬜ sur le déploiement réel |
| | Secret chiffré au repos, jamais dans une réponse ni un journal | 🧪 (+ rotation de la clé couverte depuis #471) |
| | `docs/securite.md` traité | ✅ |
| | Retrait du TOTP d'un autre compte (administrateur) | ✅ **réel** (409, 409, 404 ; audit) |
| **#445** audit exportable | L'audit arrive dans le SIEM de test | ⬜ (le fichier JSON : réglage du `.env` du CT 116 à faire par le propriétaire) |
| | Aucune valeur secrète dans l'export, même sur les erreurs | 🧪 (10 formes de secrets, injection de lignes) |
| | Une panne de la destination ne casse pas Kaji et se voit dans les journaux | 🧪 (syslog TCP injoignable, erreur journalisée une fois par minute) |
| | Réglages documentés (`.env.example`, guide d'installation) | ✅ |
| **#446** limiteur persistant | Un redémarrage ne remet pas le compteur à zéro ; expiration ; purge | 🧪 |
| **#447** rôles par périmètre | Un compte restreint ne sort pas de son périmètre : test exhaustif | 🧪 (toutes les routes de l'application passent par la politique) |
| | … **et essai réel** | 🟡 gestion côté administrateur vue **en réel** ; ⬜ **la vue d'un compte restreint** (connexion avec mot de passe) |
| | Une route ajoutée plus tard est refusée par défaut | 🧪 |
| | Interface : le compte ne voit que son périmètre | ⬜ en réel |

## Ce qu'il reste, par propriétaire de l'action
| À faire | Par qui | Pourquoi pas un agent |
|---|---|---|
| Journal de Proxmox nominatif (#440), jeton de service et refus (#441) | **Enzo** (procédure : `docs/essais-j2-a-faire-par-enzo.md`, §§ 5 et 6) | Un jeton Proxmox à créer et à coller dans le formulaire : un agent ne saisit pas de jeton |
| Parcours TOTP, vue d'un compte restreint, formulaire de jeton | **Enzo** (§§ 1, 2, 3 de la même page) | Il faut se connecter avec un mot de passe |
| Export de l'audit | **Enzo** (§ 4) | Réglage du `.env` du CT 116 |
| SSO réel | **Enzo** + un fournisseur d'identité de test (Keycloak, Entra, Authentik…) | Il n'y en a pas |
| Corriger ce que ces essais révèleront | PC A ou PC B | — |

**Règle de sortie du jalon** : tous les ✅ en réel, hormis le SSO qui peut sortir « fonction facultative non validée » **si le propriétaire le décide**. Les 🧪 qui restent sans preuve en réel sont signalés dans `docs/statut-fonctions.md`.
