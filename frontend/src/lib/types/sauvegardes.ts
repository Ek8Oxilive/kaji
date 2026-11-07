/** Une sauvegarde vzdump, telle que renvoyée par `GET /nodes/{node}/storage/{storage}/backups` (docs/api/sauvegardes.md). */
export type Backup = {
  volid: string; name: string; vmid: number | null; type: "qemu" | "lxc" | null; format: string | null;
  size: number | null; ctime: number | null; date: string | null; notes: string | null;
  protected: boolean; deletable: boolean;
};

// ---- page « Sauvegardes » (M5-6) : formes des routes de docs/api/sauvegardes.md ----

/** Une sauvegarde avec l'endroit où elle se trouve (un stockage partagé n'est lu qu'une fois, depuis un nœud). */
export type BackupRow = Backup & { storage: string; node: string; shared: boolean };

/** Un stockage pouvant recevoir des sauvegardes, vu depuis un nœud (`GET /nodes/{node}/storages?content=backup`). */
export type BackupStore = { storage: string; node: string; shared: boolean; active: boolean; avail: number | null };

export type BackupMode = "snapshot" | "suspend" | "stop";
export type BackupCompress = "zstd" | "gzip" | "lzo" | "none";

/** `POST /nodes/{node}/backups`. `confirm: true` est exigé par le serveur quand `mode` vaut `stop`. */
export type BackupCreateBody = { vmid: number; storage: string; mode: BackupMode; compress: BackupCompress; notes?: string; confirm?: boolean };
export type BackupCreateResult = { upid: string; node: string; vmid: number; storage: string };

/** `POST /nodes/{node}/restore` : crée une NOUVELLE machine, ne remplace jamais une machine existante. */
export type RestoreBody = { volid: string; vmid?: number; storage: string; pool?: string; unique: boolean };
export type RestoreResult = { upid: string; node: string; vmid: number; type: "qemu" | "lxc"; archive: string };

/** `DELETE …/backups/{volume}?confirm=true&name=…` */
export type BackupDeleteResult = { upid: string | null; deleted: string };
