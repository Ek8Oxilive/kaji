import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest, type NodeInfo, type StorageInfo } from "../lib/api";
import { bytes } from "../lib/format";
import { LONG_TASK_SECONDS, runTask } from "../lib/tasks";
import type { BackupCompress, BackupCreateBody, BackupCreateResult, BackupDeleteResult, BackupMode, BackupRow, BackupStore, RestoreBody, RestoreResult } from "../lib/types/sauvegardes";
import { useSubmit } from "./HardwareDialogs";
import { Modal } from "./Modal";
import { PoolField } from "./PoolField";
import { useToast } from "./Toast";
import { Field } from "./ui";

import { tr, locale } from "../lib/i18n";
const enc = encodeURIComponent;
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" }) : "–");
const guestKey = (g: Pick<Guest, "node" | "type" | "vmid">) => `${g.node}/${g.type}/${g.vmid}`;
const warn = "rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn";

// ------------------------------------------------------------------------------------------------ lancer une sauvegarde

export const MODES: { id: BackupMode; label: string; hint: string }[] = [
  { id: "snapshot", get label() { return tr("Instantané"); }, get hint() { return tr("La machine reste en marche (recommandé)."); } },
  { id: "suspend", get label() { return tr("Suspension"); }, get hint() { return tr("La machine est mise en pause pendant la copie."); } },
  { id: "stop", get label() { return tr("Arrêt"); }, get hint() { return tr("La machine est ARRÊTÉE pendant la copie, puis redémarrée."); } },
];
export const COMPRESS: { id: BackupCompress; label: string }[] = [
  { id: "zstd", get label() { return tr("zstd (rapide, recommandé)"); } }, { id: "gzip", label: "gzip" }, { id: "lzo", get label() { return tr("lzo (très rapide)"); } }, { id: "none", get label() { return tr("Aucune"); } },
];

