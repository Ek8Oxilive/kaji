# Reprise rapide (lis ceci, et rien d'autre, avant de coder)

> Enzo : **ouvre une session neuve par lot** (ou `/clear`) au lieu de reprendre l'ancienne conversation : reprendre recharge tout l'historique (≈ 20 % du contexte). Cette page et `docs/CARTE.md` suffisent pour repartir.

Kaji = interface web (FastAPI + React) pour piloter le Proxmox perso d'Enzo ; but : **ne perdre aucune fonction de l'interface Proxmox**.
Je suis **PC A** (valide en réel, relit PC B) ; Enzo merge toutes les PR. `main` est protégée : une PR par lot (ticket + jalon + `agent:pc-a`).

## Rôle : Enzo l'annonce au démarrage, sinon DEMANDE « PC A ou PC B ? » avant tout
- **PC A** (portable Linux, accès au vrai cluster en VPN) : sonde et valide en réel (lecture seule, écritures réversibles avec l'accord d'Enzo), relit les PR de PC B, prend les lots qui exigent le cluster.
- **PC B** (autre PC, **faux Proxmox uniquement**, jamais le cluster) : code et teste sur faux Proxmox strict ; ne prend jamais un ticket `agent:pc-a`.
- Phrases de départ à coller : « **Tu es PC A**, lot : … » / « **Tu es PC B**, lot : … ». Sans lot : prendre le suivant de la liste ci-dessous.
- **Répartition suggérée** (Enzo décide) : A = M5 (il faut lire le stockage réel), M6, M7 et M8 (banc d'essai), M10 ; B = M13 notifications et métriques, M14, M15, M12 C4 si autorisé ; chacun relit l'autre.

## État (mis à jour à chaque fin de session)
- **Fait** : M0 à M4, M5 lecture, M6 lecture, M9 consoles, M11 complet (système des nœuds, sauf firmware : pas d'API), M12 Ceph lecture + écriture C2/C3/init (PC B, rien validé : pas de Ceph), M13 tâches, graphiques, étiquettes, notes, vues.
- **Déployé** : CT 116, `http://192.168.1.214:8080` (VPN), dossier `~/kaji`, `git pull && docker compose up -d --build`. Je n'y ai pas accès : Enzo lance les commandes.
- **M5 fait** : lecture, sauvegardes, ajouter/modifier/retirer un stockage (PR #133, `/storage-config`), téléverser/télécharger ISO et modèles (lot 2, `docs/api/telechargement.md`), PBS (lot 3 : stockage, clé de chiffrement affichée une fois, état de vérification des sauvegardes). volumes (lot 4 : supprimer un fichier, protéger une sauvegarde, élaguer avec aperçu, `docs/api/volumes.md`). **M5 terminé** (reste seulement la copie d'un volume vers un autre stockage/nœud).
- **Reste, dans cet ordre** (tableau détaillé : `docs/parite-proxmox.md`, colonnes ⬜/🟡) : **M5** stockage (ajouter/modifier, téléverser ISO, PBS) → M6 droits en écriture → M7 réseau/firewall/SDN → M8 HA/réplication → M10 cluster → M12 C4 destruction Ceph → M13 notifications + métriques → M14 options avancées → M15 datacenter.
- **Jamais exécuté en réel** (à dire dans chaque PR) : migration à chaud, déplacement et agrandissement de disque, carte réseau ajoutée, PBS (aucun PBS dispo), protection de sauvegarde, élagage (aucune sauvegarde sur le cluster), stockages autres que dir, redémarrer/éteindre un nœud, disques et volumes, certificats, ACME, dépôts (ajout), Ceph.

- **Validé en réel (2026-11-08, dir `kaji-test` créé puis retiré)** : ajouter, modifier (contenu) et retirer un stockage `dir`, téléverser une ISO de 1 Mo avec somme de contrôle sha256 (taille exacte, tâche Proxmox réussie), supprimer ce fichier ; téléchargement par URL sur `enzo2` (fichier de 496 octets, sha256 vérifié, mauvaise somme refusée par le nœud, adresse 127.0.0.1 refusée par Kaji), puis suppression. Le `Content-Length` calculé est accepté par pveproxy. Reste sur le nœud `enzo` : le dossier vide `/var/lib/kaji-test` (Kaji ne supprime jamais de fichiers).

- **M3 et M4 validés en réel (2026-11-08)**, sur la VM 115 `kaji-sandbox` et des machines jetables 117 à 119 (toutes supprimées, cluster revenu à l'identique : 17 machines) :
  - M3 : tableau de bord (chiffres de l'API = écran), flux SSE (instantané en 82 ms puis toutes les 5 s), thèmes Sombre/Glass mémorisés, palette Ctrl+K, filtres, actions rapides démarrer et arrêt forcé.
  - M4 : RAM et cœurs (valeurs absurdes refusées), ajout, détachement et suppression d'un disque, snapshots (créer, restaurer, supprimer), clone complet puis suppression, migration hors ligne `enzo` → `enzo2` → `enzo`, cloud-init (lecteur, réglages, nettoyage, retrait), création d'un LXC et d'une VM puis suppression.
  - **Pas testé en réel** : migration à chaud, déplacement et agrandissement de disque (irréversible : faux Proxmox seulement), ajout de carte réseau (droit `SDN.Use` du jeton manquant), création depuis ISO avec démarrage, démarrage d'un LXC, écran de première configuration, connexion et déconnexion (mot de passe), repli en polling si le SSE tombe.
  - **À ne jamais tester** : le CT 116 `kaji-ct` est Kaji lui-même (suppression, arrêt, migration interdits) ; machines 100 à 114 = services d'Enzo. Les tickets #143 à #151 (agent:pc-b) sont des lots pour PC B que PC A teste ensuite dans ce bac à sable.

- **M6 en cours** : décisions d'Enzo (2026-11-08) = option D (`docs/m6-ecriture.md`), token d'administration collé, session de 30 min (4 h max). **M6-6 livré** : session administrateur (`docs/api/admin-session.md`, `routers/admin_session.py`, `adminsession.py`) ; elle n'écrit aucun droit. **M6-7a livré** : écrire une entrée d'ACL (`docs/api/acl-ecriture.md`, `aclwrite.py`, `routers/acl_write.py`, bouton « Modifier une ACL… » dans le panneau), non validé en réel (aucun token d'administration). **M6-7b livré** : utilisateurs pve, groupes, appartenances (`docs/api/utilisateurs-ecriture.md`), non validé en réel. **Suite** : M6-7c tokens API (création avec secret affiché une fois, révocation), puis validation en réel avec un token d'administration d'Enzo avec les interdits absolus du §5, une écriture à la fois, essais réels seulement sur un utilisateur et un chemin jetables (`/pool/kaji-test`). Pour tester en réel, Enzo doit créer un token sans séparation de privilèges avec `Permissions.Modify` sur `/pool/kaji-test` seulement.

## Méthode d'un lot (≈ 1 PR)
1. `git checkout main && git pull`, branche `feat/mX-…`, ticket `gh issue create --milestone … --label agent:pc-a`.
2. Sonder le vrai Proxmox **en lecture seule** (`$CLAUDE_JOB_DIR/tmp/probe*.py`, `PYTHONPATH=. .venv/bin/python -B`) avant de coder ; schémas réels, pas de mémoire.
3. Code + **faux Proxmox strict** (méthode et noms de paramètres exacts, 400 sinon) + tests ; puis **mutations** sans bytecode (`PYTHONDONTWRITEBYTECODE=1`, `python -B`), base verte d'abord ; chaque survivant = un test.
4. Suite complète en arrière-plan (≈ 4 min) sortie dans un fichier, `tail -2` seulement ; `npm run build` ; doc `docs/api/<fonction>.md` + tableau de parité.
5. Commit (`type(Mx/zone): …` + `Closes #N`), PR avec liste honnête « non testé ». Essai réel d'écriture : seulement réversible et avec l'accord d'Enzo.

## Retrouver le code sans tout lire
`grep -i mot docs/CARTE.md` (carte générée : rôle et routes de chaque fichier), puis ouvrir seulement le fichier trouvé (son `*spec.py` pour la validation, son routeur, `tests/test_<module>.py`). Fin de lot : `python3 tools/carte.py > docs/CARTE.md`.

## Pièges connus
Ne pas changer de branche pendant une suite ou des mutations · `pgrep -f` se reconnaît lui-même · ancrer les motifs `^…$`, `fullmatch` · droits du token via `docs/api/acces.md` · Brave + extension Claude (reconnecter si « not connected ») · économiser les tokens : pas de relecture de README/PLAN/docs d'API entiers.
