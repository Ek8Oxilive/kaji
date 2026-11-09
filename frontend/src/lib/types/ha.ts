/** Types de la haute disponibilité et de la réplication (`docs/api/ha.md`), lecture seule. */
export type HaStatus = { type: "quorum" | "master" | "lrm" | "service" | "fencing"; id: string | null; node: string | null; status: string | null; state: string | null; sid: string | null; quorate: boolean | null; armed_state: string | null };
export type HaResource = { sid: string; type: string | null; state: string | null; max_restart: number | null; max_relocate: number | null; failback: boolean | null; comment: string | null };
export type HaRule = { rule: string; type: string; resources: string[]; nodes: { node: string; priority: number | null }[]; strict: boolean | null; affinity: string | null; disable: boolean | null; comment: string | null };
export type ReplJob = { id: string; guest: number | null; source: string | null; target: string | null; schedule: string | null; rate: number | null; disable: boolean | null; comment: string | null };
export type ReplStatus = { id: string; last_sync: number | null; next_sync: number | null; duration: number | null; fail_count: number | null; error: string | null };
