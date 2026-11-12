import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { bytes } from "../lib/format";
import { runTask } from "../lib/tasks";
import type { Disk } from "../lib/types/disques";
import { Button, Notice } from "./ui";

export type DiskMode = "gpt" | "wipe" | "lvm" | "lvmthin" | "directory" | "zfs";
const TITLE: Record<DiskMode, string> = { gpt: "Initialiser le disque en GPT", wipe: "Effacer le disque", lvm: "Créer un groupe LVM", lvmthin: "Créer un pool LVM-thin", directory: "Créer un répertoire", zfs: "Créer un pool ZFS" };
const RAID: [string, string, number][] = [["single", "Un seul disque", 1], ["mirror", "Miroir (2 disques ou plus)", 2], ["raid10", "RAID10 (4 disques, nombre pair)", 4], ["raidz", "RAIDZ (3 disques ou plus)", 3], ["raidz2", "RAIDZ2 (4 disques ou plus)", 4], ["raidz3", "RAIDZ3 (5 disques ou plus)", 5]];
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
        <h2 className="text-lg font-semibold">{TITLE[mode]} sur {node}</h2>
        <Notice kind="error">Action destructive : tout ce que contient {mode === "zfs" ? "ces disques" : "ce disque"} est perdu. Kaji refuse un disque utilisé (système, volume, OSD Ceph).</Notice>
        {create && <label className={label}>Nom<input value={name} onChange={(e) => setName(e.target.value)} className={input} autoComplete="off" />
          {name !== "" && !NAME.test(name) && <span className="text-danger">Lettres, chiffres, _ . - (40 caractères au plus).</span>}</label>}
        {(mode === "lvm" || mode === "lvmthin" || mode === "directory") && (
          <label className={label}>Disque<select value={device} onChange={(e) => setDevice(e.target.value)} className={input}>
            {free.map((d) => <option key={d.device} value={d.device}>{d.device} · {d.size != null ? bytes(d.size) : "?"} · {d.model ?? ""}</option>)}</select></label>)}
        {mode === "directory" && <label className={label}>Système de fichiers<select value={fs} onChange={(e) => setFs(e.target.value as "ext4" | "xfs")} className={input}><option value="ext4">ext4</option><option value="xfs">xfs</option></select></label>}
        {mode === "zfs" && <>
          <fieldset className={label}><legend>Disques</legend>{free.map((d) => (
            <label key={d.device} className="mt-1 flex gap-2 text-sm text-fg"><input type="checkbox" checked={devices.includes(d.device)} onChange={(e) => setDevices(e.target.checked ? [...devices, d.device] : devices.filter((x) => x !== d.device))} />{d.device} · {d.size != null ? bytes(d.size) : "?"}</label>))}</fieldset>
          <label className={label}>Niveau de redondance<select value={raid} onChange={(e) => setRaid(e.target.value)} className={input}>{RAID.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className={label}>Compression<select value={compression} onChange={(e) => setCompression(e.target.value)} className={input}>{["on", "off", "lz4", "zstd"].map((c) => <option key={c}>{c}</option>)}</select></label>
            <label className={label}>ashift<input type="number" min={9} max={16} value={ashift} onChange={(e) => setAshift(Number(e.target.value))} className={input} /></label>
          </div></>}
        {create && <label className="flex gap-2 text-sm"><input type="checkbox" checked={addStorage} onChange={(e) => setAddStorage(e.target.checked)} />
          <span>Ajouter comme stockage Proxmox <span className="text-muted">(défini pour tout le cluster)</span></span></label>}
        {!create && <p className="text-sm text-muted">{mode === "gpt" ? "Une nouvelle table de partitions GPT sera écrite." : "Les signatures et partitions seront effacées."} Disque : <b>{disk?.device}</b></p>}
        {(create || disk) && <label className={label}>Retape <code>{expected || (create ? "le nom" : "le disque")}</code> pour confirmer{target ? ` (cible : ${target})` : ""}
          <input value={typed} onChange={(e) => setTyped(e.target.value)} className={input} autoComplete="off" /></label>}
        {err && <Notice kind="error">{err}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Annuler</Button>
          <Button variant="danger" onClick={submit} disabled={!valid || busy}>{busy ? "En cours…" : TITLE[mode]}</Button>
        </div>
      </div>
    </div>
  );
}
