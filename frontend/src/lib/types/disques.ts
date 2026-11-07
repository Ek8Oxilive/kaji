/** Disques d'un nœud : forme des réponses de `docs/api/disques.md`. */
import type { Section } from "./systeme";
export type Partition = { device: string; size: number | null; used: string | null };
export type Disk = { device: string; size: number | null; used: string | null; gpt: boolean; osd: boolean; model: string | null; type: string | null; health: string | null; wearout: number | null; partitions: Partition[] };
export type NodeDisks = {
  disks: Section<Disk[]>;
  lvm: Section<{ name: string; size: number | null; free: number | null; volumes: number | null; devices: string[] }[]>;
  lvmthin: Section<{ name: string; vg: string | null; size: number | null; used: number | null; metadata_size: number | null; metadata_used: number | null }[]>;
  directory: Section<{ path: string; device: string | null; type: string | null; options: string | null }[]>;
  zfs: Section<{ name: string; size: number | null; alloc: number | null; free: number | null; health: string | null; fragmentation: number | null }[]>;
};
export type Smart = { health: string | null; type: "text" | "ata"; wearout: number | null; text: string | null;
  attributes: { id: number | null; name: string; value: number | null; worst: number | null; threshold: number | null; raw: string | null; failing: boolean }[] };
