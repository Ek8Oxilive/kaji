# Thèmes de l'interface

Frontend seul. Menu **« Apparence »** dans la barre latérale, **entre « Compte » et « Déconnexion »** (dans le tiroir du menu sur téléphone ; en haut à droite sur l'écran de connexion), qui regroupe le thème, la **couleur d'accentuation** et la langue et palette de commandes (Ctrl K, « Thème … »). Le choix est gardé dans le navigateur (`localStorage`, clé `kaji-theme`) ; sans choix : Sombre.

| Thème | Rôle |
|---|---|
| **Sombre** (`dark`) | Thème d'origine, surfaces opaques. |
| **Glass** (`glass`) | Surfaces translucides avec flou. |
| **Clair** (`light`) | Fond clair, texte `#0f172a`. Contrastes WCAG AA vérifiés : texte courant, accent, ok, warn, danger et séries des graphiques ≥ 4,5:1 sur blanc, fond de page et surfaces secondaires. |
| **Auto** (`auto`) | Suit le réglage clair / sombre du système (`prefers-color-scheme`) et le suit s'il change tant qu'il est choisi. |

Un thème = un jeu de variables CSS (`frontend/src/index.css`) : `--canvas`, `--surface`, `--surface2`, `--fg`, `--muted`, `--line`, `--accent`, `--accentfg`, `--ok`, `--warn`, `--danger`, `--series-1/2` (graphiques), `--code-bg` (blocs de commandes et journaux), `--option-bg` (listes déroulantes natives, **opaque**). Les composants n'utilisent que ces jetons : pas de couleur écrite en dur (les consoles noVNC et xterm.js restent noires dans tous les thèmes). `frontend/public/theme-init.js` applique le thème avant le premier rendu (pas de flash).

## Couleur d'accentuation
Dans le menu « Apparence », **en plus du thème** : huit couleurs prêtes (bleu ciel, violet, vert, ambre, orange, rose, rouge, turquoise), « Défaut » (la couleur du thème) et une **couleur personnalisée** (sélecteur du navigateur). Elle colore les boutons, l'élément actif du menu et les champs actifs ; le choix est gardé dans le navigateur (`localStorage`, clé `kaji-accent`).
- **Lisibilité garantie** (`frontend/src/lib/accent.ts`) : la couleur est **ajustée en luminosité, teinte conservée**, selon le thème réellement appliqué (Auto compris), pour que le texte posé dessus et elle-même posée sur les fonds du thème gardent un contraste WCAG AA (4,5:1). Une couleur personnalisée ajustée le dit (« Ajustée au thème pour rester lisible »).
- **Vérifié par `npm run check:accent`** (étape de la CI) : 838 couleurs (préréglages, extrêmes comme noir, blanc ou jaune pâle, et un balayage aléatoire) sur les fonds LUS dans `src/index.css` (canevas et surfaces des trois thèmes ; pour le verre, les surfaces translucides sur le canevas et sur une zone modérément éclairée du dégradé). Le seuil et les fonds du script sont indépendants du module vérifié.
- **Limite** : au cœur de la tache violette la plus vive du thème Glass, le contraste reste plus bas (c'est déjà le cas de la couleur par défaut du thème).

