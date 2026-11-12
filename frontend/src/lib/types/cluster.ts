/** Cluster (corosync) en lecture seule (`docs/api/cluster.md`). */
export type ClusterNode = { name: string; nodeid: number | null; online: boolean | null; ip: string | null; local: boolean; votes: number | null; links: { link: number; addr: string }[]; fingerprint: string | null };
export type ClusterConfig = {
  cluster: { name: string | null; quorate: boolean | null; version: number | null; nodes_total: number | null; clustered: boolean };
  nodes: ClusterNode[];
  totem: { cluster_name: string | null; config_version: number | null; ip_version: string | null; link_mode: string | null; secauth: string | null; transport: string | null; links: number[] } | null;
  qdevice: { configured: boolean; info: Record<string, string | null> };
  join: { preferred_node: string | null; address: string | null; fingerprint: string | null; nodes: number } | null;
  errors: Record<string, string>;
};

/** Écriture du cluster (M10-2, `docs/api/cluster-ecriture.md`). */
export type ClusterLocks = { blockers: string[]; cut: string[]; live: string[] };
export type ClusterPreview = { dry_run: true; node?: string | null; params?: Record<string, string | number>; guests?: number[]; ha_resources?: string[]; locks: ClusterLocks; phrase: string | null };
export type ClusterWriteResult = { created?: string; joining?: string | null; removed?: string; node?: string | null; via?: string; upid?: string | null; guests?: number[]; ha_resources?: string[] };
export type ClusterMode = { kind: "create" } | { kind: "join" } | { kind: "remove"; node: string };
