/** Notifications du datacenter, lecture seule (`docs/api/notifications.md`). Aucun secret n'est renvoyé : seuls les NOMS d'en-têtes et de secrets d'un webhook, et « corps défini ». */
export type NotifType = "sendmail" | "smtp" | "gotify" | "webhook";
export type NotifOrigin = "builtin" | "user-created" | "modified-builtin" | null;
export type NotifEndpoint = {
  name: string; type: NotifType; comment: string | null; disable: boolean; origin: NotifOrigin;
  author?: string | null; from_address?: string | null; mailto?: string[]; mailto_user?: string[];                   // sendmail, smtp
  server?: string | null; port?: number | null; mode?: string | null; username?: string | null;                     // smtp, gotify (server)
  url?: string | null; method?: string | null; header_names?: string[]; secret_names?: string[]; body_set?: boolean;   // webhook
};
export type NotifEndpoints = { endpoints: Record<NotifType, NotifEndpoint[]>; unavailable: NotifType[] };
export type NotifMatcher = {
  name: string; comment: string | null; disable: boolean; mode: "all" | "any"; invert_match: boolean; origin: NotifOrigin;
  match_field: string[]; match_severity: string[]; match_calendar: string[]; target: string[];
};

export const NOTIF_TYPES: NotifType[] = ["sendmail", "smtp", "gotify", "webhook"];
export const NOTIF_LABEL: Record<NotifType, string> = { sendmail: "Sendmail", smtp: "SMTP", gotify: "Gotify", webhook: "Webhook" };
export const ORIGIN_LABEL: Record<string, string> = { builtin: "intégrée", "user-created": "créée", "modified-builtin": "intégrée modifiée" };

/** Une ligne de résumé pour une cible, sans secret. */
export function endpointSummary(e: NotifEndpoint): string {
  const to = [...(e.mailto_user ?? []), ...(e.mailto ?? [])].join(", ");
  switch (e.type) {
    case "sendmail": return to ? `À : ${to}` : "Destinataire non défini";
    case "smtp": return `${e.server ?? "?"}${e.port ? `:${e.port}` : ""}${e.mode ? ` (${e.mode})` : ""}${to ? ` · à : ${to}` : ""}`;
    case "gotify": return e.server ?? "Serveur illisible";
    case "webhook": return `${(e.method ?? "post").toUpperCase()} ${e.url ?? "adresse illisible"}${(e.header_names?.length ?? 0) > 0 ? ` · ${e.header_names!.length} en-tête(s)` : ""}`;
  }
}

/** Ce sur quoi une règle porte, en une phrase. */
export function matcherSummary(m: NotifMatcher): string {
  const parts = [
    m.match_severity.length ? `gravité : ${m.match_severity.join(", ")}` : "",
    m.match_field.length ? `champs : ${m.match_field.join(", ")}` : "",
    m.match_calendar.length ? `calendrier : ${m.match_calendar.join(", ")}` : "",
  ].filter(Boolean);
  const body = parts.length ? parts.join(" · ") : "tout";
  return `${m.invert_match ? "sauf " : ""}${body}${parts.length > 1 ? ` (${m.mode === "any" ? "l'un des critères" : "tous les critères"})` : ""}`;
}
