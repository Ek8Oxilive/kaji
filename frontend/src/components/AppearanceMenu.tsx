import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ACCENT_PRESETS, fitAccent } from "../lib/accent";
import { LANGS, setLang, tr, useLang } from "../lib/i18n";
import { THEMES, resolveTheme, useTheme } from "../lib/theme";

const ITEM = "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition";
const WIDTH = 264;
const ACCENT_NAMES: Record<string, () => string> = {
  sky: () => tr("Bleu ciel"), violet: () => tr("Violet"), emerald: () => tr("Vert"), amber: () => tr("Ambre"),
  orange: () => tr("Orange"), rose: () => tr("Rose"), red: () => tr("Rouge"), teal: () => tr("Turquoise"),
};
type Place = { left: number; top?: number; bottom?: number; maxHeight: number };

/**
 * Un seul bouton « Apparence » : thème, couleur d'accentuation et langue. `sidebar` : bouton pleine largeur de la barre latérale (le menu s'ouvre vers le haut) ;
 * `floating` : petit bouton isolé (écran de connexion). Le menu est rendu hors de la barre (portail) : elle défile et le couperait. Échap ou un clic à l'extérieur le ferme.
 */
export function AppearanceMenu({ variant = "floating" }: { variant?: "sidebar" | "floating" }) {
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<Place | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const { theme, setTheme, accent, setAccent } = useTheme();
  const lang = useLang();

  const toggle = () => {
    if (open) { setOpen(false); return; }
    const r = button.current?.getBoundingClientRect();
    if (r) {
      const left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - WIDTH - 8));
      setPlace(r.top > window.innerHeight / 2
        ? { left, bottom: window.innerHeight - r.top + 8, maxHeight: r.top - 16 }
        : { left, top: r.bottom + 8, maxHeight: window.innerHeight - r.bottom - 16 });
    }
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { const t = e.target as Node; if (!pop.current?.contains(t) && !button.current?.contains(t)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    const close = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); window.removeEventListener("resize", close); };
  }, [open]);

  const current = THEMES.find((t) => t.id === theme);
  const mode = resolveTheme(theme) === "light" ? "light" : "dark";
  const isPreset = (c: string | null) => ACCENT_PRESETS.some((p) => p.hex === c);
  const customFit = accent && !isPreset(accent) ? fitAccent(accent, mode) : null;
  const adjusted = !!customFit && customFit.accent.toLowerCase() !== accent!.toLowerCase();

  return (
    <>
      <button ref={button} type="button" aria-haspopup="dialog" aria-expanded={open} onClick={toggle}
        title={tr("Apparence : thème, couleur et langue")} aria-label={tr("Apparence : thème, couleur et langue")}
        className={variant === "sidebar"
          ? "flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-surface2 px-4 py-2 text-sm text-fg transition hover:brightness-125"
          : "panel flex items-center gap-2 px-3 py-2 text-sm text-muted transition hover:text-fg"}>
        <span className="size-3.5 rounded-full ring-1 ring-white/30" style={{ background: current?.swatch }} />
        <span>{tr("Apparence")}</span>
        <span aria-hidden className="text-xs">▾</span>
      </button>
      {open && place && createPortal(
        <div ref={pop} role="dialog" aria-label={tr("Apparence")} style={{ position: "fixed", left: place.left, top: place.top, bottom: place.bottom, maxHeight: place.maxHeight, width: WIDTH }}
          className="panel rise z-[70] space-y-3 overflow-y-auto p-3">
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
          <div role="radiogroup" aria-label={tr("Couleur d'accentuation")} className="space-y-2 border-t border-line pt-3">
            <p className="px-2 text-xs font-medium text-muted">{tr("Couleur d'accentuation")}</p>
            <div className="flex flex-wrap items-center gap-2 px-1">
              <button type="button" role="radio" aria-checked={accent === null} onClick={() => setAccent(null)} title={tr("Par défaut du thème")}
                className={`rounded-full border px-2.5 py-1 text-xs transition ${accent === null ? "border-accent bg-accent font-medium text-accentfg" : "border-line text-fg hover:bg-surface2"}`}>
                {tr("Défaut")}
              </button>
              {ACCENT_PRESETS.map((p) => (
                <button key={p.id} type="button" role="radio" aria-checked={accent === p.hex} onClick={() => setAccent(p.hex)}
                  title={ACCENT_NAMES[p.id]()} aria-label={ACCENT_NAMES[p.id]()}
                  className={`size-6 rounded-full ring-offset-2 ring-offset-transparent transition hover:scale-110 ${accent === p.hex ? "ring-2 ring-fg" : "ring-1 ring-white/30"}`}
                  style={{ background: p.hex }} />
              ))}
              <label title={tr("Couleur personnalisée")}
                className={`relative grid size-6 cursor-pointer place-items-center overflow-hidden rounded-full text-[10px] transition hover:scale-110 ${accent && !isPreset(accent) ? "ring-2 ring-fg" : "ring-1 ring-white/30"}`}
                style={{ background: accent && !isPreset(accent) ? accent : "conic-gradient(#f87171,#fbbf24,#34d399,#38bdf8,#a78bfa,#f472b6,#f87171)" }}>
                <input type="color" aria-label={tr("Couleur personnalisée")} value={accent ?? "#38bdf8"} onChange={(e) => setAccent(e.target.value)}
                  className="absolute inset-0 size-full cursor-pointer opacity-0" />
              </label>
            </div>
            {adjusted && <p className="px-2 text-xs text-muted">{tr("Ajustée au thème pour rester lisible.")}</p>}
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
        </div>, document.body)}
    </>
  );
}
