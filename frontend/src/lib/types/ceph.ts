/** Types de la page « Ceph » (lecture seule) : formes des réponses de `docs/api/ceph.md`.
 *  Ces formes sont des hypothèses : elles n'ont jamais été vues sur un vrai Ceph (le cluster de test n'en a pas). */

export type CephHealth = "HEALTH_OK" | "HEALTH_WARN" | "HEALTH_ERR" | "UNKNOWN";

/** Réponse de TOUTES les routes quand Ceph n'est pas installé (200, pas une erreur). */
export type CephAbsent = { installed: false; message: string };
export type Ceph<T> = ({ installed: true; node?: string } & T) | CephAbsent;

export type CephCheck = { code: string; severity: CephHealth; message: string; count: number | null; muted: boolean; details: string[] };
export type CephStatus = {
  health: { status: CephHealth; checks: CephCheck[] };
  osds: { total: number | null; up: number | null; in: number | null };
  mons: { total: number | null; quorum: string[] };
  mgr: { active: string | null; standbys: number; available: boolean | null };
  pgs: { total: number | null; states: { state: string; count: number }[]; all_clean: boolean };
  usage: { total: number | null; used: number | null; avail: number | null; percent: number | null };
  io: { read_bytes_sec: number | null; write_bytes_sec: number | null; read_ops: number | null; write_ops: number | null };
};

export type CephOsd = {
  id: number | null; name: string; host: string | null; up: boolean | null; in: boolean | null; device_class: string | null;
  crush_weight: number | null; reweight: number | null; percent_used: number | null; used: number | null; total: number | null;
  pgs: number | null; version: string | null;
};
export type CephOsds = { osds: CephOsd[]; flags: string[]; summary: { total: number; up: number; in: number } };

export type CephPool = {
  name: string; id: number | null; type: string | null; size: number | null; min_size: number | null; pg_num: number | null;
  crush_rule: string | null; autoscale: string | null; used: number | null; percent_used: number | null; applications: string[]; warnings: string[];
};
export type CephPools = { pools: CephPool[] };

export type CephFilesystems = {
  filesystems: { name: string; metadata_pool: string | null; data_pools: string[] }[];
  mds: { name: string; host: string | null; addr: string | null; rank: number | null; state: string | null }[];
};

export type CephMon = { name: string; host: string | null; addr: string | null; rank: number | null; in_quorum: boolean | null; state: string | null; version: string | null };
export type CephMonitors = { monitors: CephMon[] };
export type CephMgr = { name: string; host: string | null; addr: string | null; state: string | null; version: string | null };
export type CephManagers = { managers: CephMgr[] };

// ---- écriture des pools (lot C2) : docs/api/ceph.md. JAMAIS validé sur un vrai Ceph. ----
export type CephRules = { rules: { name: string; id: number | null }[] };
export type PoolAutoscale = "on" | "off" | "warn";
export type PoolApplication = "rbd" | "cephfs" | "rgw";
export type PoolFields = { size?: number; min_size?: number; pg_num?: number; autoscale?: PoolAutoscale; application?: PoolApplication; crush_rule?: string };
/** `POST /ceph/pools` : seuls ces champs existent côté serveur, tout autre est ignoré. */
export type PoolCreateBody = PoolFields & { name: string; add_storage?: boolean };
/** `PUT /ceph/pools/{name}` : seuls les champs qui changent ; `confirm: true` seulement après avoir montré les raisons du serveur. */
export type PoolPatchBody = PoolFields & { confirm?: boolean };
export type CephWriteResult = { upid: string | null; node: string };
export type PoolWriteResult = { upid: string | null; node: string; pool: string; changes?: PoolFields };
