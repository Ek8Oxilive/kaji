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

// ---- jobs planifiés (M5-6, seconde partie) : formes des routes de docs/api/sauvegardes-planifiees.md ----

export type JobSelection = { type: "all" } | { type: "pool"; pool: string } | { type: "vmids"; vmids: number[] } | { type: null };
export type JobRetention = {
  keep_all?: true; keep_last?: number; keep_hourly?: number; keep_daily?: number; keep_weekly?: number; keep_monthly?: number; keep_yearly?: number;
};

/** `GET /backup-jobs` : un job tel que Kaji le met en forme. `retention: null` = celle du stockage s'applique. */
export type Job = {
  id: string; enabled: boolean; schedule: string | null; storage: string | null; mode: BackupMode; compress: BackupCompress | null;
  node: string | null; selection: JobSelection; retention: JobRetention | null; notes: string | null; next_run: string | null; repeat_missed: boolean;
};

export type JobSelectionBody = { type: "all" } | { type: "pool"; pool: string } | { type: "vmids"; vmids: number[] };
/** `POST /backup-jobs`. `confirm: true` n'est envoyé qu'après avoir montré les raisons que le serveur a données. */
export type JobCreateBody = {
  schedule: string; storage: string; selection: JobSelectionBody; mode: BackupMode; compress: BackupCompress; enabled: boolean;
  retention?: JobRetention; node?: string; notes?: string; confirm?: boolean;
};
/** `PUT /backup-jobs/{id}` : seuls les champs fournis changent ; `node: null` et `notes: null` les retirent. */
export type JobPatchBody = Partial<Omit<JobCreateBody, "node" | "notes" | "confirm">> & { node?: string | null; notes?: string | null; confirm?: boolean };
