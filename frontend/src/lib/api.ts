import { tr } from "./i18n";
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function messageOf(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return tr(d);               // message du serveur : traduit s'il figure dans en-server.json
  if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? tr("Valeur invalide")).join(" · ");
  return tr("Erreur {status}", { status });
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? "GET",
    headers: init.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    credentials: "same-origin",
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, messageOf(body, res.status));
  return body as T;
}

export type AuthStatus = { setup_required: boolean; authenticated: boolean; setup_token_required: boolean };
export type Connection = {
  id: number; name: string; host: string; port: number; user: string; token_id: string; verify_ssl: boolean; tls_pinned: boolean; tls_fingerprint: string | null;
};
export type ProbeResult = { ok: boolean; version?: string; release?: string; error?: string };

export type ClusterStatus = { name: string | null; quorate: boolean | null; nodes: { name: string; online: boolean; ip: string | null }[] };
export type NodeInfo = { node: string; status: string | null; cpu: number | null; maxcpu: number | null; mem: number | null; maxmem: number | null; disk: number | null; maxdisk: number | null; uptime: number | null };
export type Guest = {
  vmid: number; name: string | null; type: "qemu" | "lxc"; node: string; status: string | null; template: boolean;
  cpu: number; maxcpu: number | null; mem: number; maxmem: number | null; uptime: number; tags?: string[]; pool?: string | null;
};
export type GuestAction = "start" | "shutdown" | "reboot" | "stop";
export type TaskStatus = { status: string | null; exitstatus: string | null; type: string | null; ok: boolean; warnings?: boolean };

export type HwDisk = {
  key: string; kind: "disk" | "cdrom"; storage: string | null; volume: string | null; empty: boolean;
  size: string | null; size_bytes: number | null; options: Record<string, string>; cloudinit?: boolean;
};
export type HwNet = {
  key: string; model: string | null; mac: string | null; bridge: string | null; tag: number | null;
  firewall: boolean; name: string | null; ip: string | null;
};
export type HwPending = { key: string; value: string | number | null; pending: string | number | null; delete: boolean };
export type HwConfig = {
  type: "qemu" | "lxc"; settings: Record<string, string | number>; disks: HwDisk[]; nets: HwNet[];
  pending: HwPending[]; reboot_required: boolean; boot_order: string[]; unused: { key: string; volume: string; storage: string | null }[];
};
export type HwUpdate = {
  memory?: number; balloon?: number; cores?: number; sockets?: number; cpu?: string; swap?: number;
  nets?: Record<string, { bridge?: string; tag?: number; clear_tag?: boolean; firewall?: boolean }>;
  cdroms?: Record<string, { iso: string | null }>;
  boot?: string[];
};

export type Bridge = { name: string; kind: "bridge" | "vnet"; zone: string | null; detail: string | null; vlan_aware: boolean };
export type Iso = { volid: string; storage: string; name: string; size: number | null };

export type Snapshot = { name: string; description: string; time: number | null; vmstate: boolean; parent: string | null };
export type SnapshotList = { snapshots: Snapshot[]; current_parent: string | null };

export type Pool = { poolid: string; comment: string | null };
export type StorageInfo = { storage: string; type: string | null; avail: number | null; total: number | null; shared: boolean; active: boolean };
export type VmCreateBody = {
  name: string; vmid?: number; memory: number; cores: number; sockets: number; cpu: string; ostype: string;
  disk?: { storage: string; size_gb: number }; net?: { bridge: string; model: string; tag?: number; firewall: boolean };
  iso?: string; pool?: string; agent: boolean; start: boolean; description: string;
};

export type MigratePreflight = {
  preflight: boolean; running: boolean | null; allowed_nodes: string[]; not_allowed: { node: string; reasons: string[] }[];
  local_disks: { volid: string | null; size: number | null }[]; local_resources: string[];
};

export type LxcTemplates = {
  storages: string[]; local: { volid: string; storage: string; name: string; size: number | null }[];
  downloadable: { template: string; os: string | null; version: string | null; section: string | null; architecture: string | null; description: string | null }[] | null;
  /** Architecture du nœud en noms du catalogue (`amd64`, `arm64`…) ; `null` si inconnue. */
  node_architecture?: string | null;
};
export type LxcCreateBody = {
  hostname: string; vmid?: number; template: string; memory: number; swap: number; cores: number;
  disk: { storage: string; size_gb: number };
  net?: { bridge: string; tag?: number; firewall: boolean; ip?: string; gateway?: string };
  password?: string; ssh_public_keys?: string; unprivileged: boolean; nesting: boolean; pool?: string; start: boolean; description: string;
};

export type CiIpConf = { mode: "dhcp" | "static" | "none"; ip: string | null; gateway: string | null };
export type CloudInit = {
  has_drive: boolean; drive: string | null; user: string | null; password_set: boolean; ssh_keys: string | null;
  ipconfig: Record<string, CiIpConf>; nameserver: string | null; searchdomain: string | null; upgrade: boolean | null;
};
