import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { bytes, pct } from "../lib/format";
import type { Disk, NodeDisks as Disks, Smart } from "../lib/types/disques";
import type { Section } from "../lib/types/systeme";
import { Gauge } from "./Gauge";
import { DiskDeleteDialog, type VolumeKind } from "./DiskDeleteDialog";
import { DiskWriteDialog, type DiskMode } from "./DiskWriteDialog";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
function Block<T>({ title, section, children }: { title: string; section: Section<T> | undefined; children: (d: T) => React.ReactNode }) {
  return (
    <div className="panel space-y-2 p-4">
      <h3 className="font-semibold">{title}</h3>
      {!section ? <div className="h-10 animate-pulse rounded bg-surface2" />
        : section.state === "forbidden" ? <p className="text-sm text-muted">{tr("Droit manquant pour le token de Kaji. La page « Accès » donne la commande à copier.")}</p>
        : section.state === "error" || !section.data ? <p className="text-sm text-danger">{tr("Lecture impossible.")}</p>
        : children(section.data)}
    </div>
  );
}

const ok = (h: string | null) => !h || h === "PASSED" || h === "OK";
/** Indication d'affichage seulement : le serveur relit l'état chez Proxmox et décide. */
const stateOf = (d: Disk): "free" | "leftover" | "busy" =>
  d.osd ? "busy" : !d.used && d.partitions.length === 0 ? "free" : d.used === "partitions" && d.partitions.length > 0 && d.partitions.every((p) => !p.used) ? "leftover" : "busy";

