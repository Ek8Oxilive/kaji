import type { HwNet } from "../api";

/** Options fines d'une carte réseau (lot #377, `docs/api/options-materiel.md`) : en plus des champs de `HwNet`. */
export type NetX = HwNet & { rate?: string | null; mtu?: number | null; queues?: number | null; link_down?: boolean; trunks?: string[] };

/** Corps de `PATCH …/disks/{key}/options` : seuls les champs modifiés sont envoyés ; `clear` remet une option à son défaut. */
export type DiskOptionsBody = {
  cache?: string; discard?: string; aio?: string;
  iothread?: boolean; ssd?: boolean; backup?: boolean; ro?: boolean; replicate?: boolean; detect_zeroes?: boolean;
  mbps_rd?: number; mbps_wr?: number; iops_rd?: number; iops_wr?: number;
  clear?: string[]; confirm?: boolean;
};
export type NetOptionsBody = { rate?: number; mtu?: number; queues?: number; link_down?: boolean; trunks?: string[]; clear?: string[]; confirm?: boolean };
export type CpuOptionsBody = { cpuunits?: number; cpulimit?: number; affinity?: string; hugepages?: string; clear?: string[]; confirm?: boolean };
