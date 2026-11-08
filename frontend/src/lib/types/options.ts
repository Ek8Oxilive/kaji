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

/** Options d'un conteneur LXC (lot #145), formes de `docs/api/options.md`. */
export type LxcOptionKey = "onboot" | "startup" | "protection" | "features" | "ostype" | "console" | "cmode" | "tty" | "timezone" | "description";
export type LxcMount = "nfs" | "cifs";
export type LxcOptions = {
  onboot: boolean | null; protection: boolean | null; console: boolean | null;
  startup: { order: number | null; up: number | null; down: number | null } | null;
  features: { nesting: boolean | null; fuse: boolean | null; keyctl: boolean | null; mount: LxcMount[] } | null;
  ostype: string | null; cmode: string | null; tty: number | null; timezone: string | null; description: string | null;
};
export type LxcOptionsResponse = { type: "lxc"; options: LxcOptions; unprivileged: boolean | null; pending: VmOptionsPending[]; reboot_required: boolean };
export type LxcOptionsPatch = {
  onboot?: boolean; protection?: boolean; console?: boolean; startup?: { order?: number; up?: number; down?: number };
  features?: { nesting?: boolean; fuse?: boolean; keyctl?: boolean; mount?: LxcMount[] }; ostype?: string; cmode?: string; tty?: number; timezone?: string;
  description?: string; clear?: LxcOptionKey[]; confirm?: boolean;
};
