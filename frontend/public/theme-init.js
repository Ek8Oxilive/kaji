// Applique le thème enregistré avant le premier rendu (évite le flash).
// Fichier séparé : la politique de sécurité (CSP) du serveur interdit les scripts en ligne.
try {
  var t = localStorage.getItem("kaji-theme");
  if (t === "dark" || t === "glass") document.documentElement.dataset.theme = t;
} catch (e) {}
