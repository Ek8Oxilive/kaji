/** Pools de ressources (`docs/api/pools.md`) : lire, créer, modifier les membres, supprimer un pool vide et sans droit. */
export type PoolMember =
  | { type: "qemu" | "lxc"; vmid: number; name: string | null; node: string | null; status: string | null }
  | { type: "storage"; storage: string; node: string | null };
export type Pool = { poolid: string; comment: string | null; members: PoolMember[]; vms: number[]; storages: string[] };

export type PoolUpdateBody = {
  comment?: string; add_vms?: number[]; remove_vms?: number[]; add_storage?: string[]; remove_storage?: string[];
  allow_move?: boolean; confirm?: boolean; dry_run?: boolean;
};
export type PoolUpdateResult = { changed: true; pool: Pool | null } | { dry_run: true; calls: Record<string, unknown>[]; needs_confirm: string[] };
