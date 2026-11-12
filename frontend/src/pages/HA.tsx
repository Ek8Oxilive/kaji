import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { HaDialog } from "../components/HaDialog";
import { ReplDialog } from "../components/ReplDialog";
import { Button, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import type { HaMode, HaResource, HaRule, HaStatus, ReplJob, ReplMode, ReplStatus } from "../lib/types/ha";

import { tr } from "../lib/i18n";
const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[32rem] text-sm">
    <thead><tr className="border-b border-line text-left text-xs text-muted">{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
);
const Empty = ({ children }: { children: ReactNode }) => <div className="rounded-xl border border-line bg-surface2 p-4 text-sm text-muted">{children}</div>;
const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : "–");

/** Page « HA » : haute disponibilité (M8-2) et réplication (M8-3), écritures verrouillées avec aperçu. */
export function HA({ onGoConnections }: { onGoConnections: () => void }) {
  const { active, id } = useActiveConnection();
  const [mode, setMode] = useState<HaMode | null>(null), [rmode, setRmode] = useState<ReplMode | null>(null);
  const q = <T,>(key: string, path: string) => useQuery({ queryKey: ["ha", id, key], queryFn: () => api<T>(`/api/connections/${id}/${path}`), enabled: id !== null, staleTime: 10_000 }); // eslint-disable-line react-hooks/rules-of-hooks
  const status = q<HaStatus[]>("status", "ha/status"), res = q<HaResource[]>("resources", "ha/resources"), rules = q<HaRule[]>("rules", "ha/rules"), jobs = q<ReplJob[]>("jobs", "replication");
  const nodes = useQuery({ queryKey: ["nodes", id], queryFn: () => api<{ node: string }[]>(`/api/connections/${id}/nodes`), enabled: id !== null });
  const rstat = useQuery({
    queryKey: ["ha", id, "rstatus", (nodes.data ?? []).map((n) => n.node).join(",")], enabled: id !== null && !!nodes.data,
    queryFn: async () => (await Promise.all((nodes.data ?? []).map((n) => api<ReplStatus[]>(`/api/connections/${id}/nodes/${encodeURIComponent(n.node)}/replication`).catch(() => [] as ReplStatus[])))).flat(),
  });
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center"><div className="panel space-y-4 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1><Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button></div></div>
  );
  const err = (e: unknown) => <Notice kind="error">{(e as Error).message}</Notice>;
  const quorum = status.data?.find((s) => s.type === "quorum"), fencing = status.data?.find((s) => s.type === "fencing");
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header><h1 className="text-2xl font-semibold tracking-tight">{tr("HA : haute disponibilité et réplication")}</h1><p className="text-muted">{tr("{name} · écritures verrouillées, avec aperçu", { name: active.name })}</p></header>
      <Notice kind="ok">{tr("Avec deux nœuds, la HA est risquée : si un nœud tombe, l'autre perd le quorum et peut redémarrer de lui-même (watchdog). Toute écriture HA est d'abord prévisualisée, et exige ici la phrase COUPURE POSSIBLE.")}</Notice>

      <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("État")}</h2>
        {status.error ? err(status.error) : (status.data ?? []).length === 0 ? <Empty>{tr("Aucun état HA.")}</Empty> : (
          <Table head={[tr("Type"), tr("Nœud / machine"), tr("État")]}>{(status.data ?? []).map((s, i) => (
            <tr key={`${s.type}-${s.id}-${i}`} className="border-b border-line/60 last:border-0">
              <td className="px-4 py-2 text-muted">{{ quorum: tr("Quorum"), master: tr("Maître"), lrm: "LRM", service: tr("Service"), fencing: tr("Watchdog") }[s.type]}</td>
              <td className="px-4 py-2 font-mono">{s.type === "service" ? s.sid ?? "–" : s.node ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{s.status ?? s.state ?? "–"}{s.type === "service" && s.request_state ? tr(" · demandé : {request_state}", { request_state: s.request_state }) : ""}</td></tr>))}</Table>)}
        <p className="text-xs text-muted">{tr("Quorum : {p} · Watchdog : {p2}", { p: quorum ? (quorum.quorate ? "oui" : "NON") : "–", p2: fencing?.armed_state ?? fencing?.status ?? "–" })}</p>
      </section>

      <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{tr("Ressources HA")}</h2><Button variant="ghost" onClick={() => setMode({ kind: "resource-new" })}>{tr("Ajouter une machine…")}</Button></div>
        {res.error ? err(res.error) : (res.data ?? []).length === 0 ? <Empty>{tr("Aucune ressource HA.")}</Empty> : (
          <Table head={[tr("Machine"), tr("État demandé"), tr("Redémarrages"), tr("Déplacements"), tr("Commentaire"), ""]}>{(res.data ?? []).map((r) => (
            <tr key={r.sid} className="border-b border-line/60 last:border-0"><td className="px-4 py-2 font-mono">{r.sid}</td><td className="px-4 py-2">{r.state ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{r.max_restart ?? "–"}</td><td className="px-4 py-2 text-muted">{r.max_relocate ?? "–"}</td><td className="px-4 py-2 text-muted">{r.comment ?? ""}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMode({ kind: "resource-edit", resource: r })}>{tr("Modifier")}</button><button className="underline" onClick={() => setMode({ kind: "migrate", resource: r })}>{tr("Migrer")}</button><button className="underline" onClick={() => setMode({ kind: "relocate", resource: r })}>{tr("Relocaliser")}</button><button className="text-danger underline" onClick={() => setMode({ kind: "resource-delete", resource: r })}>{tr("Retirer")}</button></td></tr>))}</Table>)}
      </section>

      <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{tr("Règles HA")}</h2><Button variant="ghost" onClick={() => setMode({ kind: "rule-new" })}>{tr("Nouvelle règle…")}</Button></div>
        {rules.error ? err(rules.error) : (rules.data ?? []).length === 0 ? <Empty>{tr("Aucune règle.")}</Empty> : (
          <Table head={[tr("Règle"), tr("Type"), tr("Machines"), tr("Nœuds / affinité"), ""]}>{(rules.data ?? []).map((r) => (
            <tr key={r.rule} className={`border-b border-line/60 last:border-0 ${r.disable ? "opacity-50" : ""}`}><td className="px-4 py-2 font-mono">{r.rule}</td><td className="px-4 py-2 text-muted">{r.type}</td>
              <td className="px-4 py-2 text-muted">{r.resources.join(", ")}</td>
              <td className="px-4 py-2 text-muted">{r.nodes.length ? r.nodes.map((n) => n.node + (n.priority !== null ? `:${n.priority}` : "")).join(", ") + (r.strict ? " (strict)" : "") : r.affinity ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{r.disable ? tr("désactivée") : ""}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMode({ kind: "rule-edit", rule: r })}>{tr("Modifier")}</button><button className="text-danger underline" onClick={() => setMode({ kind: "rule-delete", rule: r })}>{tr("Supprimer")}</button></td></tr>))}</Table>)}
      </section>

      <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{tr("Réplication")}</h2><Button variant="ghost" onClick={() => setRmode({ kind: "new" })}>{tr("Nouveau job…")}</Button></div>
        {jobs.error ? err(jobs.error) : (jobs.data ?? []).length === 0 ? <Empty>{tr("Aucun job de réplication. La réplication exige du stockage ZFS sur les deux nœuds : sans lui, « Nouveau job… » indiquera ce qui bloque.")}</Empty> : (
          <Table head={[tr("Job"), tr("Machine"), "Source → cible", tr("Planification"), tr("Dernière synchro"), tr("Prochaine"), tr("Échecs"), ""]}>{(jobs.data ?? []).map((j) => {
            const s = (rstat.data ?? []).find((x) => x.id === j.id);
            return (<tr key={j.id} className={`border-b border-line/60 last:border-0 ${j.disable ? "opacity-50" : ""}`}><td className="px-4 py-2 font-mono">{j.id}</td><td className="px-4 py-2">{j.guest ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{j.source ?? "?"} → {j.target ?? "?"}</td><td className="px-4 py-2 text-muted">{j.schedule ?? "–"}</td>
              <td className="px-4 py-2 text-muted">{when(s?.last_sync ?? null)}</td><td className="px-4 py-2 text-muted">{when(s?.next_sync ?? null)}</td>
              <td className={`px-4 py-2 ${s?.fail_count ? "text-danger" : "text-muted"}`} title={s?.error ?? undefined}>{s?.fail_count ?? 0}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs">{j.remove_job ? <span className="text-muted">{tr("suppression en cours")}</span> : <><button className="underline" onClick={() => setRmode({ kind: "edit", job: j })}>{tr("Modifier")}</button><button className="underline" onClick={() => setRmode({ kind: "now", job: j })}>{tr("Lancer")}</button><button className="text-danger underline" onClick={() => setRmode({ kind: "delete", job: j })}>{tr("Supprimer")}</button></>}</td></tr>);
          })}</Table>)}
      </section>
      {mode && id !== null && <HaDialog connId={id} mode={mode} onClose={() => setMode(null)} />}
      {rmode && id !== null && <ReplDialog connId={id} mode={rmode} onClose={() => setRmode(null)} />}
    </div>
  );
}
