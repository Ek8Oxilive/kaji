import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Notice } from "../components/ui";
import { api, type Guest, type NodeInfo } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { STATE_LABEL, duration, taskLabel } from "../lib/taskLabels";
import type { TaskDetail, TaskLine, TaskList, TaskRow, TaskState } from "../lib/types/taches";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" }) : "–");
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const LOG_CHUNK = 1000;
const LOG_MAX = 20_000;            // lignes gardées en mémoire : au-delà, on le dit au lieu de ralentir la page

/** Couleur ET mot : l'état ne repose jamais sur la couleur seule. */
const TONE: Record<TaskState, { dot: string; text: string }> = {
  running: { dot: "bg-accent animate-pulse", text: "text-accent" }, ok: { dot: "bg-ok", text: "text-ok" },
  warning: { dot: "bg-warn", text: "text-warn" }, error: { dot: "bg-danger", text: "text-danger" },
};
const Badge = ({ s }: { s: TaskState }) => <span className={`flex items-center gap-1.5 text-xs ${TONE[s].text}`}><span className={`size-2 rounded-full ${TONE[s].dot}`} />{STATE_LABEL[s]}</span>;

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
        <h1 className="text-2xl font-semibold tracking-tight">Aucun cluster connecté</h1>
        <p className="text-muted">Ajoute ton cluster Proxmox pour voir ses tâches.</p>
        <Button onClick={onGoConnections}>Ajouter un cluster</Button>
      </div>
    </div>
  );

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tâches</h1>
          <p className="text-muted">{active.name} · {active.host} · lecture seule</p>
        </div>
        <Button variant="ghost" onClick={() => tasks.refetch()} disabled={tasks.isFetching} className="!px-3 !py-1.5">
          <span className={tasks.isFetching ? "inline-block animate-spin" : ""}>↻</span> Actualiser
        </Button>
      </header>

      {tasks.error && <Notice kind="error">{(tasks.error as Error).message} — <button className="underline" onClick={() => tasks.refetch()}>réessayer</button></Notice>}
      {tasks.data?.failed.map((f) => <Notice key={f.node} kind="error">Le nœud « {f.node} » n'a pas répondu ({f.reason}). Ses tâches ne sont pas affichées.</Notice>)}

      <section className="space-y-3" aria-label="Liste des tâches">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Tâches <span className="text-sm font-normal text-muted">({rows.length}{rows.length !== (tasks.data?.tasks.length ?? 0) ? ` sur ${tasks.data?.tasks.length}` : ""})</span></h2>
          <div className="flex flex-wrap gap-2">
            <input className={`${sel} min-w-44`} placeholder="Rechercher…" aria-label="Rechercher une tâche" value={q} onChange={(e) => setQ(e.target.value)} />
            <select className={sel} aria-label="État" value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
              <option value="all">Toutes</option><option value="running">En cours</option><option value="error">Échecs</option><option value="warning">Avertissements</option>
            </select>
            <select className={sel} aria-label="Nœud" value={node} onChange={(e) => setNode(e.target.value)}>
              <option value="all">Tous les nœuds</option>{(nodes.data ?? []).map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}
            </select>
            <select className={sel} aria-label="Nombre de tâches" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[50, 100, 250, 500].map((n) => <option key={n} value={n}>{n} dernières</option>)}
            </select>
          </div>
        </div>

        {tasks.isLoading ? <div className="space-y-2">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="panel h-11 animate-pulse" />)}</div>
          : rows.length === 0 ? <div className="panel p-6 text-muted">{(tasks.data?.tasks.length ?? 0) === 0 ? "Aucune tâche." : "Aucune tâche ne correspond aux filtres."}</div>
          : (
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[56rem] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    <th scope="col" className="px-4 py-2 font-normal">État</th><th scope="col" className="px-4 py-2 font-normal">Tâche</th>
                    <th scope="col" className="px-4 py-2 font-normal">Nœud</th><th scope="col" className="px-4 py-2 font-normal">Utilisateur</th>
                    <th scope="col" className="px-4 py-2 font-normal">Début</th><th scope="col" className="px-4 py-2 text-right font-normal">Durée</th>
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
                      <td className="px-4 py-2 text-muted">{t.user ?? "–"}{t.token ? `!${t.token}` : ""}{t.by_kaji && <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[0.7rem]">Kaji</span>}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-muted">{when(t.start)}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums text-muted">{t.state === "running" ? "en cours" : duration(t.duration)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {tasks.data && tasks.data.tasks.length >= limit && <p className="text-xs text-muted">Les {limit} tâches les plus récentes. Augmente le nombre pour remonter plus loin.</p>}
      </section>

      {open && <TaskDrawer connId={id} task={open} label={`${taskLabel(open.type)}${target(open) ? ` · ${target(open)}` : ""}`} onClose={() => setOpen(null)} />}
    </div>
  );
}

