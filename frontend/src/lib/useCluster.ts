import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, type ClusterStatus, type Guest, type GuestAction, type NodeInfo, type TaskStatus } from "./api";

const POLL_MS = 10_000; // Proxmox rafraîchit ses statistiques environ toutes les 10 s

type Snapshot = { status: ClusterStatus; nodes: NodeInfo[]; guests: Guest[] };

/**
 * Données du cluster. Le flux temps réel (SSE) alimente le cache dès qu'il est connecté ; sinon (connexion
 * perdue, serveur sans SSE) on retombe automatiquement sur un rafraîchissement toutes les 10 s.
 */
export function useCluster(connId: number | null) {
  const qc = useQueryClient();
  const [live, setLive] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    setLive(false); setProblem(null);
    if (connId === null || typeof EventSource === "undefined") return;
    const es = new EventSource(`/api/connections/${connId}/events`);
    es.addEventListener("snapshot", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as Snapshot;
      qc.setQueryData(["cluster", connId, "status"], d.status);
      qc.setQueryData(["cluster", connId, "nodes"], d.nodes);
      qc.setQueryData(["cluster", connId, "guests"], d.guests);
      setLive(true); setProblem(null);
    });
    // Erreur renvoyée par le serveur (Proxmox injoignable…) : les données affichées restent les dernières connues.
    es.addEventListener("problem", (e) => setProblem(JSON.parse((e as MessageEvent).data) as string));
    // Perte de connexion : EventSource retente seul ; en attendant, le rafraîchissement périodique prend le relais.
    es.onerror = () => setLive(false);
    return () => es.close();
  }, [connId, qc]);

  const opts = { enabled: connId !== null, refetchInterval: live ? false : POLL_MS, refetchIntervalInBackground: false } as const;
  const base = `/api/connections/${connId}`;
  const status = useQuery({ queryKey: ["cluster", connId, "status"], queryFn: () => api<ClusterStatus>(`${base}/cluster/status`), ...opts });
  const nodes = useQuery({ queryKey: ["cluster", connId, "nodes"], queryFn: () => api<NodeInfo[]>(`${base}/nodes`), ...opts });
  const guests = useQuery({ queryKey: ["cluster", connId, "guests"], queryFn: () => api<Guest[]>(`${base}/guests`), ...opts });
  return { status, nodes, guests, live, problem };
}

export const LABELS: Record<GuestAction, { busy: string; done: string; expect: "running" | "stopped" }> = {
  start: { busy: "Démarrage…", done: "démarrée", expect: "running" },
  reboot: { busy: "Redémarrage…", done: "redémarrée", expect: "running" },
  shutdown: { busy: "Extinction…", done: "éteinte", expect: "stopped" },
  stop: { busy: "Arrêt forcé…", done: "arrêtée", expect: "stopped" },
};

export const guestKey = (g: Pick<Guest, "node" | "type" | "vmid">) => `${g.node}/${g.type}/${g.vmid}`;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Lance une action, suit la tâche Proxmox jusqu'au bout, et affiche l'état attendu tout de suite
 * (mise à jour optimiste) : la liste Proxmox, elle, peut retarder de ~10 s.
 */
export function useGuestActions(connId: number | null) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [overrides, setOverrides] = useState<Record<string, { status: string; until: number }>>({});

  const run = useCallback(async (g: Guest, action: GuestAction) => {
    const key = guestKey(g), label = g.name ?? String(g.vmid);
    setBusy((b) => ({ ...b, [key]: LABELS[action].busy }));
    const refetch = () => qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] });
    try {
      const { upid } = await api<{ upid: string }>(`/api/connections/${connId}/guests/${g.node}/${g.type}/${g.vmid}/${action}`, {
        method: "POST", body: action === "stop" ? { confirm: true } : {},
      });
      let task: TaskStatus | null = null;
      for (let i = 0; i < 90 && !task; i++) {
        await sleep(1000);
        const t = await api<TaskStatus>(`/api/connections/${connId}/tasks/${g.node}/${encodeURIComponent(upid)}`);
        if (t.status === "stopped") task = t;
      }
      if (task?.ok) {
        toast("ok", `${label} ${LABELS[action].done}`);
        setOverrides((o) => ({ ...o, [key]: { status: LABELS[action].expect, until: Date.now() + 22_000 } }));
      } else {
        toast("error", task ? `${label} : la tâche a échoué (${task.exitstatus ?? "erreur"})` : `${label} : la tâche prend trop de temps`);
      }
    } catch (e) {
      toast("error", `${label} : ${(e as Error).message}`);
    } finally {
      setBusy((b) => { const { [key]: _, ...rest } = b; return rest; });
      refetch();
      setTimeout(refetch, 11_000);
      setTimeout(refetch, 21_000);
    }
  }, [connId, qc, toast]);

  const effectiveStatus = (g: Guest) => {
    const o = overrides[guestKey(g)];
    return o && o.until > Date.now() ? o.status : g.status;
  };
  return { run, busy, effectiveStatus };
}
