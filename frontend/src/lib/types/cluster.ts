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
