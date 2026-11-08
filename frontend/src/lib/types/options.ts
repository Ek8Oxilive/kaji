/** Options d'une VM (onglet « Options »), formes de `docs/api/options.md`. Jamais vues sur un vrai cluster. */
export type VmOptionKey = "onboot" | "startup" | "ostype" | "agent" | "tablet" | "protection" | "hotplug" | "numa" | "localtime" | "acpi" | "kvm" | "freeze" | "description";
export type VmBoolKey = "onboot" | "tablet" | "protection" | "numa" | "localtime" | "acpi" | "kvm" | "freeze";
export type HotplugFeature = "network" | "disk" | "cpu" | "memory" | "usb" | "cloudinit";

export type VmOptions = Record<VmBoolKey, boolean | null> & {
  startup: { order: number | null; up: number | null; down: number | null } | null;
  ostype: string | null;
  agent: { enabled: boolean | null; fstrim_cloned_disks: boolean | null } | null;
  hotplug: HotplugFeature[] | null;
  description: string | null;
};
export type VmOptionsPending = { key: string; value: unknown; pending: unknown; delete: boolean };
export type VmOptionsResponse = { type: "qemu"; options: VmOptions; pending: VmOptionsPending[]; reboot_required: boolean };
export type VmOptionsPatch = Partial<{ [K in VmBoolKey]: boolean }> & {
  startup?: { order?: number; up?: number; down?: number }; ostype?: string; agent?: { enabled?: boolean; fstrim_cloned_disks?: boolean };
  hotplug?: HotplugFeature[]; description?: string; clear?: VmOptionKey[]; confirm?: boolean;
};
export type VmOptionsResult = { changed: string[]; removed: string[] };
