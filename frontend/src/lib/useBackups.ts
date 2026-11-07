import { useQuery } from "@tanstack/react-query";
import { api, type Guest, type NodeInfo, type StorageInfo } from "./api";
import type { Backup, BackupRow, BackupStore } from "./types/sauvegardes";

export type BackupData = { rows: BackupRow[]; stores: BackupStore[]; failed: { storage: string; node: string; message: string }[] };

/**
 * Toutes les sauvegardes du cluster : pour chaque nœud en ligne, ses stockages qui acceptent des sauvegardes, puis la
 * liste de chacun. Un stockage partagé n'est lu qu'une fois ; un stockage illisible ne fait pas échouer les autres, il
 * est signalé dans `failed`.
 */
async function loadBackups(connId: number, nodes: NodeInfo[]): Promise<BackupData> {
  const base = `/api/connections/${connId}/nodes`;
  const perNode = await Promise.all(nodes.filter((n) => n.status === "online").map(async (n) => {
    const list = await api<StorageInfo[]>(`${base}/${encodeURIComponent(n.node)}/storages?content=backup`).catch(() => [] as StorageInfo[]);
    return list.map((s): BackupStore => ({ storage: s.storage, node: n.node, shared: s.shared, active: s.active, avail: s.avail }));
  }));
  const stores = perNode.flat();

  const seen = new Set<string>();
  const toRead = stores.filter((s) => {
    const key = s.shared ? s.storage : `${s.storage}@${s.node}`;
    if (!s.active || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const failed: BackupData["failed"] = [];
  const lists = await Promise.all(toRead.map(async (s) => {
    try {
      const rows = await api<Backup[]>(`${base}/${encodeURIComponent(s.node)}/storage/${encodeURIComponent(s.storage)}/backups`);
      return rows.map((b): BackupRow => ({ ...b, storage: s.storage, node: s.node, shared: s.shared }));
    } catch (e) {
      failed.push({ storage: s.storage, node: s.node, message: (e as Error).message });
      return [] as BackupRow[];
    }
  }));
  return { rows: lists.flat().sort((a, b) => (b.ctime ?? 0) - (a.ctime ?? 0)), stores, failed };
}

/** Données de la page « Sauvegardes ». Les clés de cache des nœuds et des machines sont celles du tableau de bord. */
export function useBackupData(connId: number | null) {
  const base = `/api/connections/${connId}`;
  const nodes = useQuery({ queryKey: ["cluster", connId, "nodes"], queryFn: () => api<NodeInfo[]>(`${base}/nodes`), enabled: connId !== null, staleTime: 15_000 });
  const guests = useQuery({ queryKey: ["cluster", connId, "guests"], queryFn: () => api<Guest[]>(`${base}/guests`), enabled: connId !== null, staleTime: 15_000 });
  const backups = useQuery({
    queryKey: ["backups", connId], queryFn: () => loadBackups(connId!, nodes.data!),
    enabled: connId !== null && !!nodes.data, staleTime: 15_000,
  });
  return { nodes, guests, backups };
}
