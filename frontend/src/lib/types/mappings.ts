import { tr } from "../i18n";
export type MType = "pci" | "usb" | "dir";
export const MTYPES: MType[] = ["pci", "usb", "dir"];
export const MTYPE_LABEL: Record<MType, string> = { pci: "PCI", usb: "USB", get dir() { return tr("Répertoires"); } };

/** Entrée d'une correspondance (une par nœud et par périphérique). Seules les propriétés du type sont utilisées. */
export type MapEntry = { node: string; path: string | null; id: string | null; iommugroup: number | null; subsystem_id: string | null; description: string | null };
export type Mapping = {
  id: string; type: MType; description: string | null; map: MapEntry[]; checks: string[]; error: string | null;
  mdev: boolean | null; live_migration_capable: boolean | null; digest: string | null;
};
export type MappingPreview = { dry_run: true; params?: Record<string, unknown>; remove?: string[]; retype?: string; used_by?: string[] };
export type PciDevice = { id: string; iommugroup: number | null; map_id: string; subsystem_id: string | null; vendor_name: string | null; device_name: string | null; mdev: boolean | null; class: string | null };
export type UsbDevice = { map_id: string; map_path: string | null; busnum: number | null; port: number | null; product: string | null; manufacturer: string | null; class: number | null; speed: string | null };
export const emptyEntry = (node: string): MapEntry => ({ node, path: null, id: null, iommugroup: null, subsystem_id: null, description: null });
