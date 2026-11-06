import { useQuery } from "@tanstack/react-query";
import { api, type Guest } from "../lib/api";
import { bytes } from "../lib/format";
import type { Backup } from "../lib/types/sauvegardes";
import { Notice } from "./ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "–");

/**
 * Onglet « Sauvegardes » de la page Machine : lecture seule. Cherche les sauvegardes de cette machine sur les stockages du
 * nœud où elle se trouve (celles d'un stockage local d'un autre nœud n'apparaissent pas). Lancer, restaurer ou supprimer
 * une sauvegarde : page « Sauvegardes » (ticket M5-6).
 */
export function BackupsTab({ connId, guest }: { connId: number; guest: Guest }) {
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(guest.node)}`;
  const q = useQuery({
    queryKey: ["guest-backups", connId, guest.node, guest.vmid],
    queryFn: async () => {
      const stores = await api<{ storage: string }[]>(`${base}/storages?content=backup`);
      const lists = await Promise.all(stores.map((s) =>
        api<Backup[]>(`${base}/storage/${encodeURIComponent(s.storage)}/backups?vmid=${guest.vmid}`)
          .then((rows) => rows.map((r) => ({ ...r, storage: s.storage })))));
      return lists.flat().sort((a, b) => (b.ctime ?? 0) - (a.ctime ?? 0));
    },
    staleTime: 15_000,
  });

  if (q.isLoading) return <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-xl bg-surface2" />)}</div>;
  if (q.error) return <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>réessayer</button></Notice>;
  const rows = q.data ?? [];
  if (rows.length === 0) return <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Aucune sauvegarde de cette machine sur les stockages du nœud {guest.node}.</div>;
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[34rem] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th scope="col" className="px-4 py-2 font-normal">Date</th><th scope="col" className="px-4 py-2 font-normal">Stockage</th>
              <th scope="col" className="px-4 py-2 font-normal">Format</th><th scope="col" className="px-4 py-2 text-right font-normal">Taille</th>
              <th scope="col" className="px-4 py-2 font-normal">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.volid} className="border-b border-line/60 last:border-0">
                <td className="whitespace-nowrap px-4 py-2" title={b.name}>{when(b.date)}</td>
                <td className="px-4 py-2 text-muted">{b.storage}</td>
                <td className="px-4 py-2 text-muted">{b.format ?? "–"}</td>
                <td className="px-4 py-2 text-right tabular-nums">{bytes(b.size)}</td>
                <td className="max-w-xs truncate px-4 py-2 text-muted">{b.protected ? "Protégée" : ""}{b.protected && b.notes ? " · " : ""}{b.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">Sauvegardes des stockages du nœud {guest.node} uniquement. Pour lancer, restaurer ou supprimer une sauvegarde, la page « Sauvegardes » arrive avec le jalon M5.</p>
    </div>
  );
}
