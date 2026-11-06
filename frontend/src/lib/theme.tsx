import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export const THEMES = [
  { id: "dark", label: "Sombre", swatch: "linear-gradient(135deg,#111826,#38bdf8)" },
  { id: "glass", label: "Glass", swatch: "linear-gradient(135deg,#7c3aed,#0ea5e9 60%,#ec4899)" },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];

const KEY = "kaji-theme";
const valid = (v: unknown): v is ThemeId => THEMES.some((t) => t.id === v);

function initial(): ThemeId {
  try {
    const v = localStorage.getItem(KEY);
    if (valid(v)) return v;
  } catch { /* stockage indisponible : thème par défaut */ }
  return "dark";
}

const Ctx = createContext<{ theme: ThemeId; setTheme: (t: ThemeId) => void }>({ theme: "dark", setTheme: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeId>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(KEY, theme); } catch { /* ignoré */ }
  }, [theme]);
  return <Ctx.Provider value={{ theme, setTheme }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
