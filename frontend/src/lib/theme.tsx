import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { fitAccent, isHex } from "./accent";
import { tr } from "./i18n";
/** `auto` suit le réglage clair / sombre du système (`prefers-color-scheme`) et le suit s'il change ; les autres sont fixes. */
export const THEMES = [
  { id: "dark", get label() { return tr("Sombre"); }, swatch: "linear-gradient(135deg,#111826,#38bdf8)" },
  { id: "glass", get label() { return tr("Glass"); }, swatch: "linear-gradient(135deg,#7c3aed,#0ea5e9 60%,#ec4899)" },
  { id: "light", get label() { return tr("Clair"); }, swatch: "linear-gradient(135deg,#ffffff,#0369a1)" },
  { id: "auto", get label() { return tr("Auto"); }, swatch: "linear-gradient(90deg,#111826 50%,#ffffff 50%)" },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];

const KEY = "kaji-theme";
const valid = (v: unknown): v is ThemeId => THEMES.some((t) => t.id === v);
const query = () => (typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: light)") : null);
/** Thème réellement appliqué (`data-theme`) : `auto` devient `light` ou `dark` selon le système. */
export const resolveTheme = (t: ThemeId): "dark" | "glass" | "light" => (t === "auto" ? (query()?.matches ? "light" : "dark") : t);

function initial(): ThemeId {
  try {
    const v = localStorage.getItem(KEY);
    if (valid(v)) return v;
  } catch { /* stockage indisponible : thème par défaut */ }
  return "dark";
}

const ACCENT_KEY = "kaji-accent";
function initialAccent(): string | null {
  try { const v = localStorage.getItem(ACCENT_KEY); if (isHex(v)) return v; } catch { /* stockage indisponible : couleur du thème */ }
  return null;
}
/** Pose (ou retire) la couleur d'accentuation choisie ; elle est ajustée pour rester lisible sur le thème réellement appliqué. */
function applyAccent(accent: string | null, applied: "dark" | "glass" | "light") {
  const style = document.documentElement.style;
  const fitted = accent ? fitAccent(accent, applied === "light" ? "light" : "dark") : null;
  if (!fitted) { style.removeProperty("--accent"); style.removeProperty("--accentfg"); return; }
  style.setProperty("--accent", fitted.accent);
  style.setProperty("--accentfg", fitted.fg);
}

const Ctx = createContext<{ theme: ThemeId; setTheme: (t: ThemeId) => void; accent: string | null; setAccent: (c: string | null) => void }>(
  { theme: "dark", setTheme: () => {}, accent: null, setAccent: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeId>(initial);
  const [accent, setAccent] = useState<string | null>(initialAccent);
  useEffect(() => {
    const apply = () => { const applied = resolveTheme(theme); document.documentElement.dataset.theme = applied; applyAccent(accent, applied); };
    apply();
    try { localStorage.setItem(KEY, theme); } catch { /* ignoré */ }
    try { if (accent) localStorage.setItem(ACCENT_KEY, accent); else localStorage.removeItem(ACCENT_KEY); } catch { /* ignoré */ }
    if (theme !== "auto") return;
    const q = query();                                   // `auto` : on suit le système tant qu'il est choisi
    q?.addEventListener("change", apply);
    return () => q?.removeEventListener("change", apply);
  }, [theme, accent]);
  return <Ctx.Provider value={{ theme, setTheme, accent, setAccent }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