export function LaunchBackupDialog({ connId, guests, stores, initial, onClose }: { connId: number; guests: Guest[]; stores: BackupStore[]; initial?: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [key, setKey] = useState(initial ?? (guests[0] ? guestKey(guests[0]) : ""));
  const guest = guests.find((g) => guestKey(g) === key) ?? null;
  const options = stores.filter((s) => s.active && guest && (s.shared || s.node === guest.node))
    .filter((s, i, all) => all.findIndex((x) => x.storage === s.storage) === i);
  const [storage, setStorage] = useState("");
  const chosen = options.find((s) => s.storage === storage)?.storage ?? options[0]?.storage ?? "";
  const [mode, setMode] = useState<BackupMode>("snapshot");
  const [compress, setCompress] = useState<BackupCompress>("zstd");
  const [notes, setNotes] = useState("");
  const [stopOk, setStopOk] = useState(false);
  const { busy, error, run } = useSubmit(onClose);

  const notesOk = notes.length <= 200 && !/[\\\u0000-\u001f\u007f]/.test(notes);
  const ok = !!guest && !!chosen && notesOk && (mode !== "stop" || stopOk);
  const body: BackupCreateBody | null = guest && chosen
    ? { vmid: guest.vmid, storage: chosen, mode, compress, ...(notes.trim() ? { notes: notes.trim() } : {}), ...(mode === "stop" ? { confirm: true } : {}) }
    : null;

  return (
    <Modal title={tr("Lancer une sauvegarde")} subtitle={tr("Sauvegarde manuelle : elle ne supprime jamais d'anciennes sauvegardes.")}
      onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel={tr("Lancer la sauvegarde")}
      onSubmit={() => run(async () => {
        if (!guest || !body) return;
        await runTask(connId, guest.node, () => api<BackupCreateResult>(`/api/connections/${connId}/nodes/${enc(guest.node)}/backups`, { method: "POST", body }), tr("Sauvegarde"), LONG_TASK_SECONDS);
        toast("ok", tr("Sauvegarde de « {p} » terminée", { p: guest.name ?? guest.vmid }));
        await qc.invalidateQueries({ queryKey: ["backups", connId] });
      })}>
      <label className="block space-y-1.5">
        <span className="text-sm text-muted">{tr("Machine")}</span>
        <select className="field" value={key} onChange={(e) => { setKey(e.target.value); setStorage(""); }} autoFocus>
          {guests.map((g) => <option key={guestKey(g)} value={guestKey(g)}>{g.name ?? g.vmid} · #{g.vmid} · {g.type === "qemu" ? "VM" : "LXC"} · {g.node}</option>)}
        </select>
      </label>
      <label className="block space-y-1.5">
        <span className="text-sm text-muted">{tr("Stockage de destination")}</span>
        <select className="field" value={chosen} onChange={(e) => setStorage(e.target.value)} disabled={options.length === 0}>
          {options.length === 0 && <option value="">{tr("Aucun stockage de sauvegarde pour ce nœud")}</option>}
          {options.map((s) => <option key={s.storage} value={s.storage}>{s.storage}{s.shared ? tr(" (partagé)") : ""}{s.avail ? ` · ${bytes(s.avail)} libres` : ""}</option>)}
        </select>
      </label>
      <fieldset className="space-y-2" aria-label={tr("Mode de sauvegarde")}>
        {MODES.map((m) => (
          <label key={m.id} className="flex items-start gap-2 text-sm">
            <input type="radio" name="mode" className="mt-0.5 size-4 accent-[var(--accent)]" checked={mode === m.id} onChange={() => { setMode(m.id); setStopOk(false); }} />
            <span>{m.label} <span className="block text-xs text-muted">{m.hint}</span></span>
          </label>
        ))}
      </fieldset>
      {mode === "stop" && (
        <div className={`${warn} space-y-2`}>
          <p>{tr("Le mode « Arrêt »")}{" "}<strong>{tr("éteint la machine")}</strong>{" "}{tr("pendant toute la sauvegarde. Ses services seront indisponibles.")}</p>
          <label className="flex items-start gap-2"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={stopOk} onChange={(e) => setStopOk(e.target.checked)} />
            <span>{tr("Je comprends que « {p} » sera arrêtée pendant la sauvegarde.", { p: guest?.name ?? guest?.vmid })}</span></label>
        </div>
      )}
      <label className="block space-y-1.5">
        <span className="text-sm text-muted">{tr("Compression")}</span>
        <select className="field" value={compress} onChange={(e) => setCompress(e.target.value as BackupCompress)}>{COMPRESS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select>
      </label>
      <Field label={tr("Notes (facultatif)")} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={200}
        hint={notesOk ? tr("Une seule ligne. Proxmox y remplace {{guestname}}, {{vmid}}, {{node}}, {{cluster}}.") : tr("Une seule ligne, sans antislash.")} aria-invalid={!notesOk} />
      {busy && <p className="text-sm text-muted">{tr("Sauvegarde en cours, cela peut durer longtemps. Tu peux fermer cette fenêtre : elle continue en arrière-plan et la liste se mettra à jour.")}</p>}
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------------ restaurer

export function RestoreDialog({ connId, backup, nodes, guestName, onClose }: { connId: number; backup: BackupRow; nodes: NodeInfo[]; guestName: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const base = `/api/connections/${connId}`;
  const lxc = backup.type === "lxc";
  const targets = backup.shared ? nodes.filter((n) => n.status === "online") : nodes.filter((n) => n.node === backup.node);
  const [node, setNode] = useState(backup.node);
  const [storage, setStorage] = useState("");
  const [vmid, setVmid] = useState("");
  const [pool, setPool] = useState("");
  const [unique, setUnique] = useState(true);
  const { busy, error, run } = useSubmit(onClose);

  const nextId = useQuery({ queryKey: ["nextid", connId], queryFn: () => api<{ vmid: number }>(`${base}/nextid`), staleTime: 0, retry: false });
  const stores = useQuery({ queryKey: ["storages", connId, node, lxc ? "rootdir" : "images"], retry: false, staleTime: 30_000,
    queryFn: () => api<StorageInfo[]>(`${base}/nodes/${enc(node)}/storages?content=${lxc ? "rootdir" : "images"}`) });

  const idOk = vmid === "" || (Number.isInteger(Number(vmid)) && Number(vmid) >= 100);
  const ok = !!storage && idOk && !!backup.type;
  const body: RestoreBody = { volid: backup.volid, storage, unique, ...(vmid ? { vmid: Number(vmid) } : {}), ...(pool ? { pool } : {}) };
  const origin = backup.vmid != null ? `${guestName ?? "machine"} #${backup.vmid}` : "machine inconnue";

  return (
    <Modal title={tr("Restaurer vers une nouvelle machine")} subtitle={`${origin} · ${when(backup.date)} · ${backup.storage}`}
      onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel={tr("Restaurer")}
      onSubmit={() => run(async () => {
        let res: RestoreResult | undefined;
        await runTask(connId, node, async () => (res = await api<RestoreResult>(`${base}/nodes/${enc(node)}/restore`, { method: "POST", body })), tr("Restauration"), LONG_TASK_SECONDS);
        toast("ok", tr("Machine #{p} créée à partir de la sauvegarde (arrêtée)", { p: res?.vmid ?? "?" }));
        await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] });
      })}>
      <p className="rounded-xl border border-ok/40 bg-ok/10 p-3 text-sm text-ok">{tr("La restauration crée")}{" "}{lxc ? <>{tr("un")}{" "}<strong>{tr("nouveau conteneur")}</strong>{tr(", qui reste")}{" "}<strong>{tr("arrêté")}</strong></> : <>{tr("une")}{" "}<strong>{tr("nouvelle machine")}</strong>{tr(", qui reste")}{" "}<strong>{tr("arrêtée")}</strong></>}{tr(". Elle ne remplace jamais une machine existante : un identifiant déjà utilisé est refusé.")}</p>
      <div className="grid gap-4 sm:grid-cols-[1fr_9rem]">
        {targets.length > 1
          ? <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Nœud")}</span>
              <select className="field" value={node} onChange={(e) => { setNode(e.target.value); setStorage(""); }}>{targets.map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}</select></label>
          : <div className="space-y-1.5"><span className="text-sm text-muted">{tr("Nœud")}</span><p className="field !bg-transparent">{backup.node}</p></div>}
        <Field label={tr("Identifiant")} type="number" min={100} value={vmid} onChange={(e) => setVmid(e.target.value)} placeholder={nextId.data ? String(nextId.data.vmid) : ""}
          hint={nextId.data ? tr("Vide : le prochain libre ({vmid})", { vmid: nextId.data.vmid }) : tr("Vide : le prochain libre")} aria-invalid={!idOk} />
      </div>
      <label className="block space-y-1.5">
        <span className="text-sm text-muted">{tr("Stockage de destination des disques")}</span>
        <select className="field" value={storage} onChange={(e) => setStorage(e.target.value)} autoFocus>
          <option value="">{tr("Choisir un stockage…")}</option>
          {stores.data?.map((s) => <option key={s.storage} value={s.storage} disabled={!s.active}>{s.storage}{s.type ? ` (${s.type})` : ""}{s.avail ? ` · ${bytes(s.avail)} libres` : ""}</option>)}
        </select>
      </label>
      <PoolField connId={connId} value={pool} onChange={setPool} />
      <p className="-mt-2 text-xs text-muted">{tr("Selon les droits du token, Proxmox peut n'autoriser la création que dans certains pools.")}</p>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={unique} onChange={(e) => setUnique(e.target.checked)} />
        <span>{tr("Nouvelles adresses MAC (recommandé)")}<span className="block text-xs text-muted">{tr("Sans cela, la machine restaurée garde les adresses de l'originale : doublon sur le réseau tant qu'elle existe.")}</span></span></label>
      {busy && <p className="text-sm text-muted">{tr("Restauration en cours, cela peut durer longtemps. Tu peux fermer cette fenêtre : elle continue en arrière-plan.")}</p>}
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------------ supprimer

export function DeleteBackupDialog({ connId, backup, onClose }: { connId: number; backup: BackupRow; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const { busy, error, run } = useSubmit(onClose);
  const url = `/api/connections/${connId}/nodes/${enc(backup.node)}/storage/${enc(backup.storage)}/backups/${enc(backup.name)}?confirm=true&name=${enc(typed)}`;

  return (
    <Modal title={tr("Supprimer cette sauvegarde ?")} subtitle={backup.storage} danger onClose={onClose} busy={busy} error={error}
      canSubmit={typed === backup.name} submitLabel={tr("Supprimer définitivement")}
      onSubmit={() => run(async () => {
        const r = await api<BackupDeleteResult>(url, { method: "DELETE" });
        if (r.upid) await runTask(connId, backup.node, async () => ({ upid: r.upid as string }), tr("Suppression"), 600);
        toast("ok", tr("Sauvegarde supprimée"));
        await qc.invalidateQueries({ queryKey: ["backups", connId] });
      })}>
      <p className="text-sm text-muted">{tr("Le fichier est détruit sur")}{" "}<strong className="text-fg">{backup.storage}</strong>. <strong className="text-fg">{tr("Cette action est irréversible")}</strong>{" "}{tr(": il n'y a pas de corbeille.")}</p>
      <Field label={tr("Retape le nom exact du fichier pour confirmer")} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} autoFocus
        hint={backup.name} aria-invalid={typed !== "" && typed !== backup.name} />
    </Modal>
  );
}