function SmartPanel({ base, device }: { base: string; device: string }) {
  const q = useQuery({ queryKey: ["node-smart", base, device], staleTime: 30_000, queryFn: () => api<Smart>(`${base}/smart?disk=${encodeURIComponent(device)}`) });
  if (q.isLoading) return <div className="h-12 animate-pulse rounded bg-surface2" />;
  if (q.error || !q.data) return <p className="text-sm text-danger">{(q.error as Error | null)?.message ?? "SMART indisponible"}</p>;
  const s = q.data;
  return (
    <div className="space-y-2 text-sm">
      <p>{tr("Santé :")}{" "}<b className={ok(s.health) ? "text-ok" : "text-danger"}>{s.health ?? tr("inconnue")}</b>{s.wearout != null && <span className="text-muted">{" "}{tr("· usure {p} %", { p: 100 - s.wearout })}</span>}</p>
      {s.attributes.length > 0 && (
        <div className="max-h-64 overflow-auto"><table className="w-full text-xs"><thead><tr className="text-left text-muted"><th className="pr-2 font-normal">{tr("Attribut")}</th><th className="pr-2 font-normal">{tr("Valeur")}</th><th className="pr-2 font-normal">{tr("Pire")}</th><th className="pr-2 font-normal">{tr("Seuil")}</th><th className="font-normal">{tr("Brut")}</th></tr></thead>
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
  const [dlg, setDlg] = useState<{ mode: DiskMode; disk?: Disk } | null>(null);
  const [del, setDel] = useState<{ kind: VolumeKind; name: string; vg?: string } | null>(null);
  const rm = (kind: VolumeKind, name: string, vg?: string) => <Button variant="danger" className="!px-2 !py-1 text-xs" onClick={() => setDel({ kind, name, vg })}>{tr("Supprimer")}</Button>;
  if (!online) return <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{tr("Nœud hors ligne : disques indisponibles.")}</div>;
  if (q.error) return <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>{tr("réessayer")}</button></Notice>;
  const d = q.data;
  return (
    <div className="space-y-3">
      <Block title={tr("Disques")} section={d?.disks}>{(disks) => disks.length === 0 ? <p className="text-sm text-muted">{tr("Aucun disque.")}</p> : (
        <div className="space-y-3 text-sm">{disks.map((x) => (
          <div key={x.device} className="space-y-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span><b>{x.device}</b> <span className="text-muted">{x.model ?? ""} · {x.type ?? "?"} · {x.size != null ? bytes(x.size) : "–"} · {x.gpt ? "GPT" : tr("sans GPT")}</span></span>
              <span className="flex items-center gap-2"><span className={ok(x.health) ? "text-muted" : "text-danger"}>{x.health ?? "?"}{x.wearout != null ? ` · usure ${100 - x.wearout} %` : ""}</span>
                <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setSmart(smart === x.device ? null : x.device)}>{smart === x.device ? "Masquer SMART" : "SMART"}</Button></span>
            </div>
            {stateOf(x) === "busy" ? <p className="ml-4 text-xs text-muted">{tr("Utilisé : Kaji n'y touche pas.")}</p>
              : <div className="ml-4 flex flex-wrap gap-1">
                {stateOf(x) === "free" && <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setDlg({ mode: "gpt", disk: x })}>{tr("Initialiser GPT")}</Button>}
                <Button variant="danger" className="!px-2 !py-1 text-xs" onClick={() => setDlg({ mode: "wipe", disk: x })}>{tr("Effacer")}</Button>
                {stateOf(x) === "free" && (["lvm", "lvmthin", "directory"] as const).map((m) => (
                  <Button key={m} variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setDlg({ mode: m, disk: x })}>{m === "lvm" ? tr("Créer LVM") : m === "lvmthin" ? tr("Créer LVM-thin") : tr("Créer répertoire")}</Button>))}
              </div>}
            {x.partitions.length > 0 && <ul className="ml-4 text-xs text-muted">{x.partitions.map((p) => <li key={p.device}>{p.device} · {p.size != null ? bytes(p.size) : "–"} · {p.used ?? tr("inutilisée")}</li>)}</ul>}
            {smart === x.device && <div className="rounded-lg border border-line p-3"><SmartPanel base={base} device={x.device} /></div>}
          </div>))}</div>)}</Block>
      <div className="grid gap-3 sm:grid-cols-2">
        <Block title={tr("Groupes LVM")} section={d?.lvm}>{(v) => v.length === 0 ? <p className="text-sm text-muted">{tr("Aucun groupe.")}</p> : (
          <div className="space-y-2">{v.map((g) => (<div key={g.name} className="space-y-1"><Gauge label={tr("{name} · {p} volumes", { name: g.name, p: g.volumes ?? "?" })} value={g.size && g.free != null ? pct(g.size - g.free, g.size) : 0} detail={g.size ? `${bytes(g.size - (g.free ?? 0))} / ${bytes(g.size)}` : "–"} />{g.volumes === 0 && rm("lvm", g.name)}</div>))}</div>)}</Block>
        <Block title={tr("Pools LVM-thin")} section={d?.lvmthin}>{(v) => v.length === 0 ? <p className="text-sm text-muted">{tr("Aucun pool.")}</p> : (
          <div className="space-y-2">{v.map((p) => (<div key={`${p.vg}/${p.name}`} className="space-y-1"><Gauge label={`${p.vg ?? "?"}/${p.name}`} value={p.size && p.used != null ? pct(p.used, p.size) : 0} detail={p.size ? `${bytes(p.used ?? 0)} / ${bytes(p.size)}` : "–"} />{p.used === 0 && p.vg && rm("lvmthin", p.name, p.vg)}</div>))}</div>)}</Block>
        <Block title={tr("Répertoires")} section={d?.directory}>{(v) => v.length === 0 ? <p className="text-sm text-muted">{tr("Aucun répertoire monté par Proxmox.")}</p> : (
          <ul className="space-y-1 text-sm">{v.map((r) => <li key={r.path} className="flex flex-wrap items-center justify-between gap-2"><span>{r.path} <span className="text-muted">{r.device} · {r.type}</span></span>{rm("directory", r.path.replace(/\/+$/, "").split("/").pop() ?? "")}</li>)}</ul>)}</Block>
        <Block title={tr("ZFS")} section={d?.zfs}>{(v) => v.length === 0 ? <p className="text-sm text-muted">{tr("Aucun pool ZFS.")}</p> : (
          <div className="space-y-2">{v.map((z) => (<div key={z.name} className="space-y-1"><Gauge label={`${z.name} · ${z.health ?? "?"}`} value={z.size && z.alloc != null ? pct(z.alloc, z.size) : 0} detail={z.size ? `${bytes(z.alloc ?? 0)} / ${bytes(z.size)}` : "–"} />{rm("zfs", z.name)}</div>))}</div>)}</Block>
      </div>
      {d?.disks.data && d.disks.data.some((x) => stateOf(x) === "free") && (
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setDlg({ mode: "zfs" })}>{tr("Créer un pool ZFS…")}</Button>)}
      <p className="text-xs text-muted">{tr("Kaji ne supprime qu'un volume vide (le bouton « Supprimer » n'apparaît que sur un groupe LVM sans volume ou un pool LVM-thin vide ; le serveur revérifie tout).")}</p>
      {del && <DiskDeleteDialog connId={connId} node={node} kind={del.kind} name={del.name} vg={del.vg} onClose={() => setDel(null)} />}
      {dlg && <DiskWriteDialog connId={connId} node={node} mode={dlg.mode} disk={dlg.disk} free={(d?.disks.data ?? []).filter((x) => stateOf(x) === "free")} onClose={() => setDlg(null)} />}
    </div>
  );
}
