# Thèmes de l'interface

Frontend seul. Sélecteur en haut de chaque page (dans le tiroir du menu sur téléphone) et palette de commandes (Ctrl K, « Thème … »). Le choix est gardé dans le navigateur (`localStorage`, clé `kaji-theme`) ; sans choix : Sombre.

| Thème | Rôle |
|---|---|
| **Sombre** (`dark`) | Thème d'origine, surfaces opaques. |
| **Glass** (`glass`) | Surfaces translucides avec flou. |
| **Clair** (`light`) | Fond clair, texte `#0f172a`. Contrastes WCAG AA vérifiés : texte courant, accent, ok, warn, danger et séries des graphiques ≥ 4,5:1 sur blanc, fond de page et surfaces secondaires. |
| **Auto** (`auto`) | Suit le réglage clair / sombre du système (`prefers-color-scheme`) et le suit s'il change tant qu'il est choisi. |

Un thème = un jeu de variables CSS (`frontend/src/index.css`) : `--canvas`, `--surface`, `--surface2`, `--fg`, `--muted`, `--line`, `--accent`, `--accentfg`, `--ok`, `--warn`, `--danger`, `--series-1/2` (graphiques), `--code-bg` (blocs de commandes et journaux), `--option-bg` (listes déroulantes natives, **opaque**). Les composants n'utilisent que ces jetons : pas de couleur écrite en dur (les consoles noVNC et xterm.js restent noires dans tous les thèmes). `frontend/public/theme-init.js` applique le thème avant le premier rendu (pas de flash).
