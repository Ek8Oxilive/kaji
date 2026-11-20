import { useEffect, useRef, useState } from "react";
import { LANGS, setLang, tr, useLang } from "../lib/i18n";
import { THEMES, useTheme } from "../lib/theme";

const ITEM = "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition";

/** Un seul bouton « Apparence » qui ouvre le thème et la langue (au lieu de deux sélecteurs toujours affichés). Échap, ou un clic à l'extérieur, le ferme. */
export function AppearanceMenu() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const { theme, setTheme } = useTheme();
  const lang = useLang();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const current = THEMES.find((t) => t.id === theme);
  return (
    <div ref={box} className="relative">
      <button ref={button} type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        title={tr("Apparence : thème et langue")} aria-label={tr("Apparence : thème et langue")}
        className="panel flex items-center gap-2 px-3 py-2 text-sm text-muted transition hover:text-fg">
        <span className="size-3.5 rounded-full ring-1 ring-white/30" style={{ background: current?.swatch }} />
        <span className="hidden sm:inline">{tr("Apparence")}</span>
        <span aria-hidden className="text-xs">▾</span>
      </button>
      {open && (
        <div role="dialog" aria-label={tr("Apparence")} className="panel rise absolute right-0 top-full z-50 mt-2 w-60 space-y-3 p-3">
          <div role="radiogroup" aria-label={tr("Thème")} className="space-y-1">
            <p className="px-2 text-xs font-medium text-muted">{tr("Thème")}</p>
            {THEMES.map((t) => (
              <button key={t.id} type="button" role="radio" aria-checked={theme === t.id} onClick={() => setTheme(t.id)}
                className={`${ITEM} ${theme === t.id ? "bg-accent font-medium text-accentfg" : "text-fg hover:bg-surface2"}`}>
                <span className="size-3.5 shrink-0 rounded-full ring-1 ring-white/30" style={{ background: t.swatch }} />
                {t.label}
              </button>
            ))}
          </div>
          <div role="radiogroup" aria-label={tr("Langue")} className="space-y-1 border-t border-line pt-3">
            <p className="px-2 text-xs font-medium text-muted">{tr("Langue")}</p>
            {LANGS.map((l) => (
              <button key={l.id} type="button" role="radio" aria-checked={lang === l.id} onClick={() => { void setLang(l.id); }}
                className={`${ITEM} ${lang === l.id ? "bg-accent font-medium text-accentfg" : "text-fg hover:bg-surface2"}`}>
                <span className="w-6 shrink-0 text-xs opacity-80">{l.short}</span>
                {l.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
