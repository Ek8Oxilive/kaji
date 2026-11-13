import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ClusterLog } from "../components/ClusterLog";
import { Badge, TaskDrawer, when } from "../components/TaskDrawer";
import { Button, Notice } from "../components/ui";
import { api, type Guest, type NodeInfo } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { duration, taskLabel } from "../lib/taskLabels";
import type { TaskList, TaskRow } from "../lib/types/taches";

import { tr } from "../lib/i18n";
type Filter = "all" | "running" | "error" | "warning";

export function Taches({ onGoConnections }: { onGoConnections: () => void }) {
  const { conns, active, id } = useActiveConnection();
  const [filter, setFilter] = useState<Filter>("all"), [node, setNode] = useState("all"), [limit, setLimit] = useState(100), [q, setQ] = useState("");
  const [open, setOpen] = useState<TaskRow | null>(null);

  const query = new URLSearchParams({ limit: String(limit) });
  if (filter === "error") query.set("errors", "true");
  if (filter === "running") query.set("running", "true");
  if (node !== "all") query.set("node", node);
  const tasks = useQuery({
    queryKey: ["tasks", id, filter === "error" || filter === "running" ? filter : "all", node, limit], enabled: id !== null,
    queryFn: () => api<TaskList>(`/api/connections/${id}/tasks?${query}`),
    // Une tâche est en cours : on suit de près ; sinon, un rafraîchissement tranquille.
    refetchInterval: (qr) => (qr.state.data?.tasks.some((t) => t.state === "running") ? 3000 : 15_000),
  });
  const nodes = useQuery({ queryKey: ["cluster", id, "nodes"], enabled: id !== null, staleTime: 30_000, queryFn: () => api<NodeInfo[]>(`/api/connections/${id}/nodes`) });
  const guests = useQuery({ queryKey: ["cluster", id, "guests"], enabled: id !== null, staleTime: 30_000, queryFn: () => api<Guest[]>(`/api/connections/${id}/guests`) });
  const names = useMemo(() => new Map((guests.data ?? []).map((g) => [String(g.vmid), g.name])), [guests.data]);
  const target = (t: TaskRow) => (t.id ? (names.get(t.id) ? `${names.get(t.id)} · #${t.id}` : t.id) : "");

  // Proxmox appelle « erreur » tout ce qui n'est pas « OK », avertissements compris : on affine ici.
  const rows = (tasks.data?.tasks ?? []).filter((t) => (filter !== "warning" || t.state === "warning") && (filter !== "error" || t.state === "error")
    && (!q || `${taskLabel(t.type)} ${t.type ?? ""} ${target(t)} ${t.user ?? ""} ${t.node ?? ""} ${t.status_text ?? ""}`.toLowerCase().includes(q.toLowerCase())));
  const sel = "field !w-auto !py-1.5 text-sm";

  if (conns.isLoading) return <div className="mx-auto max-w-6xl space-y-3">{[0, 1, 2].map((i) => <div key={i} className="panel h-12 animate-pulse" />)}</div>;
  if (!active || id === null) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1>
        <p className="text-muted">{tr("Ajoute ton cluster Proxmox pour voir ses tâches.")}</p>
        <Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button>
      </div>
    </div>
  );

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{tr("Tâches")}</h1>
          <p className="text-muted">{tr("{name} · {host} · lecture seule", { name: active.name, host: active.host })}</p>
        </div>
        <Button variant="ghost" onClick={() => tasks.refetch()} disabled={tasks.isFetching} className="!px-3 !py-1.5">
          <span className={tasks.isFetching ? "inline-block animate-spin" : ""}>↻</span>{" "}{tr("Actualiser")}</Button>
      </header>

      {tasks.error && <Notice kind="error">{(tasks.error as Error).message} — <button className="underline" onClick={() => tasks.refetch()}>{tr("réessayer")}</button></Notice>}
      {tasks.data?.failed.map((f) => <Notice key={f.node} kind="error">{tr("Le nœud « {node} » n'a pas répondu ({reason}). Ses tâches ne sont pas affichées.", { node: f.node, reason: f.reason })}</Notice>)}

      <section className="space-y-3" aria-label={tr("Liste des tâches")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{tr("Tâches")}{" "}<span className="text-sm font-normal text-muted">({rows.length}{rows.length !== (tasks.data?.tasks.length ?? 0) ? ` sur ${tasks.data?.tasks.length}` : ""})</span></h2>
          <div className="flex flex-wrap gap-2">
            <input className={`${sel} min-w-44`} placeholder={tr("Rechercher…")} aria-label={tr("Rechercher une tâche")} value={q} onChange={(e) => setQ(e.target.value)} />
            <select className={sel} aria-label={tr("État")} value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
              <option value="all">{tr("Toutes")}</option><option value="running">{tr("En cours")}</option><option value="error">{tr("Échecs")}</option><option value="warning">{tr("Avertissements")}</option>
            </select>
            <select className={sel} aria-label={tr("Nœud")} value={node} onChange={(e) => setNode(e.target.value)}>
              <option value="all">{tr("Tous les nœuds")}</option>{(nodes.data ?? []).map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}
            </select>
            <select className={sel} aria-label={tr("Nombre de tâches")} value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[50, 100, 250, 500].map((n) => <option key={n} value={n}>{tr("{n} dernières", { n })}</option>)}
            </select>
          </div>
        </div>

        {tasks.isLoading ? <div className="space-y-2">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="panel h-11 animate-pulse" />)}</div>
          : rows.length === 0 ? <div className="panel p-6 text-muted">{(tasks.data?.tasks.length ?? 0) === 0 ? tr("Aucune tâche.") : tr("Aucune tâche ne correspond aux filtres.")}</div>
          : (
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[56rem] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    <th scope="col" className="px-4 py-2 font-normal">{tr("État")}</th><th scope="col" className="px-4 py-2 font-normal">{tr("Tâche")}</th>
                    <th scope="col" className="px-4 py-2 font-normal">{tr("Nœud")}</th><th scope="col" className="px-4 py-2 font-normal">{tr("Utilisateur")}</th>
                    <th scope="col" className="px-4 py-2 font-normal">{tr("Début")}</th><th scope="col" className="px-4 py-2 text-right font-normal">{tr("Durée")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.upid} className="cursor-pointer border-b border-line/60 transition last:border-0 hover:bg-surface2" onClick={() => setOpen(t)}>
                      <td className="px-4 py-2"><Badge s={t.state} /></td>
                      <td className="px-4 py-2">
                        <button type="button" className="text-left font-medium hover:underline focus-visible:underline" onClick={(e) => { e.stopPropagation(); setOpen(t); }}>{taskLabel(t.type)}</button>
                        {target(t) && <span className="block text-xs text-muted">{target(t)}</span>}
                        {t.status_text && <span className="block max-w-md truncate text-xs text-danger" title={t.status_text}>{t.status_text}</span>}
                      </td>
                      <td className="px-4 py-2 text-muted">{t.node ?? "–"}</td>
                      <td className="px-4 py-2 text-muted">{t.user ?? "–"}{t.token ? `!${t.token}` : ""}{t.by_kaji && <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[0.7rem]">{tr("Kaji")}</span>}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-muted">{when(t.start)}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums text-muted">{t.state === "running" ? tr("en cours") : duration(t.duration)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {tasks.data && tasks.data.tasks.length >= limit && <p className="text-xs text-muted">{tr("Les {limit} tâches les plus récentes. Augmente le nombre pour remonter plus loin.", { limit })}</p>}
      </section>

      <ClusterLog connId={id} />

      {open && <TaskDrawer connId={id} task={open} label={`${taskLabel(open.type)}${target(open) ? ` · ${target(open)}` : ""}`} onClose={() => setOpen(null)} />}
    </div>
  );
}
