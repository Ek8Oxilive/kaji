import { useMemo, useState } from "react";
import { DeleteBackupDialog, LaunchBackupDialog, RestoreDialog } from "../components/BackupDialogs";
import { JobsPanel } from "../components/BackupJobs";
import { Button, Notice } from "../components/ui";
import { useActiveConnection } from "../lib/connection";
import { bytes } from "../lib/format";
import type { BackupRow } from "../lib/types/sauvegardes";
import { useBackupData } from "../lib/useBackups";

import { tr, locale } from "../lib/i18n";
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" }) : "–");
const rowKey = (b: BackupRow) => `${b.node}/${b.storage}/${b.volid}`;

export function Sauvegardes({ onGoConnections }: { onGoConnections: () => void }) {
  const { conns, active, id } = useActiveConnection();
  const { nodes, guests, backups } = useBackupData(id);
  const [q, setQ] = useState(""), [machine, setMachine] = useState("all"), [storage, setStorage] = useState("all"), [kind, setKind] = useState("all");
  const [tab, setTab] = useState<"list" | "jobs">("list");
  const [launch, setLaunch] = useState(false);
  const [restore, setRestore] = useState<BackupRow | null>(null);
  const [del, setDel] = useState<BackupRow | null>(null);

  const names = useMemo(() => new Map((guests.data ?? []).map((g) => [g.vmid, g.name])), [guests.data]);
  const rows = backups.data?.rows ?? [];
  const stores = backups.data?.stores ?? [];
  const machines = useMemo(() => [...new Set(rows.map((r) => r.vmid).filter((v): v is number => v != null))].sort((a, b) => a - b), [rows]);
  const storageNames = useMemo(() => [...new Set(rows.map((r) => r.storage))].sort(), [rows]);
  const visible = rows.filter((r) => (machine === "all" || String(r.vmid) === machine) && (storage === "all" || r.storage === storage) && (kind === "all" || r.type === kind)
    && (!q || `${r.name} ${r.vmid ?? ""} ${names.get(r.vmid ?? -1) ?? ""} ${r.notes ?? ""}`.toLowerCase().includes(q.toLowerCase())));
  const launchable = (guests.data ?? []).filter((g) => !g.template);
  const sel = "field !w-auto !py-1.5 text-sm";

  if (conns.isLoading) return <div className="mx-auto max-w-6xl space-y-3">{[0, 1, 2].map((i) => <div key={i} className="panel h-14 animate-pulse" />)}</div>;
  if (!active || id === null) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1>
        <p className="text-muted">{tr("Ajoute ton cluster Proxmox pour voir ses sauvegardes.")}</p>
        <Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button>
      </div>
    </div>
  );

  const loading = nodes.isLoading || backups.isLoading;
  const error = nodes.error ?? backups.error;
  const refetch = () => { nodes.refetch(); guests.refetch(); backups.refetch(); };

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{tr("Sauvegardes")}</h1>
          <p className="text-muted">{active.name} · {active.host}</p>
        </div>
        {tab === "list" && (
          <div className="flex items-center gap-3">
            <Button onClick={() => setLaunch(true)} disabled={loading || launchable.length === 0 || stores.length === 0} className="!px-3 !py-1.5"
              title={stores.length === 0 && !loading ? tr("Aucun stockage n'accepte les sauvegardes") : undefined}>{tr("Lancer une sauvegarde")}</Button>
            <Button variant="ghost" onClick={refetch} disabled={backups.isFetching} className="!px-3 !py-1.5">
              <span className={backups.isFetching ? "inline-block animate-spin" : ""}>↻</span>{" "}{tr("Actualiser")}</Button>
          </div>
        )}
      </header>

      <div className="flex gap-2" role="tablist" aria-label={tr("Affichage")}>
        {([["list", tr("Sauvegardes")], ["jobs", tr("Planifiées")]] as const).map(([t, label]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`rounded-full border px-4 py-1.5 text-sm transition ${tab === t ? "border-accent bg-accent text-accentfg" : "border-line bg-surface2 text-muted hover:text-fg"}`}>{label}</button>
        ))}
      </div>

      {tab === "jobs" && <JobsPanel connId={id} nodes={nodes.data ?? []} guests={launchable} stores={stores} />}
      {tab === "list" && <>

      {error && <Notice kind="error">{(error as Error).message} — <button className="underline" onClick={refetch}>{tr("réessayer")}</button></Notice>}
      {backups.data?.failed.map((f) => <Notice key={`${f.node}/${f.storage}`} kind="error">{tr("Stockage « {storage} » (nœud {node}) illisible : {message}. Les autres stockages sont affichés.", { storage: f.storage, node: f.node, message: f.message })}</Notice>)}

      <section className="space-y-3" aria-label={tr("Liste des sauvegardes")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{tr("Sauvegardes")}{" "}<span className="text-sm font-normal text-muted">({visible.length}{visible.length !== rows.length ? ` sur ${rows.length}` : ""}{rows.length ? ` · ${bytes(visible.reduce((s, r) => s + (r.size ?? 0), 0))}` : ""})</span></h2>
          <div className="flex flex-wrap gap-2">
            <input className={`${sel} min-w-44`} placeholder={tr("Rechercher…")} aria-label={tr("Rechercher une sauvegarde")} value={q} onChange={(e) => setQ(e.target.value)} />
            <select className={sel} aria-label={tr("Machine")} value={machine} onChange={(e) => setMachine(e.target.value)}>
              <option value="all">{tr("Toutes les machines")}</option>
              {machines.map((v) => <option key={v} value={v}>#{v}{names.get(v) ? ` · ${names.get(v)}` : tr(" · absente du cluster")}</option>)}
            </select>
            <select className={sel} aria-label={tr("Stockage")} value={storage} onChange={(e) => setStorage(e.target.value)}>
              <option value="all">{tr("Tous les stockages")}</option>{storageNames.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select className={sel} aria-label={tr("Type")} value={kind} onChange={(e) => setKind(e.target.value)}><option value="all">{tr("VM + LXC")}</option><option value="qemu">{tr("VM")}</option><option value="lxc">{tr("LXC")}</option></select>
          </div>
        </div>

        {loading ? <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="panel h-12 animate-pulse" />)}</div>
          : visible.length === 0 ? <div className="panel p-6 text-muted">{rows.length === 0 ? tr("Aucune sauvegarde sur les stockages du cluster.") : tr("Aucune sauvegarde ne correspond aux filtres.")}</div>
          : (
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[52rem] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    <th scope="col" className="px-4 py-2 font-normal">{tr("Machine")}</th><th scope="col" className="px-4 py-2 font-normal">{tr("Date")}</th>
                    <th scope="col" className="px-4 py-2 font-normal">{tr("Stockage")}</th><th scope="col" className="px-4 py-2 font-normal">{tr("Format")}</th>
                    <th scope="col" className="px-4 py-2 text-right font-normal">{tr("Taille")}</th><th scope="col" className="px-4 py-2 font-normal">{tr("Notes")}</th>
                    <th scope="col" className="px-4 py-2 text-right font-normal"><span className="sr-only">{tr("Actions")}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((b) => {
                    const name = b.vmid != null ? names.get(b.vmid) : null;
                    return (
                      <tr key={rowKey(b)} className="border-b border-line/60 last:border-0">
                        <td className="px-4 py-2">
                          <span className="block" title={b.name}>{b.vmid != null ? (name ?? tr("Machine absente")) : "–"}</span>
                          <span className="block text-xs text-muted">{b.vmid != null ? `#${b.vmid} · ` : ""}{b.type === "qemu" ? "VM" : b.type === "lxc" ? "LXC" : "type inconnu"}</span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-2">{when(b.date)}</td>
                        <td className="px-4 py-2 text-muted">{b.storage}<span className="block text-xs">{b.shared ? tr("partagé") : b.node}</span></td>
                        <td className="px-4 py-2 text-muted">{b.format ?? "–"}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{bytes(b.size)}</td>
                        <td className="max-w-xs truncate px-4 py-2 text-muted" title={b.notes ?? undefined}>{b.protected ? tr("Protégée") : ""}{b.protected && b.notes ? " · " : ""}{b.notes}</td>
                        <td className="whitespace-nowrap px-4 py-2 text-right">
                          <div className="flex justify-end gap-2">
                            <Button variant="ghost" className="!px-3 !py-1 text-xs" onClick={() => setRestore(b)} disabled={!b.type}
                              title={b.type ? tr("Restaurer vers une nouvelle machine") : tr("Forme de sauvegarde non reconnue : restauration impossible ici")}>{tr("Restaurer")}</Button>
                            <Button variant="danger" className="!px-3 !py-1 text-xs" onClick={() => setDel(b)} disabled={!b.deletable}
                              title={b.deletable ? tr("Supprimer définitivement") : b.protected ? tr("Sauvegarde protégée : retire d'abord la protection dans Proxmox") : tr("Forme de sauvegarde non reconnue : suppression impossible ici")}>{tr("Supprimer")}</Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        <p className="text-xs text-muted">{tr("Un stockage partagé n'est lu qu'une fois. Les stockages hors ligne ou inactifs ne sont pas affichés.")}</p>
      </section>
      </>}

      {launch && <LaunchBackupDialog connId={id} guests={launchable} stores={stores} onClose={() => setLaunch(false)} />}
      {restore && <RestoreDialog connId={id} backup={restore} nodes={nodes.data ?? []} guestName={restore.vmid != null ? names.get(restore.vmid) ?? null : null} onClose={() => setRestore(null)} />}
      {del && <DeleteBackupDialog connId={id} backup={del} onClose={() => setDel(null)} />}
    </div>
  );
}
