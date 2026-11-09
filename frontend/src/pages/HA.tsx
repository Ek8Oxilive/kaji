import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { HaDialog } from "../components/HaDialog";
import { Button, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import type { HaMode, HaResource, HaRule, HaStatus, ReplJob, ReplStatus } from "../lib/types/ha";

const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[32rem] text-sm">
    <thead><tr className="border-b border-line text-left text-xs text-muted">{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
);
const Empty = ({ children }: { children: ReactNode }) => <div className="rounded-xl border border-line bg-surface2 p-4 text-sm text-muted">{children}</div>;
const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : "–");

/** Haute disponibilité (écriture avec verrous, M8-2) et réplication (lecture seule). */
export function HauteDispo({ onGoConnections }: { onGoConnections: () => void }) {
  const { active, id } = useActiveConnection();
  const [mode, setMode] = useState<HaMode | null>(null);
  const q = <T,>(key: string, path: string) => useQuery({ queryKey: ["ha", id, key], queryFn: () => api<T>(`/api/connections/${id}/${path}`), enabled: id !== null, staleTime: 10_000 }); // eslint-disable-line react-hooks/rules-of-hooks
  const status = q<HaStatus[]>("status", "ha/status"), res = q<HaResource[]>("resources", "ha/resources"), rules = q<HaRule[]>("rules", "ha/rules"), jobs = q<ReplJob[]>("jobs", "replication");
  const nodes = useQuery({ queryKey: ["nodes", id], queryFn: () => api<{ node: string }[]>(`/api/connections/${id}/nodes`), enabled: id !== null });
  const rstat = useQuery({
    queryKey: ["ha", id, "rstatus", (nodes.data ?? []).map((n) => n.node).join(",")], enabled: id !== null && !!nodes.data,
    queryFn: async () => (await Promise.all((nodes.data ?? []).map((n) => api<ReplStatus[]>(`/api/connections/${id}/nodes/${encodeURIComponent(n.node)}/replication`).catch(() => [] as ReplStatus[])))).flat(),
  });
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center"><div className="panel space-y-4 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">Aucun cluster connecté</h1><Button onClick={onGoConnections}>Ajouter un cluster</Button></div></div>
  );
  const err = (e: unknown) => <Notice kind="error">{(e as Error).message}</Notice>;
  const quorum = status.data?.find((s) => s.type === "quorum"), fencing = status.data?.find((s) => s.type === "fencing");
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header><h1 className="text-2xl font-semibold tracking-tight">Haute disponibilité et réplication</h1><p className="text-muted">{active.name} · HA modifiable avec verrous · réplication en lecture seule</p></header>
      <Notice kind="ok">Avec deux nœuds, la HA est risquée : si un nœud tombe, l'autre perd le quorum et peut redémarrer de lui-même (chien de garde). Toute écriture HA est d'abord prévisualisée, et exige ici la phrase COUPURE POSSIBLE.</Notice>

      <section className="space-y-3"><h2 className="text-lg font-semibold">État</h2>
        {status.error ? err(status.error) : (
          <p className="text-sm text-muted">Quorum : {quorum ? (quorum.quorate ? "oui" : "NON") : "–"} · Chien de garde : {fencing?.armed_state ?? fencing?.status ?? "–"}
            {(status.data ?? []).filter((s) => s.type === "service").length > 0 && ` · ${(status.data ?? []).filter((s) => s.type === "service").length} service(s) HA`}</p>)}
      </section>

      <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Ressources HA</h2><Button variant="ghost" onClick={() => setMode({ kind: "resource-new" })}>Ajouter une machine…</Button></div>
        {res.error ? err(res.error) : (res.data ?? []).length === 0 ? <Empty>Aucune ressource HA.</Empty> : (
          <Table head={["Machine", "État demandé", "Redémarrages", "Déplacements", "Commentaire", ""]}>{(res.data ?? []).map((r) => (
            <tr key={r.sid} className="border-b border-line/60 last:border-0"><td className="px-4 py-2 font-mono">{r.sid}</td><td className="px-4 py-2">{r.state ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{r.max_restart ?? "–"}</td><td className="px-4 py-2 text-muted">{r.max_relocate ?? "–"}</td><td className="px-4 py-2 text-muted">{r.comment ?? ""}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMode({ kind: "resource-edit", resource: r })}>Modifier</button><button className="underline" onClick={() => setMode({ kind: "migrate", resource: r })}>Migrer</button><button className="underline" onClick={() => setMode({ kind: "relocate", resource: r })}>Relocaliser</button><button className="text-danger underline" onClick={() => setMode({ kind: "resource-delete", resource: r })}>Retirer</button></td></tr>))}</Table>)}
      </section>

      <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Règles HA</h2><Button variant="ghost" onClick={() => setMode({ kind: "rule-new" })}>Nouvelle règle…</Button></div>
        {rules.error ? err(rules.error) : (rules.data ?? []).length === 0 ? <Empty>Aucune règle.</Empty> : (
          <Table head={["Règle", "Type", "Machines", "Nœuds / affinité", ""]}>{(rules.data ?? []).map((r) => (
            <tr key={r.rule} className={`border-b border-line/60 last:border-0 ${r.disable ? "opacity-50" : ""}`}><td className="px-4 py-2 font-mono">{r.rule}</td><td className="px-4 py-2 text-muted">{r.type}</td>
              <td className="px-4 py-2 text-muted">{r.resources.join(", ")}</td>
              <td className="px-4 py-2 text-muted">{r.nodes.length ? r.nodes.map((n) => n.node + (n.priority !== null ? `:${n.priority}` : "")).join(", ") + (r.strict ? " (strict)" : "") : r.affinity ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{r.disable ? "désactivée" : ""}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMode({ kind: "rule-edit", rule: r })}>Modifier</button><button className="text-danger underline" onClick={() => setMode({ kind: "rule-delete", rule: r })}>Supprimer</button></td></tr>))}</Table>)}
      </section>

      <section className="space-y-3"><h2 className="text-lg font-semibold">Réplication</h2>
        {jobs.error ? err(jobs.error) : (jobs.data ?? []).length === 0 ? <Empty>Aucun job de réplication. La réplication exige du stockage ZFS sur les deux nœuds.</Empty> : (
          <Table head={["Job", "Machine", "Source → cible", "Planification", "Dernière synchro", "Prochaine", "Échecs"]}>{(jobs.data ?? []).map((j) => {
            const s = (rstat.data ?? []).find((x) => x.id === j.id);
            return (<tr key={j.id} className={`border-b border-line/60 last:border-0 ${j.disable ? "opacity-50" : ""}`}><td className="px-4 py-2 font-mono">{j.id}</td><td className="px-4 py-2">{j.guest ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{j.source ?? "?"} → {j.target ?? "?"}</td><td className="px-4 py-2 text-muted">{j.schedule ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{when(s?.last_sync ?? null)}</td><td className="px-4 py-2 text-muted">{when(s?.next_sync ?? null)}</td>
              <td className={`px-4 py-2 ${s?.fail_count ? "text-danger" : "text-muted"}`} title={s?.error ?? undefined}>{s?.fail_count ?? 0}</td></tr>);
          })}</Table>)}
      </section>
      {mode && id !== null && <HaDialog connId={id} mode={mode} onClose={() => setMode(null)} />}
    </div>
  );
}
