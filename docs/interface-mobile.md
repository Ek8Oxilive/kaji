# Interface sur petit écran (téléphone, petit PC)

Frontend seul, aucune route. Points de rupture Tailwind : `sm` 640 px, `md` 768 px, `lg` 1024 px.

| Largeur | Mise en page |
|---|---|
| < 768 px | Barre du haut collante (bouton menu ☰, logo, thème en pastilles) ; la navigation s'ouvre dans un **tiroir** (fermé par ✕, Échap, clic à l'extérieur ou le choix d'une page). Page en pleine largeur. |
| 768 – 1023 px | Barre latérale étroite (12 rem). |
| ≥ 1024 px | Barre latérale de 15 rem (mise en page d'origine). |

Autres adaptations :
- **Barre de tâches** : repliée par défaut sous 768 px (le choix de l'utilisateur est conservé) ; sous 640 px, le nœud et la durée sont cachés.
- **Fenêtres** (`Modal`) : marges réduites, hauteur `94dvh`, boutons qui passent à la ligne ; leurs grilles de champs s'empilent sous 640 px.
- **Écrans tactiles** (`pointer: coarse`) : champs de 2,75 rem de haut, texte de 16 px (pas de zoom automatique sur iOS).
- **Tableaux** : défilement horizontal dans leur cadre (déjà le cas) ; la page elle-même ne défile jamais horizontalement (`overflow-x: clip`).

Vérification : Chrome ne descend pas sous ~700 px de fenêtre ; la largeur d'un téléphone se simule avec un zoom CSS de la page (`document.documentElement.style.zoom = 1.8` donne environ 390 px de mise en page, avec les points de rupture d'une fenêtre de 700 px).
