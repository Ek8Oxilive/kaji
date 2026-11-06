/** Une sauvegarde vzdump, telle que renvoyée par `GET /nodes/{node}/storage/{storage}/backups` (docs/api/sauvegardes.md). */
export type Backup = {
  volid: string; name: string; vmid: number | null; type: "qemu" | "lxc" | null; format: string | null;
  size: number | null; ctime: number | null; date: string | null; notes: string | null;
  protected: boolean; deletable: boolean;
};
