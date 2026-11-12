import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button, Notice } from "./ui";
import { api } from "../lib/api";
import { STATE_LABEL } from "../lib/taskLabels";
import type { TaskDetail, TaskLine, TaskRow, TaskState } from "../lib/types/taches";

import { tr, locale } from "../lib/i18n";
export const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(locale(), { dateStyle: "short", timeStyle: "medium" }) : "–");
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const LOG_CHUNK = 1000;
const LOG_MAX = 20_000;            // lignes gardées en mémoire : au-delà, on le dit au lieu de ralentir la page

/** Couleur ET mot : l'état ne repose jamais sur la couleur seule. */
const TONE: Record<TaskState, { dot: string; text: string }> = {
  running: { dot: "bg-accent animate-pulse", text: "text-accent" }, ok: { dot: "bg-ok", text: "text-ok" },
  warning: { dot: "bg-warn", text: "text-warn" }, error: { dot: "bg-danger", text: "text-danger" },
};
export const Badge = ({ s }: { s: TaskState }) => <span className={`flex items-center gap-1.5 text-xs ${TONE[s].text}`}><span className={`size-2 rounded-full ${TONE[s].dot}`} />{STATE_LABEL[s]}</span>;

/** Tiroir d'une tâche : état, puis journal ; une tâche en cours est suivie en direct. */
export function TaskDrawer({ connId, task, label, onClose }: { connId: number; task: TaskRow; label: string; onClose: () => void }) {
  const base = `/api/connections/${connId}/tasks/${encodeURIComponent(task.node ?? "")}/${encodeURIComponent(task.upid)}`;
  const detail = useQuery({ queryKey: ["task", connId, task.upid], queryFn: () => api<TaskDetail>(base), refetchInterval: (q) => (q.state.data?.status === "stopped" ? false : 2000) });
  const running = detail.data ? detail.data.status !== "stopped" : task.state === "running";
  const qc = useQueryClient();
  const [askStop, setAskStop] = useState(false), [stopping, setStopping] = useState(false), [stopErr, setStopErr] = useState<string | null>(null);
  /** Arrêt d'une tâche en cours : le serveur relit tout (en cours, type autorisé, machine non protégée) ; `stoppable` n'est qu'un indice d'affichage. */
  const stopTask = async () => {
    setStopping(true); setStopErr(null);
    try { await api(`${base}?confirm=true`, { method: "DELETE" }); setAskStop(false); await qc.invalidateQueries({ queryKey: ["task", connId, task.upid] }); }
    catch (e) { setStopErr((e as Error).message); }
    setStopping(false);
  };
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
      <aside role="dialog" aria-modal="true" aria-label={tr("Tâche : {label}", { label })} onClick={(e) => e.stopPropagation()}
        className="panel rise flex h-full w-[min(56rem,100vw)] flex-col gap-4 !rounded-none !rounded-l-2xl p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold">{label}</h2>
            <p className="truncate text-sm text-muted">{task.node} · {task.user ?? "–"}{task.token ? `!${task.token}` : ""} · {when(task.start)}</p>
          </div>
          <Button variant="ghost" onClick={onClose} aria-label={tr("Fermer")} className="!px-3 !py-1" autoFocus>✕</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3"><Badge s={state} />{running && <span className="text-xs text-muted">{tr("Journal suivi en direct")}</span>}
          {running && d?.stoppable && !askStop && <Button variant="danger" className="!px-3 !py-1" onClick={() => setAskStop(true)} title={tr("Abandonne le travail en cours de cette tâche")}>{tr("Arrêter la tâche")}</Button>}</div>
        {running && d?.stoppable && askStop && (
          <div className="space-y-2 rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn" role="alert">
            <p>{tr("Arrêter cette tâche abandonne son travail en cours (Proxmox nettoie ce qu'il peut). Confirmer l'arrêt ?")}</p>
            <div className="flex gap-2"><Button variant="danger" className="!px-3 !py-1" onClick={stopTask} disabled={stopping}>{stopping ? "…" : tr("Confirmer l'arrêt")}</Button>
              <Button variant="ghost" className="!px-3 !py-1" onClick={() => { setAskStop(false); setStopErr(null); }} disabled={stopping}>{tr("Annuler")}</Button></div>
          </div>)}
        {stopErr && <Notice kind="error">{stopErr}</Notice>}
        {!running && d?.exitstatus && d.exitstatus !== "OK" && <Notice kind={d.warnings ? "ok" : "error"}>{d.exitstatus}</Notice>}
        {detail.error && <Notice kind="error">{(detail.error as Error).message}</Notice>}
        {logError && <Notice kind="error">{tr("Journal illisible : {logError}", { logError })}</Notice>}
        <div ref={box} onScroll={(e) => { const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}
          className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-line bg-[var(--code-bg)] p-3 font-mono text-xs leading-relaxed" aria-label={tr("Journal de la tâche")} tabIndex={0}>
          {lines.length === 0 && !logError ? <p className="text-muted">{running ? tr("En attente de sortie…") : tr("Journal vide.")}</p>
            : lines.map((l, i) => <div key={l.n ?? i} className="whitespace-pre-wrap break-all">{l.t}</div>)}
          {capped && <p className="mt-2 text-warn">{tr("Journal tronqué : seules les {p} premières lignes sont affichées.", { p: LOG_MAX.toLocaleString(locale()) })}</p>}
        </div>
      </aside>
    </div>
  );
}
