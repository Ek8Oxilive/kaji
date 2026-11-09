/** Notifications (`docs/api/notifications.md`), lecture seule : aucun secret n'est renvoyé. */
export type NotifType = "sendmail" | "smtp" | "gotify" | "webhook";
export type NotifTarget = { name: string; type: NotifType; disable: boolean; comment: string | null; origin: string | null; builtin: boolean; used_by: string[] };
export type NotifEndpoint = {
  name: string; type: NotifType; disable: boolean; comment: string | null; origin: string | null; builtin: boolean;
  author?: string | null; from_address?: string | null; mailto?: string[]; mailto_user?: string[]; server?: string | null; port?: number | null; mode?: string | null; username?: string | null;
  url?: string | null; method?: string | null; header_names?: string[]; secret_names?: string[]; body_set?: boolean;
};
export type NotifMatcher = {
  name: string; disable: boolean; invert: boolean; mode: "all" | "any"; match_field: string[]; match_severity: string[]; match_calendar: string[]; targets: string[]; comment: string | null; origin: string | null; builtin: boolean;
};
export type Notifications = { targets: NotifTarget[]; endpoints: Record<NotifType, NotifEndpoint[]>; matchers: NotifMatcher[]; fields: string[]; errors: Record<string, string>; unused_targets: string[] };
export const TYPE_LABEL: Record<NotifType, string> = { sendmail: "Sendmail (e-mail local)", smtp: "SMTP", gotify: "Gotify", webhook: "Webhook" };
