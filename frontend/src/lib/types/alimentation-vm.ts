/** Alimentation avancée d'une VM et conversion en modèle (`docs/api/alimentation-vm.md`). */
export type PowerOp = "reset" | "suspend" | "hibernate" | "resume" | "template";

/** `GET …/qemu/{vmid}/power` : état relu chez Proxmox. Une VM suspendue : `status: "running"`, `qmpstatus: "paused"`, alors que la liste des machines dit `paused`. */
export type PowerState = { status: string | null; qmpstatus: string | null; paused: boolean };
