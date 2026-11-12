import { LANGS, setLang, useLang } from "../lib/i18n";

/** Choix de la langue (FR / EN) : même forme que le sélecteur de thème ; le choix est gardé dans le navigateur. */
export function LanguageSwitcher() {
  const lang = useLang();
  return (
    <div role="radiogroup" aria-label={lang === "en" ? "Language" : "Langue"} className="panel flex gap-1 p-1">
      {LANGS.map((l) => (
        <button key={l.id} role="radio" aria-checked={lang === l.id} title={l.name} aria-label={l.name} onClick={() => { void setLang(l.id); }}
          className={`rounded-lg px-3 py-1.5 text-sm transition ${lang === l.id ? "bg-accent text-accentfg font-medium" : "text-muted hover:text-fg"}`}>
          {l.short}
        </button>
      ))}
    </div>
  );
}
