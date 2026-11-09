/** Types du SDN (`docs/api/sdn.md`). */
export type SdnState = "new" | "changed" | "deleted" | null;
export type SdnZone = { zone: string; type: string | null; state: SdnState; bridge: string | null; tag: number | null; nodes: string[]; peers: string[]; controller: string | null; mtu: number | null };
export type SdnVnet = { vnet: string; zone: string | null; alias: string | null; tag: number | null; vlanaware: boolean | null; state: SdnState };
export type SdnSubnet = { subnet: string; cidr: string | null; gateway: string | null; snat: boolean | null; state: SdnState };
