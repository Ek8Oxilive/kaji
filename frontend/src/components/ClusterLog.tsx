import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import type { ClusterLog as Log } from "../lib/types/journal";
import { when } from "./TaskDrawer";
import { Notice } from "./ui";

const SEVERITY = [() => tr("Urgence"), () => tr("Alerte"), () => tr("Critique"), () => tr("Erreur"), () => tr("Avertissement"), () => tr("Notice"), () => tr("Info"), () => tr("Debug")];
const tone = (pri: number) => (pri <= 3 ? "text-danger" : pri === 4 ? "text-warn" : "text-muted");

/** Journal du cluster (Datacenter → Journal du cluster) : les dernières entrées, filtrables ; lecture seule, rafraîchi toutes les 30 s. */
export function ClusterLog({ connId }: { connId: number }) {
  const [max, setMax] = useState(100), [sev, setSev] = useState("all"), [node, setNode] = useState("all"), [q, setQ] = useState("");
  const log = useQuery({ queryKey: ["cluster-log", connId, max], refetchInterval: 30_000, queryFn: () => api<Log>(`/api/connections/${connId}/cluster/log?max=${max}`) });
  const all = log.data?.entries ?? [];
  const nodes = useMemo(() => [...new Set(all.map((e) => e.node).filter(Boolean))].sort(), [all]);
  const needle = q.trim().toLowerCase();
  const rows = all.filter((e) => (sev === "all" || e.pri <= Number(sev)) && (node === "all" || e.node === node)
    && (!needle || `${e.msg} ${e.tag} ${e.user ?? ""}`.toLowerCase().includes(needle)));

  return (
    <section className="space-y-3" aria-label={tr("Journal du cluster")}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{tr("Journal du cluster")}</h2>
          <p className="text-sm text-muted">{tr("Dernières entrées du journal du cluster (démons de Proxmox, corosync, pmxcfs…). Lecture seule.")}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <select className="field !w-auto" value={sev} onChange={(e) => setSev(e.target.value)} aria-label={tr("Gravité")}>
            <option value="all">{tr("Toutes les gravités")}</option><option value="3">{tr("Erreurs et pires")}</option><option value="4">{tr("Avertissements et pires")}</option>
          </select>
          <select className="field !w-auto" value={node} onChange={(e) => setNode(e.target.value)} aria-label={tr("Nœud")}>
            <option value="all">{tr("Tous les nœuds")}</option>{nodes.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <select className="field !w-auto" value={max} onChange={(e) => setMax(Number(e.target.value))} aria-label={tr("Nombre d'entrées")}>
            {[100, 200, 500].map((n) => <option key={n} value={n}>{tr("{n} entrées", { n })}</option>)}
          </select>
          <input className="field !w-48" value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr("Chercher dans le journal…")} aria-label={tr("Chercher dans le journal…")} autoComplete="off" />
        </div>
      </div>
      {log.isLoading ? <div className="panel h-24 animate-pulse" />
        : log.error ? <Notice kind="error">{tr("Lecture impossible : {message}", { message: (log.error as Error).message })}</Notice>
        : rows.length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{tr("Aucune entrée.")}</div>
        : (
          <div className="panel max-h-[32rem] overflow-auto">
            <table className="w-full min-w-[44rem] text-sm">
              <thead className="sticky top-0 bg-surface2"><tr className="border-b border-line text-left text-xs text-muted">
                <th scope="col" className="px-3 py-2 font-normal">{tr("Heure")}</th><th scope="col" className="px-3 py-2 font-normal">{tr("Gravité")}</th>
                <th scope="col" className="px-3 py-2 font-normal">{tr("Nœud")}</th><th scope="col" className="px-3 py-2 font-normal">{tr("Service")}</th>
                <th scope="col" className="px-3 py-2 font-normal">{tr("Utilisateur")}</th><th scope="col" className="px-3 py-2 font-normal">{tr("Message")}</th></tr></thead>
              <tbody>{rows.map((e, i) => (
                <tr key={`${e.time}-${i}`} className="border-b border-line/60 align-top last:border-0">
                  <td className="whitespace-nowrap px-3 py-1.5 text-muted">{e.time ? when(new Date(e.time * 1000).toISOString()) : "–"}</td>
                  <td className={`whitespace-nowrap px-3 py-1.5 ${tone(e.pri)}`}>{SEVERITY[e.pri]()}</td>
                  <td className="px-3 py-1.5 text-muted">{e.node || "–"}</td>
                  <td className="px-3 py-1.5 text-muted">{e.tag || "–"}{e.pid !== null ? <span className="text-xs">[{e.pid}]</span> : null}</td>
                  <td className="px-3 py-1.5 text-muted">{e.user ?? "–"}</td>
                  <td className="break-words px-3 py-1.5">{e.msg}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      {log.data && <p className="text-xs text-muted">{tr("{n} entrées affichées sur {total}", { n: rows.length, total: all.length })}</p>}
    </section>
  );
}
