export type ClusterLogEntry = { time: number | null; pri: number; tag: string; node: string; user: string | null; pid: number | null; msg: string };
export type ClusterLog = { entries: ClusterLogEntry[] };
