import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { bytes } from "../lib/format";
import { runTask } from "../lib/tasks";
import type { Disk } from "../lib/types/disques";
import { Button, Notice } from "./ui";

import { tr, T } from "../lib/i18n";
export type DiskMode = "gpt" | "wipe" | "lvm" | "lvmthin" | "directory" | "zfs";
const TITLE: Record<DiskMode, string> = { get gpt() { return tr("Initialiser le disque en GPT"); }, get wipe() { return tr("Effacer le disque"); }, get lvm() { return tr("Créer un groupe LVM"); }, get lvmthin() { return tr("Créer un pool LVM-thin"); }, get directory() { return tr("Créer un répertoire"); }, get zfs() { return tr("Créer un pool ZFS"); } };
const RAID: [string, string, number][] = [["single", T("Un seul disque"), 1], ["mirror", T("Miroir (2 disques ou plus)"), 2], ["raid10", "RAID10 (4 disques, nombre pair)", 4], ["raidz", T("RAIDZ (3 disques ou plus)"), 3], ["raidz2", T("RAIDZ2 (4 disques ou plus)"), 4], ["raidz3", T("RAIDZ3 (5 disques ou plus)"), 5]];
const NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$/;

/** Boîte de dialogue des actions destructives sur les disques. Le serveur relit l'état des disques et décide : ici, seulement la saisie. */
export function DiskWriteDialog({ connId, node, mode, free, disk, onClose }: { connId: number; node: string; mode: DiskMode; free: Disk[]; disk?: Disk; onClose: () => void }) {
  const qc = useQueryClient();
  const create = mode !== "gpt" && mode !== "wipe";
  const [name, setName] = useState("");
  const [device, setDevice] = useState(disk?.device ?? free[0]?.device ?? "");
  const [devices, setDevices] = useState<string[]>(disk ? [disk.device] : []);
  const [fs, setFs] = useState<"ext4" | "xfs">("ext4");
  const [raid, setRaid] = useState("single");
  const [compression, setCompression] = useState("on");
  const [ashift, setAshift] = useState(12);
  const [addStorage, setAddStorage] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const expected = create ? name : (disk?.device ?? "");
  const target = mode === "zfs" ? devices.join(", ") : create ? device : disk?.device;
  const valid = (!create || NAME.test(name)) && (mode === "zfs" ? devices.length > 0 : !!(create ? device : disk)) && typed === expected && expected !== "";
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/disks`;

  const submit = async () => {
    setBusy(true); setErr(null);
    const common = { confirm: true, type_name: typed };
    const body = mode === "gpt" || mode === "wipe" ? { ...common, disk: disk?.device }
      : mode === "zfs" ? { ...common, name, devices, raidlevel: raid, compression, ashift, add_storage: addStorage }
      : mode === "directory" ? { ...common, name, device, filesystem: fs, add_storage: addStorage }
      : { ...common, name, device, add_storage: addStorage };
    const path = mode === "gpt" ? "initgpt" : mode;
    try {
      await runTask(connId, node, () => api(`${base}/${path}`, { method: "POST", body }), TITLE[mode], 600);
      qc.invalidateQueries({ queryKey: ["node-disks", connId, node] });
      qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
      onClose();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  const label = "block text-xs text-muted";
  const input = "mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg";
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4" onClick={busy ? undefined : onClose}>
      <div role="dialog" aria-modal="true" aria-label={TITLE[mode]} className="panel rise max-h-[90vh] w-full max-w-md space-y-4 overflow-auto p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold">{tr("{p} sur {node}", { p: TITLE[mode], node })}</h2>
        <Notice kind="error">{tr("Action destructive : tout ce que contient {p} est perdu. Kaji refuse un disque utilisé (système, volume, OSD Ceph).", { p: mode === "zfs" ? "ces disques" : tr("ce disque") })}</Notice>
        {create && <label className={label}>{tr("Nom")}<input value={name} onChange={(e) => setName(e.target.value)} className={input} autoComplete="off" />
          {name !== "" && !NAME.test(name) && <span className="text-danger">{tr("Lettres, chiffres, _ . - (40 caractères au plus).")}</span>}</label>}
        {(mode === "lvm" || mode === "lvmthin" || mode === "directory") && (
          <label className={label}>{tr("Disque")}<select value={device} onChange={(e) => setDevice(e.target.value)} className={input}>
            {free.map((d) => <option key={d.device} value={d.device}>{d.device} · {d.size != null ? bytes(d.size) : "?"} · {d.model ?? ""}</option>)}</select></label>)}
        {mode === "directory" && <label className={label}>{tr("Système de fichiers")}<select value={fs} onChange={(e) => setFs(e.target.value as "ext4" | "xfs")} className={input}><option value="ext4">{tr("ext4")}</option><option value="xfs">{tr("xfs")}</option></select></label>}
        {mode === "zfs" && <>
          <fieldset className={label}><legend>{tr("Disques")}</legend>{free.map((d) => (
            <label key={d.device} className="mt-1 flex gap-2 text-sm text-fg"><input type="checkbox" checked={devices.includes(d.device)} onChange={(e) => setDevices(e.target.checked ? [...devices, d.device] : devices.filter((x) => x !== d.device))} />{d.device} · {d.size != null ? bytes(d.size) : "?"}</label>))}</fieldset>
          <label className={label}>{tr("Niveau de redondance")}<select value={raid} onChange={(e) => setRaid(e.target.value)} className={input}>{RAID.map(([v, l]) => <option key={v} value={v}>{tr(l)}</option>)}</select></label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className={label}>{tr("Compression")}<select value={compression} onChange={(e) => setCompression(e.target.value)} className={input}>{["on", "off", "lz4", "zstd"].map((c) => <option key={c}>{c}</option>)}</select></label>
            <label className={label}>{tr("ashift")}<input type="number" min={9} max={16} value={ashift} onChange={(e) => setAshift(Number(e.target.value))} className={input} /></label>
          </div></>}
        {create && <label className="flex gap-2 text-sm"><input type="checkbox" checked={addStorage} onChange={(e) => setAddStorage(e.target.checked)} />
          <span>{tr("Ajouter comme stockage Proxmox")}{" "}<span className="text-muted">{tr("(défini pour tout le cluster)")}</span></span></label>}
        {!create && <p className="text-sm text-muted">{tr("{p} Disque :", { p: mode === "gpt" ? tr("Une nouvelle table de partitions GPT sera écrite.") : tr("Les signatures et partitions seront effacées.") })}{" "}<b>{disk?.device}</b></p>}
        {(create || disk) && <label className={label}>{tr("Retape")}{" "}<code>{expected || (create ? tr("le nom") : tr("le disque"))}</code>{" "}{tr("pour confirmer{p}", { p: target ? ` (cible : ${target})` : "" })}<input value={typed} onChange={(e) => setTyped(e.target.value)} className={input} autoComplete="off" /></label>}
        {err && <Notice kind="error">{err}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>{tr("Annuler")}</Button>
          <Button variant="danger" onClick={submit} disabled={!valid || busy}>{busy ? tr("En cours…") : TITLE[mode]}</Button>
        </div>
      </div>
    </div>
  );
}
