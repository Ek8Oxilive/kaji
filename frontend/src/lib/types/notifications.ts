import { tr } from "../i18n";
/** Notifications (`docs/api/notifications.md`) : aucun secret n'est renvoyé (mot de passe, jeton, valeurs d'en-têtes : écriture seule). */
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
export const TYPE_LABEL: Record<NotifType, string> = { sendmail: "Sendmail (e-mail local)", smtp: "SMTP", get gotify() { return tr("Gotify"); }, get webhook() { return tr("Webhook"); } };
export type NotifPreview = { dry_run: true; params?: Record<string, string | number | string[]>; remove?: string[]; retype?: string; sends_a_real_message?: boolean };
export type NotifDetail = NotifEndpoint & { digest: string };
export type NotifMatcherDetail = NotifMatcher & { digest: string };
export const SEVERITIES = ["info", "notice", "warning", "error", "unknown"] as const;
