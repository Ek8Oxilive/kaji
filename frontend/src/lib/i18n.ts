import { useSyncExternalStore } from "react";

/**
 * Langue de l'interface (français, anglais). Le texte français du code EST la clé : `tr("Machine {name} démarrée", { name })`.
 * En français, `tr` renvoie la clé telle quelle ; en anglais, elle est cherchée dans `en.json` (clé absente : le français s'affiche, jamais un trou).
 * Le dictionnaire anglais n'est chargé que si l'anglais est choisi. Un test du backend (`tests/test_i18n.py`) vérifie que chaque clé utilisée existe dans `en.json`.
 */
export type Lang = "fr" | "en";
export const LANGS: { id: Lang; short: string; name: string }[] = [{ id: "fr", short: "FR", name: "Français" }, { id: "en", short: "EN", name: "English" }];

const KEY = "kaji-lang";
type Params = Record<string, string | number | boolean | null | undefined>;

let lang: Lang = "fr";
let dict: Record<string, string> = {};
const listeners = new Set<() => void>();

function detect(): Lang {
  try { const v = localStorage.getItem(KEY); if (v === "fr" || v === "en") return v; } catch { /* stockage refusé : langue du navigateur */ }
  return typeof navigator !== "undefined" && /^en\b/i.test(navigator.language) ? "en" : "fr";
}

async function load(l: Lang) {
  // En anglais : le dictionnaire de l'interface, complété par celui des messages que le SERVEUR renvoie (erreurs, catalogue des droits…).
  dict = l === "en" ? { ...(await import("./en-server.json")).default, ...(await import("./en.json")).default } : {};
}

/** À appeler une fois avant le premier rendu : choisit la langue (enregistrée, sinon celle du navigateur) et charge son dictionnaire. */
export async function initLang(): Promise<void> {
  lang = detect();
  await load(lang);
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

export async function setLang(l: Lang): Promise<void> {
  if (l === lang) return;
  await load(l);
  lang = l;
  try { localStorage.setItem(KEY, l); } catch { /* sans stockage : le choix ne survit pas au rechargement */ }
  document.documentElement.lang = l;
  listeners.forEach((f) => f());
}

export const getLang = (): Lang => lang;
export function useLang(): Lang {
  return useSyncExternalStore((cb) => { listeners.add(cb); return () => { listeners.delete(cb); }; }, getLang);
}

/** Traduit un texte (la clé est le français) ; `{nom}` est remplacé par `params.nom`. */
export function tr(key: string, params?: Params): string {
  const s = lang === "en" ? dict[key] ?? key : key;
  return params ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in params ? String(params[k] ?? "") : m)) : s;
}

/** Marque un texte à traduire plus tard (constante de module) ; on le passe ensuite à `tr(variable)` au moment de l'afficher. */
export const T = (s: string): string => s;

/** Langue des dates et des nombres (`toLocaleString`). */
export const locale = (): string => (lang === "en" ? "en-GB" : "fr-FR");
