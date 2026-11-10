/** Options du datacenter (`docs/api/datacenter.md`). */
export const KEYBOARDS = ["de", "de-ch", "da", "en-gb", "en-us", "es", "fi", "fr", "fr-be", "fr-ca", "fr-ch", "hu", "is", "it", "ja", "lt", "mk", "nl", "no", "pl", "pt", "pt-br", "sv", "sl", "tr"] as const;
export const LANGUAGES = ["ar", "ca", "da", "de", "en", "es", "eu", "fa", "fr", "hr", "he", "it", "ja", "ka", "kr", "nb", "nl", "nn", "pl", "pt_BR", "ru", "sl", "sv", "tr", "ukr", "zh_CN", "zh_TW"] as const;
export const CONSOLES = ["applet", "vv", "html5", "xtermjs"] as const;

export const SHAPES = ["full", "circle", "dense", "none"] as const;
export const ORDERINGS = ["config", "alphabetical"] as const;
export type TagColor = { tag: string; color: string; text: string | null };
export type TagStyle = { shape: string | null; ordering: string | null; case_sensitive: true | null; color_map: TagColor[] };

export type DatacenterOptions = {
  keyboard: string | null; language: string | null; console: string | null; description: string | null; mac_prefix: string | null; max_workers: number | null;
  email_from: string | null; http_proxy: string | null; migration: { type: "secure" | "insecure" | null; network: string | null };
  next_id: { lower: number | null; upper: number | null }; tag_style: TagStyle;
  readonly: Record<string, string | null>; digest: string;
};
export type DatacenterPreview = { dry_run: true; params: Record<string, string | number>; remove: string[]; locks: { insecure: boolean } };
