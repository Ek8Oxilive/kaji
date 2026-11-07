# Reprise rapide (lis ceci, et rien d'autre, avant de coder)

Kaji = interface web (FastAPI + React) pour piloter le Proxmox perso d'Enzo ; but : **ne perdre aucune fonction de l'interface Proxmox**.
Je suis **PC A** (valide en réel, relit PC B) ; Enzo merge toutes les PR. `main` est protégée : une PR par lot (ticket + jalon + `agent:pc-a`).

## État (mis à jour à chaque fin de session)
- **Fait** : M0 à M4, M5 lecture, M6 lecture, M9 consoles, M11 complet (système des nœuds, sauf firmware : pas d'API), M12 Ceph lecture + écriture C2/C3/init (PC B, rien validé : pas de Ceph), M13 tâches, graphiques, étiquettes, notes, vues.
- **Déployé** : CT 116, `http://192.168.1.214:8080` (VPN), dossier `~/kaji`, `git pull && docker compose up -d --build`. Je n'y ai pas accès : Enzo lance les commandes.
- **Reste, dans cet ordre** (tableau détaillé : `docs/parite-proxmox.md`, colonnes ⬜/🟡) : **M5** stockage (ajouter/modifier, téléverser ISO, PBS) → M6 droits en écriture → M7 réseau/firewall/SDN → M8 HA/réplication → M10 cluster → M12 C4 destruction Ceph → M13 notifications + métriques → M14 options avancées → M15 datacenter.
- **Jamais exécuté en réel** (à dire dans chaque PR) : redémarrer/éteindre un nœud, disques et volumes, certificats, ACME, dépôts (ajout), Ceph.

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
