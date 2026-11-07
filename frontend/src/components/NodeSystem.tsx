import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { bytes, uptime } from "../lib/format";
import type { NodeSystem as Sys, Section, SyslogLines } from "../lib/types/systeme";
import { Button, Notice } from "./ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR") : "–");
const daysLeft = (iso: string | null) => (iso ? Math.floor((new Date(iso).getTime() - Date.now()) / 86_400_000) : null);

/** Une rubrique : contenu si lisible, sinon la raison (droit manquant, erreur) sans bloquer les autres. */
function Block<T>({ title, section, hint, children }: { title: string; section: Section<T> | undefined; hint?: string; children: (d: T) => React.ReactNode }) {
  return (
    <div className="panel space-y-2 p-4">
      <h3 className="font-semibold">{title}</h3>
      {!section ? <div className="h-10 animate-pulse rounded bg-surface2" />
        : section.state === "forbidden" ? <p className="text-sm text-muted">Droit manquant pour le token de Kaji{hint ? ` (${hint})` : ""}. La page « Accès » donne la commande à copier.</p>
        : section.state === "error" || !section.data ? <p className="text-sm text-danger">Lecture impossible.</p>
        : children(section.data)}
    </div>
  );
}

export function NodeSystem({ connId, node, online }: { connId: number; node: string; online: boolean }) {
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}`;
  const q = useQuery({ queryKey: ["node-system", connId, node], enabled: online, staleTime: 30_000, queryFn: () => api<Sys>(`${base}/system`) });
  const [logOn, setLogOn] = useState(false);
  const log = useQuery({ queryKey: ["node-syslog", connId, node], enabled: online && logOn, staleTime: 5_000, queryFn: () => api<SyslogLines>(`${base}/syslog?limit=200`) });
  if (!online) return <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Nœud hors ligne : système indisponible.</div>;
  if (q.error) return <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>réessayer</button></Notice>;
  const d = q.data;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">Lecture seule. Les mises à jour, les services, les disques et le reste se modifient pour l'instant dans Proxmox.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Version" section={d?.status}>{(s) => (
          <dl className="space-y-1 text-sm"><div>{s.pveversion ?? "–"}</div><div className="text-muted">Noyau {s.kernel ?? "–"} · démarrage {s.boot_mode ?? "–"}</div><div className="text-muted">Actif depuis {s.uptime != null ? uptime(s.uptime) : "–"}</div></dl>)}</Block>
        <Block title="Heure et DNS" section={d?.time}>{(t) => (
          <div className="space-y-1 text-sm"><div>{t.timezone ?? "–"} · {when(t.localtime)}</div>
            {d?.dns.state === "ok" && d.dns.data && <div className="text-muted">DNS {d.dns.data.servers.join(", ") || "–"} · domaine {d.dns.data.search ?? "–"}</div>}</div>)}</Block>
      </div>

      <Block title={`Mises à jour disponibles${d?.updates.data ? ` (${d.updates.data.length})` : ""}`} section={d?.updates} hint="Sys.Modify">{(u) => u.length === 0
        ? <p className="text-sm text-ok">Le nœud est à jour.</p>
        : <div className="max-h-64 overflow-auto"><table className="w-full text-sm"><tbody>{u.map((p) => (
          <tr key={p.package} className="border-b border-line/60 last:border-0"><td className="py-1 pr-3 font-medium">{p.package}</td><td className="py-1 pr-3 text-muted">{p.from ?? "–"} → {p.to ?? "–"}</td><td className="py-1 text-muted">{p.title}</td></tr>))}</tbody></table></div>}</Block>

      <Block title="Dépôts de paquets" section={d?.repositories}>{(r) => (
        <div className="space-y-2 text-sm">{r.files.map((f) => (<div key={f.path}><div className="text-xs text-muted">{f.path}</div>
          {f.repositories.map((x, i) => (<div key={i} className={x.enabled ? "" : "text-muted line-through"}>{x.types.join(" ")} {x.uris.join(" ")} {x.suites.join(" ")} {x.components.join(" ")}</div>))}</div>))}
          {r.errors > 0 && <p className="text-danger">{r.errors} fichier(s) de dépôts illisible(s).</p>}</div>)}</Block>

      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Certificats" section={d?.certificates}>{(c) => (
          <div className="space-y-2 text-sm">{c.map((x) => { const left = daysLeft(x.not_after); return (
            <div key={x.file ?? x.fingerprint}><div className="font-medium">{x.file}</div><div className="truncate text-xs text-muted" title={x.subject ?? ""}>{x.subject}</div>
              <div className={`text-xs ${left != null && left < 30 ? "text-danger" : "text-muted"}`}>Expire le {when(x.not_after)}{left != null && ` (${left} j)`}</div></div>); })}</div>)}</Block>
        <Block title="Disques" section={d?.disks}>{(ds) => ds.length === 0 ? <p className="text-sm text-muted">Aucun disque.</p> : (
          <div className="space-y-1 text-sm">{ds.map((x) => (<div key={x.device} className="flex justify-between gap-2"><span>{x.device} <span className="text-muted">{x.model ?? ""} · {x.type ?? "?"} · {x.size != null ? bytes(x.size) : "–"}</span></span>
            <span className={x.health && x.health !== "PASSED" && x.health !== "OK" ? "text-danger" : "text-muted"}>{x.health ?? "?"}{x.wearout != null ? ` · usure ${100 - x.wearout} %` : ""}</span></div>))}</div>)}</Block>
      </div>

      <Block title="Services" section={d?.services}>{(s) => (
        <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">{s.map((x) => (<div key={x.name} className="flex items-center gap-2"><span className={`size-2 rounded-full ${x.state === "running" ? "bg-ok" : "bg-muted"}`} /><span className="font-medium">{x.name}</span><span className="truncate text-xs text-muted">{x.description}</span></div>))}</div>)}</Block>

      <div className="panel space-y-2 p-4">
        <div className="flex items-center justify-between"><h3 className="font-semibold">Journal système</h3>
          <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => (logOn ? log.refetch() : setLogOn(true))}>{logOn ? "Actualiser" : "Afficher"}</Button></div>
        {log.isFetching && !log.data ? <div className="h-10 animate-pulse rounded bg-surface2" />
          : log.error ? <p className="text-sm text-muted">{(log.error as Error).message}. Le journal exige le droit <code>Sys.Syslog</code> (page « Accès »).</p>
          : log.data ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-surface2 p-2 text-xs" tabIndex={0}>{log.data.lines.map((l) => l.text).join("\n") || "Journal vide."}</pre> : null}
      </div>
    </div>
  );
}
