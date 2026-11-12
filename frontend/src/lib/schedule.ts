import { tr, T } from "./i18n";
/**
 * Planification d'un job. Le serveur n'accepte qu'une grammaire stricte : `HH:MM`, précédée si on veut de jours
 * (`mon`, `mon,wed`, `mon..fri`), séparés par UN espace. On la construit à partir de jours cochés et d'une heure.
 */
export const DAYS = [
  { id: "mon", short: T("Lun"), long: "lundi" }, { id: "tue", short: T("Mar"), long: "mardi" }, { id: "wed", short: T("Mer"), long: "mercredi" },
  { id: "thu", short: T("Jeu"), long: "jeudi" }, { id: "fri", short: T("Ven"), long: "vendredi" }, { id: "sat", short: T("Sam"), long: "samedi" },
  { id: "sun", short: T("Dim"), long: "dimanche" },
] as const;
const ORDER: string[] = DAYS.map((d) => d.id);

/** Tous les jours : on n'écrit pas de jours (le serveur lit `02:00` comme « chaque jour »). */
export function buildSchedule(days: string[], time: string): string {
  const picked = ORDER.filter((d) => days.includes(d));
  return picked.length === 0 || picked.length === 7 ? time : `${picked.join(",")} ${time}`;
}

/** Relit une planification ; `null` si elle n'a pas la forme que Kaji sait écrire (créée ailleurs, par exemple). */
export function parseSchedule(s: string | null): { days: string[]; time: string } | null {
  const m = s?.match(/^(?:([a-z.,]+) )?([01][0-9]|2[0-3]):([0-5][0-9])$/);
  if (!m) return null;
  const days = new Set<string>();
  for (const part of (m[1] ?? ORDER.join(",")).split(",")) {
    const [a, b] = part.split("..");
    if (!ORDER.includes(a) || (b !== undefined && !ORDER.includes(b))) return null;
    if (b === undefined) days.add(a);
    else for (let i = ORDER.indexOf(a); i <= ORDER.indexOf(b); i++) days.add(ORDER[i]);
  }
  return { days: ORDER.filter((d) => days.has(d)), time: `${m[2]}:${m[3]}` };
}

export function describeSchedule(s: string | null): string {
  const p = parseSchedule(s);
  if (!p) return s ?? "–";
  if (p.days.length === 7) return tr("Tous les jours à {time}", { time: p.time });
  return tr("{p} à {time}", { p: p.days.map((d) => DAYS.find((x) => x.id === d)!.short).join(", "), time: p.time });
}