/** Tiroir d'une tâche : état, puis journal ; une tâche en cours est suivie en direct. */
function TaskDrawer({ connId, task, label, onClose }: { connId: number; task: TaskRow; label: string; onClose: () => void }) {
  const base = `/api/connections/${connId}/tasks/${encodeURIComponent(task.node ?? "")}/${encodeURIComponent(task.upid)}`;
  const detail = useQuery({ queryKey: ["task", connId, task.upid], queryFn: () => api<TaskDetail>(base), refetchInterval: (q) => (q.state.data?.status === "stopped" ? false : 2000) });
  const running = detail.data ? detail.data.status !== "stopped" : task.state === "running";
  const runningRef = useRef(running);
  runningRef.current = running;
  const [lines, setLines] = useState<TaskLine[]>([]);
  const [logError, setLogError] = useState<string | null>(null);
  const [capped, setCapped] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Lecture incrémentale du journal : on ne redemande jamais ce qu'on a déjà ; tant que la tâche tourne, on revient toutes les 2 s.
  useEffect(() => {
    let stop = false;
    let have = 0;
    (async () => {
      while (!stop) {
        try {
          const chunk = await api<TaskLine[]>(`${base}/log?start=${have}&limit=${LOG_CHUNK}`);
          if (stop) return;
          setLogError(null);
          if (chunk.length) { have += chunk.length; setLines((cur) => [...cur, ...chunk]); }
          if (have >= LOG_MAX) { setCapped(true); return; }
          if (chunk.length === LOG_CHUNK) continue;            // il en reste
        } catch (e) {
          if (!stop) setLogError((e as Error).message);
          return;
        }
        if (!runningRef.current) return;                        // terminée, et la dernière lecture vient d'être faite
        await sleep(2000);
      }
    })();
    return () => { stop = true; };
  }, [base]);

  useEffect(() => { if (follow.current) box.current?.scrollTo({ top: box.current.scrollHeight }); }, [lines]);

  const d = detail.data;
  const state: TaskState = running ? "running" : d ? (d.warnings ? "warning" : d.ok ? "ok" : "error") : task.state;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label={`Tâche : ${label}`} onClick={(e) => e.stopPropagation()}
        className="panel rise flex h-full w-[min(56rem,100vw)] flex-col gap-4 !rounded-none !rounded-l-2xl p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold">{label}</h2>
            <p className="truncate text-sm text-muted">{task.node} · {task.user ?? "–"}{task.token ? `!${task.token}` : ""} · {when(task.start)}</p>
          </div>
          <Button variant="ghost" onClick={onClose} aria-label="Fermer" className="!px-3 !py-1" autoFocus>✕</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3"><Badge s={state} />{running && <span className="text-xs text-muted">Journal suivi en direct</span>}</div>
        {!running && d?.exitstatus && d.exitstatus !== "OK" && <Notice kind={d.warnings ? "ok" : "error"}>{d.exitstatus}</Notice>}
        {detail.error && <Notice kind="error">{(detail.error as Error).message}</Notice>}
        {logError && <Notice kind="error">Journal illisible : {logError}</Notice>}
        <div ref={box} onScroll={(e) => { const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}
          className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-line bg-black/40 p-3 font-mono text-xs leading-relaxed" aria-label="Journal de la tâche" tabIndex={0}>
          {lines.length === 0 && !logError ? <p className="text-muted">{running ? "En attente de sortie…" : "Journal vide."}</p>
            : lines.map((l, i) => <div key={l.n ?? i} className="whitespace-pre-wrap break-all">{l.t}</div>)}
          {capped && <p className="mt-2 text-warn">Journal tronqué : seules les {LOG_MAX.toLocaleString("fr-FR")} premières lignes sont affichées.</p>}
        </div>
      </aside>
    </div>
  );
}
