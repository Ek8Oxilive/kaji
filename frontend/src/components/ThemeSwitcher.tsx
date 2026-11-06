import { THEMES, useTheme } from "../lib/theme";

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();
  return (
    <div role="radiogroup" aria-label="Thème" className="panel flex gap-1 p-1">
      {THEMES.map((t) => (
        <button
          key={t.id}
          role="radio"
          aria-checked={theme === t.id}
          onClick={() => setTheme(t.id)}
          className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition ${
            theme === t.id ? "bg-accent text-accentfg font-medium" : "text-muted hover:text-fg"
          }`}
        >
          <span className="size-3.5 rounded-full ring-1 ring-white/30" style={{ background: t.swatch }} />
          {t.label}
        </button>
      ))}
    </div>
  );
}
