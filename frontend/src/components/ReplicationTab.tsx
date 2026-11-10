import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type { Guest } from "../lib/api";
import type { ReplJob, ReplMode, ReplStatus } from "../lib/types/ha";
import { ReplDialog } from "./ReplDialog";
import { Button, Notice } from "./ui";

const when = (t: number | null | undefined) => (t ? new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }) : "—");

/**
 * Onglet « Réplication » d'une machine (M8) : les jobs de CETTE machine, avec les mêmes fenêtres (aperçu, verrous, nom retapé) que la page « HA ».
 * Aucune route nouvelle : on filtre `GET /replication` sur l'identifiant de la machine.
 */
export function ReplicationTab({ connId, guest }: { connId: number; guest: Guest }) {
  const [mode, setMode] = useState<ReplMode | null>(null);
  const jobs = useQuery({ queryKey: ["ha", connId, "jobs"], queryFn: () => api<ReplJob[]>(`/api/connections/${connId}/replication`), staleTime: 10_000 });
  const mine = (jobs.data ?? []).filter((j) => j.guest === guest.vmid);
  const sources = [...new Set(mine.map((j) => j.source).filter((s): s is string => !!s))];
  const stat = useQuery({
    queryKey: ["ha", connId, "rstatus", sources.join(",")], enabled: sources.length > 0,
    queryFn: async () => (await Promise.all(sources.map((n) => api<ReplStatus[]>(`/api/connections/${connId}/nodes/${encodeURIComponent(n)}/replication`).catch(() => [] as ReplStatus[])))).flat(),
  });
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">Copie périodique des disques de la machine vers un autre nœud. Elle exige du stockage ZFS sur les deux nœuds : sans lui, « Nouveau job… » indique ce qui bloque, sans rien écrire.</p>
        <Button onClick={() => setMode({ kind: "new" })} className="shrink-0">Nouveau job…</Button>
      </div>
      {jobs.error ? <Notice kind="error">{(jobs.error as Error).message}</Notice>
        : jobs.isLoading ? <p className="text-sm text-muted">Chargement…</p>
        : mine.length === 0 ? <p className="rounded-xl border border-line p-4 text-sm text-muted">Aucun job de réplication pour cette machine.</p>
        : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted"><tr>{["Job", "Source → cible", "Planification", "Dernière synchro", "Prochaine", "Échecs", ""].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{mine.map((j) => {
                const s = (stat.data ?? []).find((x) => x.id === j.id);
                return (
                  <tr key={j.id} className={`border-t border-line/60 ${j.disable ? "opacity-50" : ""}`}>
                    <td className="px-4 py-2 font-mono">{j.id}</td>
                    <td className="px-4 py-2 text-muted">{j.source ?? "?"} → {j.target ?? "?"}</td>
                    <td className="px-4 py-2 text-muted">{j.schedule ?? "—"}{j.disable ? " (désactivé)" : ""}</td>
                    <td className="px-4 py-2 text-muted">{when(s?.last_sync)}</td>
                    <td className="px-4 py-2 text-muted">{when(s?.next_sync)}</td>
                    <td className={`px-4 py-2 ${s?.fail_count ? "text-danger" : "text-muted"}`} title={s?.error ?? undefined}>{s?.fail_count ?? 0}</td>
                    <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs">
                      {j.remove_job ? <span className="text-muted">suppression en cours</span> : <>
                        <button className="underline" onClick={() => setMode({ kind: "edit", job: j })}>Modifier</button>
                        <button className="underline" onClick={() => setMode({ kind: "now", job: j })}>Lancer maintenant</button>
                        <button className="text-danger underline" onClick={() => setMode({ kind: "delete", job: j })}>Supprimer</button>
                      </>}
                    </td>
                  </tr>);
              })}</tbody>
            </table>
          </div>)}
      {mode && <ReplDialog connId={connId} mode={mode} presetGuest={guest.vmid ?? undefined} onClose={() => setMode(null)} />}
    </div>
  );
}
