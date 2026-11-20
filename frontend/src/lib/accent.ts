/**
 * Couleur d'accentuation (boutons, éléments actifs) choisie en plus du thème. Module PUR (aucune dépendance) : un script Node le vérifie
 * (`npm run check:accent`) : quelle que soit la couleur, le texte posé dessus et elle-même posée sur les fonds du thème gardent un contraste WCAG AA (4,5:1).
 * Une couleur trop claire (thèmes sombres) ou trop sombre (thème clair) est ajustée en luminosité, teinte conservée.
 */
export type AccentMode = "dark" | "light";
export const ACCENT_PRESETS = [
  { id: "sky", hex: "#38bdf8" },
  { id: "violet", hex: "#a78bfa" },
  { id: "emerald", hex: "#34d399" },
  { id: "amber", hex: "#fbbf24" },
  { id: "orange", hex: "#fb923c" },
  { id: "rose", hex: "#f472b6" },
  { id: "red", hex: "#f87171" },
  { id: "teal", hex: "#2dd4bf" },
] as const;

/** Fonds sur lesquels l'accent sert de texte ou de pastille : `canvas`, `surface`, `surface2` de chaque thème (le verre : les surfaces translucides sur le canevas et sur une zone modérément éclairée du dégradé violet ; valeurs relues dans `index.css` par `scripts/check-accent.mjs`). */
export const ACCENT_BACKGROUNDS: Record<AccentMode, string[]> = {
  dark: ["#0a0e16", "#111826", "#182133", "#0b0a1f", "#1c1b2f", "#36265f", "#28273a", "#413268"],
  light: ["#ffffff", "#f3f5f9", "#eef1f6"],
};
export const ACCENT_FG_DARK = "#04121c";
export const ACCENT_FG_LIGHT = "#ffffff";
export const MIN_CONTRAST = 4.5;
/** Marge à l'ajustement : les fonds translucides du verre sont arrondis à l'octet, un contraste de 4,49 passerait sinon. */
const FIT_MARGIN = 0.1;

export const isHex = (v: unknown): v is string => typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v);

const channel = (c: number) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
function rgb(hex: string): [number, number, number] { return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]; }
const luminance = (hex: string) => { const [r, g, b] = rgb(hex); return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b); };
export function contrast(a: string, b: string): number { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }

function toHsl(hex: string): [number, number, number] {
  const [r, g, b] = rgb(hex).map((v) => v / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  if (d === 0) return [0, 0, l * 100];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s * 100, l * 100];
}
function fromHsl(h: number, s: number, l: number): string {
  const S = s / 100, L = l / 100, c = (1 - Math.abs(2 * L - 1)) * S, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = L - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return "#" + [r, g, b].map((v) => Math.round((v + m) * 255).toString(16).padStart(2, "0")).join("");
}

/** Couleur du texte posé SUR l'accent : la plus lisible des deux. */
export const accentForeground = (accent: string) => (contrast(accent, ACCENT_FG_DARK) >= contrast(accent, ACCENT_FG_LIGHT) ? ACCENT_FG_DARK : ACCENT_FG_LIGHT);

function readable(accent: string, mode: AccentMode): boolean {
  return ACCENT_BACKGROUNDS[mode].every((bg) => contrast(accent, bg) >= MIN_CONTRAST + FIT_MARGIN) && contrast(accent, accentForeground(accent)) >= MIN_CONTRAST + FIT_MARGIN;
}

/** Ajuste la luminosité jusqu'à un contraste suffisant ; `null` si la couleur est invalide ou si aucune luminosité ne convient (on garde alors le thème). */
export function fitAccent(hex: string, mode: AccentMode): { accent: string; fg: string } | null {
  if (!isHex(hex)) return null;
  const [h, s, l0] = toHsl(hex);
  let l = l0;
  const step = mode === "dark" ? 1 : -1;
  for (let i = 0; i <= 100; i++) {
    const candidate = fromHsl(h, s, Math.min(100, Math.max(0, l)));
    if (readable(candidate, mode)) return { accent: candidate, fg: accentForeground(candidate) };
    l += step;
  }
  return null;
}
