/** Actions groupées d'un nœud et Wake-on-LAN (`docs/api/actions-groupees.md`). */
export type BulkAction = "startall" | "stopall" | "migrateall";
export type BulkGuest = { vmid: number; name: string | null; type: string | null; status: string | null };
export type BulkPlan = {
  action: BulkAction; node: string; known: boolean; online: boolean; dry_run?: true;
  apply: BulkGuest[]; skipped: (BulkGuest & { reason: string })[]; unknown: number[]; protected: number[]; running: number[];
  target: string | null; target_ok: boolean | null; blocked: string | null; needs_accept_running: boolean;
};
export type BulkResult = { node: string; action: BulkAction; upid: string | null; vmids: number[] };
export const BULK_LABEL: Record<BulkAction, string> = { startall: "Démarrer", stopall: "Arrêter", migrateall: "Migrer" };
