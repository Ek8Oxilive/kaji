# Kaji : lecture du projet (consigne pour tout agent)

**N'explore pas le dépôt et ne charge pas tout le contexte.** Au démarrage, lis seulement :
1. `@docs/REPRISE.md` (ci-dessous : état, reste à faire, méthode, pièges) ;
2. `@AGENTS.md` (règles de travail) ;
3. puis, pour le lot en cours, **cherche** avec `grep -i mot docs/CARTE.md` (carte du projet : un fichier par ligne, son rôle et ses routes) et n'ouvre que les fichiers trouvés.

Ne relis `PLAN.md`, `README.md`, `docs/parite-proxmox.md`, `docs/api/*` ou `docs/m*.md` que pour le lot concerné, et jamais en entier sans besoin.

**Ne relis jamais l'historique d'une conversation précédente ni son fichier de transcription** : tout ce qu'il faut savoir est dans `docs/REPRISE.md`, GitHub (`gh pr list`, tickets) et la carte. Une session neuve par lot coûte bien moins qu'une conversation reprise.

**À mettre à jour à CHAQUE fin de lot (obligatoire, avant la PR)** :
- `docs/REPRISE.md`, section « État » (ce qui est fait, déployé, le prochain lot) ;
- `docs/CARTE.md` : `python3 tools/carte.py > docs/CARTE.md` (un test échoue si elle est périmée).

@AGENTS.md
@docs/REPRISE.md
