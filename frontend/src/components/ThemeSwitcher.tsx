import { THEMES, useTheme } from "../lib/theme";

import { tr } from "../lib/i18n";
/** `compact` : pastilles seules (petits écrans) ; le nom reste lu par les lecteurs d'écran. */
export function ThemeSwitcher({ compact }: { compact?: boolean }) {
  const { theme, setTheme } = useTheme();
  return (
    <div role="radiogroup" aria-label={tr("Thème")} className="panel flex gap-1 p-1">
      {THEMES.map((t) => (
        <button
          key={t.id}
          role="radio"
          aria-checked={theme === t.id}
          onClick={() => setTheme(t.id)}
          title={t.label} aria-label={t.label}
          className={`flex items-center gap-2 rounded-lg ${compact ? "p-2.5" : "px-3 py-1.5"} text-sm transition ${
            theme === t.id ? "bg-accent text-accentfg font-medium" : "text-muted hover:text-fg"
          }`}
        >
          <span className="size-3.5 rounded-full ring-1 ring-white/30" style={{ background: t.swatch }} />
          {!compact && t.label}
        </button>
      ))}
    </div>
  );
}
