import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, TaskDrawer } from "./TaskDrawer";
import { api, type Guest } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { duration, taskLabel } from "../lib/taskLabels";
import type { TaskList, TaskRow } from "../lib/types/taches";

const OPEN_KEY = "kaji-taskbar-open";
const SHOWN = 6;                                                   // tâches récentes montrées dans la barre
const smallScreen = () => typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches;
// Sans choix enregistré : dépliée sur grand écran, repliée sur petit écran (elle y prendrait trop de place).
const readOpen = () => { try { const v = localStorage.getItem(OPEN_KEY); return v === null ? !smallScreen() : v !== "0"; } catch { return !smallScreen(); } };
const saveOpen = (v: boolean) => { try { localStorage.setItem(OPEN_KEY, v ? "1" : "0"); } catch { /* sans stockage : la barre reste dépliée à chaque visite */ } };

/** Barre de tâches permanente, en bas de chaque page (comme celle de Proxmox) : tâches en cours et dernières tâches, journal en un clic.
 *  Lecture seule : `GET /api/connections/{id}/tasks`. */
export function TaskBar({ onOpenTasks }: { onOpenTasks: () => void }) {
  const { id } = useActiveConnection();
  const [open, setOpen] = useState(readOpen);
  const [sel, setSel] = useState<TaskRow | null>(null);
  const tasks = useQuery({
    queryKey: ["taskbar", id], enabled: id !== null, queryFn: () => api<TaskList>(`/api/connections/${id}/tasks?limit=${SHOWN}`),
    refetchInterval: (q) => (q.state.data?.tasks.some((t) => t.state === "running") ? 3000 : 15_000),
  });
  const guests = useQuery({ queryKey: ["cluster", id, "guests"], enabled: id !== null, staleTime: 30_000, queryFn: () => api<Guest[]>(`/api/connections/${id}/guests`) });
  if (id === null) return null;

  const names = new Map((guests.data ?? []).map((g) => [String(g.vmid), g.name]));
  const target = (t: TaskRow) => (t.id ? (names.get(t.id) ? `${names.get(t.id)} · #${t.id}` : t.id) : "");
  const label = (t: TaskRow) => `${taskLabel(t.type)}${target(t) ? ` · ${target(t)}` : ""}`;
  const rows = tasks.data?.tasks ?? [];
  const running = rows.filter((t) => t.state === "running").length;
  const failed = rows.filter((t) => t.state === "error").length;
  const toggle = () => { saveOpen(!open); setOpen(!open); };

  return (
    <>
    <footer aria-label="Barre de tâches" className="panel sticky bottom-0 z-30 mx-2 mb-2 !rounded-2xl p-2 sm:mx-3 sm:mb-3 md:mx-6">
      <div className="flex flex-wrap items-center gap-3 px-2 text-sm">
        <button onClick={toggle} aria-expanded={open} className="rounded-lg px-2 py-1 text-left font-medium hover:bg-surface2">
          {open ? "▾" : "▸"} Tâches
        </button>
        <span className="text-xs text-muted" role="status">
          {tasks.isLoading ? "Chargement…" : tasks.error ? "Tâches illisibles" : running ? `${running} en cours` : "Aucune tâche en cours"}
          {failed > 0 && ` · ${failed} échec${failed > 1 ? "s" : ""} récent${failed > 1 ? "s" : ""}`}
        </span>
        <button onClick={onOpenTasks} className="ml-auto rounded-lg px-2 py-1 text-xs text-muted hover:bg-surface2 hover:text-fg">Toutes les tâches</button>
      </div>
      {open && (
        <ul className="mt-1 max-h-[6.75rem] divide-y divide-line overflow-y-auto" aria-label="Dernières tâches">
          {rows.length === 0 && !tasks.isLoading && <li className="px-3 py-2 text-xs text-muted">Aucune tâche récente.</li>}
          {rows.map((t) => (
            <li key={t.upid}>
              <button onClick={() => setSel(t)} className="flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left text-xs hover:bg-surface2">
                <span className="w-20 shrink-0 sm:w-24"><Badge s={t.state} /></span>
                <span className="min-w-0 flex-1 truncate">{label(t)}</span>
                <span className="hidden shrink-0 text-muted sm:inline">{t.node}</span>
                <span className="hidden w-20 shrink-0 text-right text-muted sm:inline">{duration(t.duration)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </footer>
    {/* Hors de la barre : son flou d'arrière-plan en ferait le repère des éléments `fixed`, et le tiroir resterait coincé dedans. */}
    {sel && <TaskDrawer connId={id} task={sel} label={label(sel)} onClose={() => setSel(null)} />}
    </>
  );
}
