// Vérifie la couleur d'accentuation : `npm run check:accent` (Node 22.6+ avec --experimental-strip-types, déjà dans le script npm).
// INDÉPENDANT du module vérifié : seuil écrit ici, fonds relus dans `src/index.css` (les vraies variables des thèmes), formule de contraste réécrite.
import { readFileSync } from "node:fs";
import { ACCENT_PRESETS, fitAccent } from "../src/lib/accent.ts";

const SEUIL = 4.5;                                           // WCAG AA, texte courant
const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
const bloc = (selecteur) => { const i = css.indexOf("\n" + selecteur); if (i < 0) throw new Error("thème introuvable : " + selecteur); return css.slice(i, css.indexOf("}", i)); };
const lire = (b, nom) => { const m = new RegExp("--" + nom + ":\\s*([^;]+);").exec(b); if (!m) throw new Error("variable introuvable : " + nom); return m[1].trim(); };
const num = (x) => parseInt(x, 16);
function couleur(v, dessous = [0, 0, 0]) {                   // #rrggbb ou rgb(r g b / a) composé sur `dessous`
  let m = /^#([0-9a-f]{6})$/i.exec(v);
  if (m) return [num(m[1].slice(0, 2)), num(m[1].slice(2, 4)), num(m[1].slice(4, 6))];
  m = /^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\/\s*([\d.]+)\s*\)$/.exec(v);
  if (!m) throw new Error("couleur illisible : " + v);
  const a = +m[4];
  return [0, 1, 2].map((i) => Math.round(+m[i + 1] * a + dessous[i] * (1 - a)));
}
const hex = (c) => "#" + c.map((x) => x.toString(16).padStart(2, "0")).join("");
const canal = (x) => { const s = x / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
const lum = (h) => { const c = couleur(h); return 0.2126 * canal(c[0]) + 0.7152 * canal(c[1]) + 0.0722 * canal(c[2]); };
const contraste = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

const sombre = bloc(':root,\n:root[data-theme="dark"] {'), clair = bloc(':root[data-theme="light"] {'), verre = bloc(':root[data-theme="glass"] {');
const fondsOpaques = (b) => ["canvas", "surface", "surface2"].map((n) => hex(couleur(lire(b, n))));
const canvasVerre = couleur(lire(verre, "canvas"));
// Verre : surfaces translucides, vues sur le canevas ET sur une zone modérément éclairée du dégradé violet (le quart de la tache la plus vive : le cœur de la tache, rarement sous du texte, ne tient pas ce seuil même avec la couleur par défaut du thème).
const tacheVerre = couleur("rgb(124 58 237 / 0.25)", canvasVerre);
const fondsVerre = [hex(canvasVerre), ...["surface", "surface2"].flatMap((n) => [hex(couleur(lire(verre, n), canvasVerre)), hex(couleur(lire(verre, n), tacheVerre))])];
const FONDS = { dark: [...fondsOpaques(sombre), ...fondsVerre], light: fondsOpaques(clair) };
if (FONDS.dark.length !== 8 || FONDS.light.length !== 3) throw new Error("fonds de thème inattendus : " + JSON.stringify(FONDS));

let bad = 0, checked = 0;
const fail = (msg) => { bad++; console.error("ÉCHEC : " + msg); };
const check = (h, mode, label) => {
  const f = fitAccent(h, mode);
  checked++;
  if (!f) return fail(`${label} ${h} (${mode}) : aucune version lisible`);
  for (const bg of FONDS[mode]) if (contraste(f.accent, bg) < SEUIL) fail(`${label} ${h} (${mode}) : ${f.accent} sur ${bg} = ${contraste(f.accent, bg).toFixed(2)}`);
  if (contraste(f.accent, f.fg) < SEUIL) fail(`${label} ${h} (${mode}) : texte ${f.fg} sur ${f.accent} = ${contraste(f.accent, f.fg).toFixed(2)}`);
};
for (const p of ACCENT_PRESETS) for (const mode of ["dark", "light"]) check(p.hex, mode, `préréglage ${p.id}`);
let seed = 12345; const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const h2 = () => Math.floor(rnd() * 256).toString(16).padStart(2, "0");
for (const h of ["#000000", "#ffffff", "#808080", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff", "#010101", "#fefefe"]) for (const mode of ["dark", "light"]) check(h, mode, "extrême");
for (let i = 0; i < 400; i++) for (const mode of ["dark", "light"]) check("#" + h2() + h2() + h2(), mode, "aléatoire");
for (const mauvais of ["", "red", "#fff", "#12345g", "#1234567", null, undefined, 42]) if (fitAccent(mauvais, "dark") !== null) fail(`valeur invalide acceptée : ${String(mauvais)}`);
if (new Set(ACCENT_PRESETS.map((p) => p.id)).size !== ACCENT_PRESETS.length) fail("identifiants de préréglage en double");
console.log(`${checked} couleurs vérifiées sur ${FONDS.dark.length} fonds sombres et ${FONDS.light.length} fonds clairs, ${bad} échec(s).`);
process.exit(bad ? 1 : 0);
