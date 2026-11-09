/** Alimentation avancée d'une VM et conversion en modèle (`docs/api/alimentation-vm.md`). */
export type PowerOp = "reset" | "suspend" | "hibernate" | "resume" | "template";

/** `GET …/qemu/{vmid}/power` : état relu chez Proxmox (la liste des machines ne dit pas « en pause »). */
export type PowerState = { status: string | null; qmpstatus: string | null; paused: boolean };
