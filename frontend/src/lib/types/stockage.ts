/** Types de la page « Stockage » : forme des réponses de `docs/api/stockage.md`. */

export type StorageContent = "images" | "rootdir" | "iso" | "vztmpl" | "backup" | "snippets";

/** `GET /api/connections/{id}/storages` : une entrée par couple (stockage, nœud). */
export type StorageRow = {
  storage: string;
  node: string | null;
  type: string | null;
  status: string | null;
  shared: boolean;
  contents: StorageContent[];
  used: number | null;
  total: number | null;
  free: number | null;
  active: boolean;
  nodes: string[];
};

/** `GET /api/connections/{id}/nodes/{node}/storage/{storage}/content` */
export type StorageVolume = {
  volid: string;
  name: string;
  content: string | null;
  format: string | null;
  size: number | null;
  ctime: number | null;
  date: string | null;
  vmid: number | null;
  notes: string | null;
  protected: boolean;
};
