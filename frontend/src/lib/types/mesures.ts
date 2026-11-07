/** Historique des mesures : forme des réponses de `docs/api/mesures.md`. Une valeur absente est `null`, jamais 0. */
export type NodePoint = {
  t: number; cpu: number | null; iowait: number | null; load: number | null; mem_used: number | null; mem_total: number | null;
  swap_used: number | null; swap_total: number | null; net_in: number | null; net_out: number | null;
};
export type GuestPoint = {
  t: number; cpu: number | null; cpus: number | null; mem_used: number | null; mem_total: number | null;
  net_in: number | null; net_out: number | null; disk_read: number | null; disk_write: number | null;
};
export type Metrics<P> = { timeframe: "hour" | "day" | "week" | "month" | "year"; step: number | null; points: P[] };
