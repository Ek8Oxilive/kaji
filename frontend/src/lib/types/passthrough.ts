import { tr } from "../i18n";
export type PType = "pci" | "usb" | "dir";
export const PTYPES: PType[] = ["pci", "usb", "dir"];
export const PTYPE_LABEL: Record<PType, string> = { get pci() { return tr("Périphériques PCI"); }, get usb() { return tr("Périphériques USB"); }, get dir() { return tr("Répertoires partagés (virtiofs)"); } };
export const PTYPE_ONE: Record<PType, string> = { pci: "PCI", usb: "USB", get dir() { return tr("répertoire"); } };

/** Périphérique d'une VM lu dans la configuration. `raw` : hôte brut (réservé à root@pam), jamais modifiable depuis Kaji. */
export type PtDevice = {
  key: string; type: PType; mapping: string | null; raw: boolean; host: string | null; other: string[];
  pcie?: boolean | null; rombar?: boolean | null; x_vga?: boolean | null; mdev?: string | null; usb3?: boolean | null;
  cache?: string | null; direct_io?: boolean | null; expose_acl?: boolean | null; expose_xattr?: boolean | null;
};
export type PtState = { pci: PtDevice[]; usb: PtDevice[]; dir: PtDevice[]; pending: string[]; machine: string | null; running: boolean | null };
export type PtPreview = { dry_run: true; key?: string; value?: string; remove?: string; mapping?: string; warnings?: string[]; running: boolean | null };
export type PtMapping = { id: string; description: string | null; map: { node: string }[]; mdev: boolean | null };
export type PtForm = { mapping: string; pcie: Tri; rombar: Tri; x_vga: Tri; mdev: string; usb3: Tri; cache: string; direct_io: Tri; expose_acl: Tri; expose_xattr: Tri };
export type Tri = "" | "yes" | "no";
export const triOf = (v: boolean | null | undefined): Tri => (v === true ? "yes" : v === false ? "no" : "");
export const triVal = (t: Tri) => (t === "yes" ? true : t === "no" ? false : undefined);
