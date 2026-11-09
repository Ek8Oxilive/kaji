/** Types de la haute disponibilité et de la réplication (`docs/api/ha.md`), lecture seule. */
export type HaStatus = { type: "quorum" | "master" | "lrm" | "service" | "fencing"; id: string | null; node: string | null; status: string | null; state: string | null; sid: string | null; quorate: boolean | null; armed_state: string | null };
export type HaResource = { sid: string; type: string | null; state: string | null; max_restart: number | null; max_relocate: number | null; failback: boolean | null; comment: string | null };
export type HaRule = { rule: string; type: string; resources: string[]; nodes: { node: string; priority: number | null }[]; strict: boolean | null; affinity: string | null; disable: boolean | null; comment: string | null };
export type ReplJob = { id: string; guest: number | null; source: string | null; target: string | null; schedule: string | null; rate: number | null; disable: boolean | null; comment: string | null };
export type ReplStatus = { id: string; last_sync: number | null; next_sync: number | null; duration: number | null; fail_count: number | null; error: string | null };

/** Écriture HA (M8-2, `docs/api/ha-ecriture.md`) : aperçu `dry_run` et verrous décidés par le serveur. */
export type HaLocks = { cut: string[]; live: string[]; inert: boolean };
export type HaPreview = { dry_run: true; params?: Record<string, string | number>; remove?: string[]; from?: string; comigrated?: string[]; locks: HaLocks; phrase: string | null };
export type HaMoveResult = { requested: string; from: string; blocking: { sid: string; cause: string | null }[]; comigrated: string[] };
export type HaMode =
  | { kind: "resource-new" }
  | { kind: "resource-edit"; resource: HaResource }
  | { kind: "resource-delete"; resource: HaResource }
  | { kind: "migrate" | "relocate"; resource: HaResource }
  | { kind: "rule-new" }
  | { kind: "rule-edit"; rule: HaRule }
  | { kind: "rule-delete"; rule: HaRule };
