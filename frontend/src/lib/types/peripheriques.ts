/** Périphériques d'une VM (`docs/api/peripheriques.md`) : carte d'affichage, ports série (socket), audio, RNG, watchdog. */
export const VGA_TYPES = ["std", "vmware", "virtio", "virtio-gl", "qxl", "qxl2", "qxl3", "qxl4", "cirrus", "serial0", "serial1", "serial2", "serial3", "none"] as const;
export type VgaType = (typeof VGA_TYPES)[number];
export const AUDIO_DEVICES = ["ich9-intel-hda", "intel-hda", "AC97"] as const;
export type AudioDevice = (typeof AUDIO_DEVICES)[number];
export const WATCHDOG_MODELS = ["i6300esb", "ib700"] as const;
export const WATCHDOG_ACTIONS = ["reset", "shutdown", "poweroff", "pause", "debug", "none"] as const;
export type SerialKey = "serial0" | "serial1" | "serial2" | "serial3";
export const SERIALS: SerialKey[] = ["serial0", "serial1", "serial2", "serial3"];
export const BIOS = ["seabios", "ovmf"] as const;
export const EFI_TYPES = ["4m", "2m"] as const;
export const TPM_VERSIONS = ["v2.0", "v1.2"] as const;
export type DeviceKey = "vga" | "audio0" | "rng0" | "watchdog" | "bios" | "efidisk0" | "tpmstate0" | SerialKey;

/** `socket` ; `device` = périphérique de l'hôte posé par root (lecture seule, chemin jamais renvoyé). */
export type SerialState = "socket" | "device" | null;
export type DevicesState = {
  vga: { type: string | null; memory: number | null; clipboard: "vnc" | null } | null;
  audio: { device: string | null; driver: string | null } | null;
  rng: { source: string | null; max_bytes: number | null; period: number | null } | null;
  watchdog: { model: string | null; action: string | null } | null;
  bios: string | null;
  efidisk: { storage: string | null; efitype: string | null; pre_enrolled_keys: boolean } | null;
  tpm: { storage: string | null; version: string | null } | null;
} & Record<SerialKey, SerialState>;
export type DevicesResponse = { type: "qemu"; devices: DevicesState; pending: { key: string; value: unknown; pending: unknown; delete: boolean }[]; reboot_required: boolean };

export type DevicesPatch = {
  vga?: { type?: string; memory?: number; clipboard?: "vnc" };
  audio?: { device: string; driver?: string };
  rng?: { max_bytes?: number; period?: number };
  watchdog?: { model: string; action?: string };
  bios?: string;
  efidisk?: { storage: string; efitype?: string; pre_enrolled_keys?: boolean };
  tpm?: { storage: string; version?: string };
  clear?: DeviceKey[];
} & Partial<Record<SerialKey, "socket">>;
export type DevicesResult = { changed: string[]; removed: string[] };
