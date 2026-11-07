import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { bytes, pct } from "../lib/format";
import type { NodeDisks as Disks, Smart } from "../lib/types/disques";
import type { Section } from "../lib/types/systeme";
import { Gauge } from "./Gauge";
import { Button, Notice } from "./ui";

function Block<T>({ title, section, children }: { title: string; section: Section<T> | undefined; children: (d: T) => React.ReactNode }) {
  return (
    <div className="panel space-y-2 p-4">
      <h3 className="font-semibold">{title}</h3>
      {!section ? <div className="h-10 animate-pulse rounded bg-surface2" />
        : section.state === "forbidden" ? <p className="text-sm text-muted">Droit manquant pour le token de Kaji. La page « Accès » donne la commande à copier.</p>
        : section.state === "error" || !section.data ? <p className="text-sm text-danger">Lecture impossible.</p>
        : children(section.data)}
    </div>
  );
}

const ok = (h: string | null) => !h || h === "PASSED" || h === "OK";

function SmartPanel({ base, device }: { base: string; device: string }) {
  const q = useQuery({ queryKey: ["node-smart", base, device], staleTime: 30_000, queryFn: () => api<Smart>(`${base}/smart?disk=${encodeURIComponent(device)}`) });
  if (q.isLoading) return <div className="h-12 animate-pulse rounded bg-surface2" />;
  if (q.error || !q.data) return <p className="text-sm text-danger">{(q.error as Error | null)?.message ?? "SMART indisponible"}</p>;
  const s = q.data;
  return (
    <div className="space-y-2 text-sm">
      <p>Santé : <b className={ok(s.health) ? "text-ok" : "text-danger"}>{s.health ?? "inconnue"}</b>{s.wearout != null && <span className="text-muted"> · usure {100 - s.wearout} %</span>}</p>
      {s.attributes.length > 0 && (
        <div className="max-h-64 overflow-auto"><table className="w-full text-xs"><thead><tr className="text-left text-muted"><th className="pr-2 font-normal">Attribut</th><th className="pr-2 font-normal">Valeur</th><th className="pr-2 font-normal">Pire</th><th className="pr-2 font-normal">Seuil</th><th className="font-normal">Brut</th></tr></thead>
          <tbody>{s.attributes.map((a) => (<tr key={`${a.id}-${a.name}`} className={`border-t border-line/60 ${a.failing ? "text-danger" : ""}`}><td className="pr-2">{a.name}</td><td className="pr-2 tabular-nums">{a.value ?? "–"}</td><td className="pr-2 tabular-nums">{a.worst ?? "–"}</td><td className="pr-2 tabular-nums">{a.threshold ?? "–"}</td><td className="tabular-nums">{a.raw ?? "–"}</td></tr>))}</tbody></table></div>)}
      {s.text && <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-surface2 p-2 text-xs" tabIndex={0}>{s.text}</pre>}
    </div>
  );
}

/** Disques, partitions, LVM, LVM-thin, répertoires, ZFS et SMART d'un nœud. Lecture seule. */
export function NodeDisks({ connId, node, online }: { connId: number; node: string; online: boolean }) {
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/disks`;
  const q = useQuery({ queryKey: ["node-disks", connId, node], enabled: online, staleTime: 30_000, queryFn: () => api<Disks>(base) });
  const [smart, setSmart] = useState<string | null>(null);
  if (!online) return <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Nœud hors ligne : disques indisponibles.</div>;
  if (q.error) return <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>réessayer</button></Notice>;
  const d = q.data;
  return (
    <div className="space-y-3">
      <Block title="Disques" section={d?.disks}>{(disks) => disks.length === 0 ? <p className="text-sm text-muted">Aucun disque.</p> : (
        <div className="space-y-3 text-sm">{disks.map((x) => (
          <div key={x.device} className="space-y-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span><b>{x.device}</b> <span className="text-muted">{x.model ?? ""} · {x.type ?? "?"} · {x.size != null ? bytes(x.size) : "–"} · {x.gpt ? "GPT" : "sans GPT"}</span></span>
              <span className="flex items-center gap-2"><span className={ok(x.health) ? "text-muted" : "text-danger"}>{x.health ?? "?"}{x.wearout != null ? ` · usure ${100 - x.wearout} %` : ""}</span>
                <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setSmart(smart === x.device ? null : x.device)}>{smart === x.device ? "Masquer SMART" : "SMART"}</Button></span>
            </div>
            {x.partitions.length > 0 && <ul className="ml-4 text-xs text-muted">{x.partitions.map((p) => <li key={p.device}>{p.device} · {p.size != null ? bytes(p.size) : "–"} · {p.used ?? "inutilisée"}</li>)}</ul>}
            {smart === x.device && <div className="rounded-lg border border-line p-3"><SmartPanel base={base} device={x.device} /></div>}
          </div>))}</div>)}</Block>
      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Groupes LVM" section={d?.lvm}>{(v) => v.length === 0 ? <p className="text-sm text-muted">Aucun groupe.</p> : (
          <div className="space-y-2">{v.map((g) => (<Gauge key={g.name} label={`${g.name} · ${g.volumes ?? "?"} volumes`} value={g.size && g.free != null ? pct(g.size - g.free, g.size) : 0} detail={g.size ? `${bytes(g.size - (g.free ?? 0))} / ${bytes(g.size)}` : "–"} />))}</div>)}</Block>
        <Block title="Pools LVM-thin" section={d?.lvmthin}>{(v) => v.length === 0 ? <p className="text-sm text-muted">Aucun pool.</p> : (
          <div className="space-y-2">{v.map((p) => (<Gauge key={`${p.vg}/${p.name}`} label={`${p.vg ?? "?"}/${p.name}`} value={p.size && p.used != null ? pct(p.used, p.size) : 0} detail={p.size ? `${bytes(p.used ?? 0)} / ${bytes(p.size)}` : "–"} />))}</div>)}</Block>
        <Block title="Répertoires" section={d?.directory}>{(v) => v.length === 0 ? <p className="text-sm text-muted">Aucun répertoire monté par Proxmox.</p> : (
          <ul className="space-y-1 text-sm">{v.map((r) => <li key={r.path}>{r.path} <span className="text-muted">{r.device} · {r.type}</span></li>)}</ul>)}</Block>
        <Block title="ZFS" section={d?.zfs}>{(v) => v.length === 0 ? <p className="text-sm text-muted">Aucun pool ZFS.</p> : (
          <div className="space-y-2">{v.map((z) => (<Gauge key={z.name} label={`${z.name} · ${z.health ?? "?"}`} value={z.size && z.alloc != null ? pct(z.alloc, z.size) : 0} detail={z.size ? `${bytes(z.alloc ?? 0)} / ${bytes(z.size)}` : "–"} />))}</div>)}</Block>
      </div>
      <p className="text-xs text-muted">Lecture seule. Initialiser, effacer ou créer un volume se fait pour l'instant dans Proxmox.</p>
    </div>
  );
}
