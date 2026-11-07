/** Système d'un nœud : forme des réponses de `docs/api/systeme-noeud.md`. */
export type Section<T> = { state: "ok" | "forbidden" | "error"; data: T | null };
export type Repo = { index: number; types: string[]; uris: string[]; suites: string[]; components: string[]; enabled: boolean };
export type RepoInfo = { files: { path: string | null; repositories: Repo[] }[]; errors: number; digest: string | null; standard: { handle: string | null; name: string | null; description: string | null; status: 0 | 1 | null }[] };
export type ServiceAction = "start" | "stop" | "restart" | "reload";
export type Service = {
  name: string; description: string | null; state: string | null; active: string | null; enabled: string | null;
  manageable: boolean; risk: "normal" | "sensitive" | "vital"; stoppable: boolean;
};
export type NodeSystem = {
  status: Section<{ pveversion: string | null; kernel: string | null; uptime: number | null; boot_mode: string | null }>;
  time: Section<{ timezone: string | null; time: string | null; localtime: string | null }>;
  dns: Section<{ search: string | null; servers: string[] }>;
  services: Section<Service[]>;
  updates: Section<{ package: string; from: string | null; to: string | null; title: string | null; origin: string | null }[]>;
  versions: Section<{ installed: number; key: { package: string; version: string | null }[] }>;
  repositories: Section<RepoInfo>;
  certificates: Section<{ file: string | null; subject: string | null; issuer: string | null; not_before: string | null; not_after: string | null; fingerprint: string | null; san: string[] }[]>;
  disks: Section<{ device: string; model: string | null; type: string | null; size: number | null; health: string | null; wearout: number | null; used: string | null; gpt: boolean }[]>;
  subscription: Section<{ status: string | null }>;
};
export type SyslogLines = { lines: { n: number; text: string }[] };
