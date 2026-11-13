import { tr } from "../i18n";
/** Options du datacenter (`docs/api/datacenter.md`). */
export const KEYBOARDS = ["de", "de-ch", "da", "en-gb", "en-us", "es", "fi", "fr", "fr-be", "fr-ca", "fr-ch", "hu", "is", "it", "ja", "lt", "mk", "nl", "no", "pl", "pt", "pt-br", "sv", "sl", "tr"] as const;
export const LANGUAGES = ["ar", "ca", "da", "de", "en", "es", "eu", "fa", "fr", "hr", "he", "it", "ja", "ka", "kr", "nb", "nl", "nn", "pl", "pt_BR", "ru", "sl", "sv", "tr", "ukr", "zh_CN", "zh_TW"] as const;
export const CONSOLES = ["applet", "vv", "html5", "xtermjs"] as const;

export const SHAPES = ["full", "circle", "dense", "none"] as const;
export const ORDERINGS = ["config", "alphabetical"] as const;
export const USER_ALLOW: Record<string, string> = { get none() { return tr("none : aucune étiquette"); }, get list() { return tr("list : seulement une liste"); }, get existing() { return tr("existing : étiquettes déjà utilisées"); }, get free() { return tr("free : étiquettes libres"); } };
export type TagColor = { tag: string; color: string; text: string | null };
export type TagStyle = { shape: string | null; ordering: string | null; case_sensitive: true | null; color_map: TagColor[] };

export type DatacenterOptions = {
  keyboard: string | null; language: string | null; console: string | null; description: string | null; mac_prefix: string | null; max_workers: number | null;
  email_from: string | null; http_proxy: string | null; migration: { type: "secure" | "insecure" | null; network: string | null };
  next_id: { lower: number | null; upper: number | null }; tag_style: TagStyle;
  registered_tags: string[]; user_tag_access: { user_allow: string | null; user_allow_list: string[] }; consent_text: string | null;
  ha: { shutdown_policy: string | null }; fencing: string | null; crs: { ha: string | null; ha_rebalance_on_start: boolean | null };
  bwlimit: Record<(typeof BW_KEYS)[number], number | null>; replication: { type: "secure" | "insecure" | null; network: string | null };
  webauthn: { allow_subdomains: boolean | null; id: string | null; origin: string | null; rp: string | null };
  readonly: Record<string, string | null>; digest: string;
};
export type DatacenterPreview = { dry_run: true; params: Record<string, string | number>; remove: string[];
  locks: { insecure: boolean; replication_insecure: boolean; ha: boolean; fencing_experimental: boolean; webauthn: boolean; webauthn_break: boolean } };

/** Haute disponibilité, fencing, ordonnancement (CRS), débits (lot #365). */
export const SHUTDOWN_POLICIES = ["conditional", "failover", "freeze", "migrate"] as const;
export const SHUTDOWN_LABELS: Record<string, string> = {
  get conditional() { return tr("conditional : récupère à l'extinction, gèle au redémarrage"); }, get failover() { return tr("failover : récupère toujours"); },
  get freeze() { return tr("freeze : gèle, sans récupération"); }, get migrate() { return tr("migrate : migre les services en marche"); },
};
export const FENCING_MODES = ["watchdog", "hardware", "both"] as const;
export const FENCING_LABELS: Record<string, string> = {
  get watchdog() { return tr("watchdog : fencing logiciel (défaut)"); }, get hardware() { return tr("hardware : appareils de fencing (expérimental)"); }, get both() { return tr("both : les deux (expérimental)"); },
};
export const FENCING_PHRASE = "COUPURE POSSIBLE";
export const CRS_MODES = ["basic", "static"] as const;
export const BW_KEYS = ["clone", "default", "migration", "move", "restore"] as const;
export const BW_LABELS: Record<string, string> = {
  get clone() { return tr("Clonage"); }, get default() { return tr("Par défaut"); }, get migration() { return tr("Migration"); }, get move() { return tr("Déplacement de disque"); }, get restore() { return tr("Restauration"); },
};
