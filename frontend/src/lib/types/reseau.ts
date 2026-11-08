/** Types de la page « Réseau » : forme des réponses de `docs/api/reseau.md` (lecture seule). */

export type NetIface = {
  iface: string; type: string; active: boolean | null; autostart: boolean | null; method: string | null; method6: string | null;
  address: string | null; netmask: string | null; cidr: string | null; gateway: string | null; address6: string | null; cidr6: string | null; gateway6: string | null;
  mtu: number | null; bridge_ports: string[]; bridge_vlan_aware: boolean | null; bridge_vids: string | null; slaves: string[]; bond_mode: string | null;
  vlan_id: number | null; vlan_raw_device: string | null; comments: string | null; has_gateway: boolean;
};
export type NetworkInfo = { interfaces: NetIface[]; changes: string | null; pending: boolean };

export type FwRule = {
  pos: number; type: string | null; action: string | null; enable: boolean | null; source: string | null; dest: string | null; proto: string | null;
  sport: string | null; dport: string | null; iface: string | null; macro: string | null; log: string | null; icmp_type: string | null; ipversion: number | null; comment: string | null;
};
export type FwPart<T> = T | { error: string };
export type FwOptions = Record<string, string | number | boolean | null> & { digest?: string | null };
export type FwCluster = {
  options: FwPart<FwOptions>; rules: FwPart<FwRule[]>; aliases: FwPart<{ name: string; cidr: string | null; comment: string | null }[]>;
  ipsets: FwPart<{ name: string; comment: string | null }[]>; groups: FwPart<{ name: string; comment: string | null }[]>;
};
export type FwNode = { options: FwPart<FwOptions>; rules: FwPart<FwRule[]> };
export const isErr = <T,>(p: FwPart<T>): p is { error: string } => !!p && typeof p === "object" && !Array.isArray(p) && "error" in (p as object);
