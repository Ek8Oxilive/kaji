// Applique le thème enregistré avant le premier rendu (évite le flash).
// Fichier séparé : la politique de sécurité (CSP) du serveur interdit les scripts en ligne.
try {
  var t = localStorage.getItem("kaji-theme");
  if (t === "auto") t = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  if (t === "dark" || t === "glass" || t === "light") document.documentElement.dataset.theme = t;
} catch (e) {}
