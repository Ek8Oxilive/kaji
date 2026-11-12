import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest } from "../lib/api";
import { duration, taskLabel } from "../lib/taskLabels";
import type { TaskList, TaskRow } from "../lib/types/taches";
import { Badge, TaskDrawer, when } from "./TaskDrawer";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
type Filter = "all" | "error";
/** Chaque ouverture d'une console crée une tâche : elles noient les vraies actions (près de la moitié de l'historique constaté). */
const CONSOLE = new Set(["vncproxy", "termproxy", "spiceproxy", "vncshell", "spiceshell"]);

/** Historique des tâches d'UNE machine (tous les nœuds : elle a pu migrer). Lecture seule ; le journal d'une tâche s'ouvre dans un tiroir. */
export function GuestTasksTab({ connId, guest }: { connId: number; guest: Guest }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [hideConsole, setHideConsole] = useState(true);
  const [open, setOpen] = useState<TaskRow | null>(null);
  const query = new URLSearchParams({ vmid: String(guest.vmid), limit: "250" });
  if (filter === "error") query.set("errors", "true");
  const tasks = useQuery({
    queryKey: ["tasks", connId, "guest", guest.vmid, filter], queryFn: () => api<TaskList>(`/api/connections/${connId}/tasks?${query}`),
    refetchInterval: (qr) => (qr.state.data?.tasks.some((t) => t.state === "running") ? 3000 : 15_000),
  });
  // Proxmox appelle « erreur » tout ce qui n'est pas « OK » : on écarte les avertissements du filtre « Échecs ».
  const all = tasks.data?.tasks ?? [];
  const hidden = hideConsole ? all.filter((t) => t.type && CONSOLE.has(t.type)).length : 0;
  const rows = all.filter((t) => (filter !== "error" || t.state === "error") && !(hideConsole && t.type && CONSOLE.has(t.type)));
  return (
    <section className="space-y-3" aria-label={tr("Tâches de la machine")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{tr("Tâches")}{" "}<span className="text-sm font-normal text-muted">({rows.length})</span></h3>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted"><input type="checkbox" checked={hideConsole} onChange={(e) => setHideConsole(e.target.checked)} />{tr("Masquer les consoles{p}", { p: hidden > 0 && ` (${hidden})` })}</label>
          <select className="field !w-auto !py-1.5 text-sm" aria-label={tr("État")} value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
            <option value="all">{tr("Toutes")}</option><option value="error">{tr("Échecs")}</option>
          </select>
          <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => tasks.refetch()} disabled={tasks.isFetching}><span className={tasks.isFetching ? "inline-block animate-spin" : ""}>↻</span>{" "}{tr("Actualiser")}</Button>
        </div>
      </div>
      {tasks.error && <Notice kind="error">{(tasks.error as Error).message}</Notice>}
      {tasks.data?.failed.map((f) => <Notice key={f.node} kind="error">{tr("Le nœud « {node} » n'a pas répondu : ses tâches ne sont pas affichées.", { node: f.node })}</Notice>)}
      {tasks.isLoading ? <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="panel h-11 animate-pulse" />)}</div>
        : rows.length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{filter === "error" ? tr("Aucun échec.") : tr("Aucune tâche enregistrée pour cette machine.")}</div>
        : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[34rem] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                <th scope="col" className="px-4 py-2 font-normal">{tr("État")}</th><th scope="col" className="px-4 py-2 font-normal">{tr("Tâche")}</th><th scope="col" className="px-4 py-2 font-normal">{tr("Début")}</th>
                <th scope="col" className="px-4 py-2 text-right font-normal">{tr("Durée")}</th></tr></thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.upid} className="cursor-pointer border-b border-line/60 transition last:border-0 hover:bg-surface2" onClick={() => setOpen(t)}>
                    <td className="px-4 py-2"><Badge s={t.state} /></td>
                    <td className="px-4 py-2">
                      <button type="button" className="text-left font-medium hover:underline focus-visible:underline" onClick={(e) => { e.stopPropagation(); setOpen(t); }}>{taskLabel(t.type)}</button>
                      <span className="block text-xs text-muted">{t.node ?? "–"} · {t.user ?? "–"}{t.token ? `!${t.token}` : ""}{t.by_kaji && <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[0.7rem]">{tr("Kaji")}</span>}</span>
                      {t.status_text && <span className="block max-w-md truncate text-xs text-danger" title={t.status_text}>{t.status_text}</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-muted">{when(t.start)}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums text-muted">{t.state === "running" ? tr("en cours") : duration(t.duration)}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>)}
      {open && <TaskDrawer connId={connId} task={open} label={`${taskLabel(open.type)} · ${guest.name ?? `#${guest.vmid}`}`} onClose={() => setOpen(null)} />}
    </section>
  );
}
