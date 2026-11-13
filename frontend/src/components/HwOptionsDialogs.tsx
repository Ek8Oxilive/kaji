import { useState } from "react";
import { api, ApiError, type HwConfig, type HwDisk } from "../lib/api";
import { tr } from "../lib/i18n";
import type { CpuOptionsBody, DiskOptionsBody, NetOptionsBody, NetX } from "../lib/types/hwopts";
import { Modal } from "./Modal";
import { Field } from "./ui";

/**
 * Options fines d'un disque, d'une carte réseau et du CPU (lot #377). Chaque champ part de la valeur actuelle et SEULS les champs modifiés sont envoyés ;
 * « Défaut de Proxmox » retire l'option. Le serveur décide des réglages risqués : il répond 400, la fenêtre demande alors une case « J'accepte ».
 */
function useOptionsSubmit(onClose: () => void, onDone: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [risk, setRisk] = useState<string | null>(null);
  const [accept, setAccept] = useState(false);
  const run = async (send: (confirm: boolean) => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await send(accept); await onDone(); onClose(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        const text = e.message.includes(") : ") ? e.message.split(") : ").slice(1).join(") : ") : e.message;
        setRisk(text.split(" ; ").map((x) => tr(x)).join(" ; ")); setAccept(false);     // chaque risque est un texte fixe du serveur (traduit s'il figure dans en-server.json)
      }
      else setError((e as Error).message);
    } finally { setBusy(false); }
  };
  const box = risk && (
    <label className="flex gap-2 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
      <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
      <span>{tr("Risque : {risk}. J'accepte.", { risk })}</span>
    </label>);
  return { busy, error, run, box, needsAccept: !!risk && !accept };
}

const DEFAULT = "";
function Pick({ label, value, onChange, choices, hint }: { label: string; value: string; onChange: (v: string) => void; choices: [string, string][]; hint?: string }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm text-muted">{label}</span>
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value={DEFAULT}>{tr("Défaut de Proxmox")}</option>
        {choices.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>);
}
const YES_NO = (): [string, string][] => [["1", tr("Oui")], ["0", tr("Non")]];
const asNum = (v: string) => (v.trim() === "" ? NaN : Number(v));

/** Champ numérique optionnel : vide = défaut. Valide : vide, ou un nombre dans [min, max]. */
function NumField({ label, value, onChange, min, max, step, hint }: { label: string; value: string; onChange: (v: string) => void; min: number; max: number; step?: number; hint?: string }) {
  return <Field label={label} type="number" min={min} max={max} step={step ?? 1} value={value} onChange={(e) => onChange(e.target.value)} hint={hint} />;
}
const numOk = (v: string, min: number, max: number, int: boolean) => v.trim() === "" || (Number.isFinite(asNum(v)) && asNum(v) >= min && asNum(v) <= max && (!int || Number.isInteger(asNum(v))));

// ------------------------------------------------------------------ disque
export function DiskOptionsDialog({ disk, base, onDone, onClose }: { disk: HwDisk; base: string; onDone: () => Promise<void>; onClose: () => void }) {
  const o = disk.options;
  const init = { cache: o.cache ?? "", discard: o.discard ?? "", aio: o.aio ?? "", iothread: o.iothread ?? "", ssd: o.ssd ?? "", backup: o.backup ?? "", ro: o.ro ?? "",
                 replicate: o.replicate ?? "", detect_zeroes: o.detect_zeroes ?? "", mbps_rd: o.mbps_rd ?? "", mbps_wr: o.mbps_wr ?? "", iops_rd: o.iops_rd ?? "", iops_wr: o.iops_wr ?? "" };
  const [v, setV] = useState(init);
  const set = (k: keyof typeof init) => (x: string) => setV({ ...v, [k]: x });
  const { busy, error, run, box, needsAccept } = useOptionsSubmit(onClose, onDone);
  const body: DiskOptionsBody = {};
  const clear: string[] = [];
  const bools = ["iothread", "ssd", "backup", "ro", "replicate", "detect_zeroes"] as const;
  const nums = ["mbps_rd", "mbps_wr", "iops_rd", "iops_wr"] as const;
  for (const k of ["cache", "discard", "aio"] as const) if (v[k] !== init[k]) (v[k] === "" ? clear.push(k) : (body[k] = v[k]));
  for (const k of bools) if (v[k] !== init[k]) (v[k] === "" ? clear.push(k) : (body[k] = v[k] === "1"));
  for (const k of nums) if (v[k] !== init[k]) (v[k].trim() === "" ? clear.push(k) : (body[k] = asNum(v[k])));
  if (clear.length) body.clear = clear;
  const ok = Object.keys(body).length > 0 && numOk(v.mbps_rd, 0, 100000, false) && numOk(v.mbps_wr, 0, 100000, false) && numOk(v.iops_rd, 0, 10_000_000, true) && numOk(v.iops_wr, 0, 10_000_000, true) && !needsAccept;
  return (
    <Modal title={tr("Options du disque {key}", { key: disk.key })} subtitle={tr("Seules les options modifiées sont envoyées ; le volume et sa taille ne changent pas. Sur une machine en marche, le changement s'applique au prochain démarrage.")}
      wide onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel={tr("Enregistrer")} onSubmit={() => run((confirm) => api(`${base}/disks/${disk.key}/options`, { method: "PATCH", body: { ...body, confirm } }))}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Pick label={tr("Cache")} value={v.cache} onChange={set("cache")} choices={[["none", "none"], ["writethrough", "writethrough"], ["writeback", "writeback"], ["directsync", "directsync"], ["unsafe", "unsafe"]]} hint={tr("writeback et unsafe : risque de perte de données")} />
        <Pick label={tr("Discard (TRIM)")} value={v.discard} onChange={set("discard")} choices={[["on", "on"], ["ignore", "ignore"]]} />
        <Pick label={tr("E/S asynchrones (aio)")} value={v.aio} onChange={set("aio")} choices={[["io_uring", "io_uring"], ["native", "native"], ["threads", "threads"]]} />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Pick label={tr("Fil d'E/S dédié (iothread)")} value={v.iothread} onChange={set("iothread")} choices={YES_NO()} hint={tr("virtio, ou scsi avec le contrôleur virtio-scsi-single")} />
        <Pick label={tr("Émulation SSD")} value={v.ssd} onChange={set("ssd")} choices={YES_NO()} hint={tr("pas sur un disque virtio")} />
        <Pick label={tr("Détection des zéros")} value={v.detect_zeroes} onChange={set("detect_zeroes")} choices={YES_NO()} />
        <Pick label={tr("Inclure dans les sauvegardes")} value={v.backup} onChange={set("backup")} choices={YES_NO()} hint={tr("Non : ce disque n'est plus sauvegardé")} />
        <Pick label={tr("Lecture seule")} value={v.ro} onChange={set("ro")} choices={YES_NO()} />
        <Pick label={tr("Inclure dans la réplication")} value={v.replicate} onChange={set("replicate")} choices={YES_NO()} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <NumField label={tr("Débit en lecture max (Mo/s)")} value={v.mbps_rd} onChange={set("mbps_rd")} min={0} max={100000} step={0.1} hint={tr("Vide = pas de limite")} />
        <NumField label={tr("Débit en écriture max (Mo/s)")} value={v.mbps_wr} onChange={set("mbps_wr")} min={0} max={100000} step={0.1} />
        <NumField label={tr("Opérations en lecture max (IOPS)")} value={v.iops_rd} onChange={set("iops_rd")} min={0} max={10_000_000} />
        <NumField label={tr("Opérations en écriture max (IOPS)")} value={v.iops_wr} onChange={set("iops_wr")} min={0} max={10_000_000} />
      </div>
      {box}
    </Modal>);
}

// ------------------------------------------------------------------ carte réseau
export function NetOptionsDialog({ net, lxc, base, onDone, onClose }: { net: NetX; lxc: boolean; base: string; onDone: () => Promise<void>; onClose: () => void }) {
  const init = { rate: net.rate ?? "", mtu: net.mtu != null ? String(net.mtu) : "", queues: net.queues != null ? String(net.queues) : "", link_down: !!net.link_down, trunks: (net.trunks ?? []).join(";") };
  const [v, setV] = useState(init);
  const { busy, error, run, box, needsAccept } = useOptionsSubmit(onClose, onDone);
  const body: NetOptionsBody = {};
  const clear: string[] = [];
  if (v.rate !== init.rate) (v.rate.trim() === "" ? clear.push("rate") : (body.rate = asNum(v.rate)));
  if (v.mtu !== init.mtu) (v.mtu.trim() === "" ? clear.push("mtu") : (body.mtu = asNum(v.mtu)));
  if (!lxc && v.queues !== init.queues) (v.queues.trim() === "" ? clear.push("queues") : (body.queues = asNum(v.queues)));
  if (v.link_down !== init.link_down) body.link_down = v.link_down;
  const trunks = v.trunks.split(/[;,\s]+/).filter(Boolean);
  if (v.trunks !== init.trunks) (trunks.length === 0 ? clear.push("trunks") : (body.trunks = trunks));
  if (clear.length) body.clear = clear;
  const ok = Object.keys(body).length > 0 && numOk(v.rate, 0, 1_000_000, false) && numOk(v.mtu, 1, 65535, true) && numOk(v.queues, 0, 64, true) && trunks.every((t) => /^[0-9]{1,4}(-[0-9]{1,4})?$/.test(t)) && !needsAccept;
  return (
    <Modal title={tr("Options de la carte {key}", { key: net.key })} subtitle={tr("L'adresse MAC, le bridge et le VLAN ne changent pas ici. Seules les options modifiées sont envoyées.")}
      onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel={tr("Enregistrer")} onSubmit={() => run((confirm) => api(`${base}/nets/${net.key}/options`, { method: "PATCH", body: { ...body, confirm } }))}>
      <NumField label={tr("Limite de débit (Mo/s)")} value={v.rate} onChange={(x) => setV({ ...v, rate: x })} min={0} max={1_000_000} step={0.1} hint={tr("Vide = pas de limite")} />
      <NumField label={tr("MTU")} value={v.mtu} onChange={(x) => setV({ ...v, mtu: x })} min={1} max={65535} hint={lxc ? tr("Conteneur : de 64 à 65535") : tr("VM : carte virtio seulement ; 1 = celui du bridge")} />
      {!lxc && <NumField label={tr("Files multiples (queues)")} value={v.queues} onChange={(x) => setV({ ...v, queues: x })} min={0} max={64} hint={tr("Carte virtio seulement")} />}
      <Field label={tr("VLAN autorisés (trunks)")} value={v.trunks} onChange={(e) => setV({ ...v, trunks: e.target.value })} placeholder="10;20-30" hint={tr("Numéros ou plages séparés par « ; » ; vide = aucun")} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.link_down} onChange={(e) => setV({ ...v, link_down: e.target.checked })} />{tr("Câble débranché (la machine perd ce réseau)")}</label>
      {box}
    </Modal>);
}

// ------------------------------------------------------------------ CPU
export function CpuOptionsDialog({ cfg, base, onDone, onClose }: { cfg: HwConfig; base: string; onDone: () => Promise<void>; onClose: () => void }) {
  const s = cfg.settings;
  const init = { cpuunits: s.cpuunits != null ? String(s.cpuunits) : "", cpulimit: s.cpulimit != null ? String(s.cpulimit) : "", affinity: s.affinity != null ? String(s.affinity) : "", hugepages: s.hugepages != null ? String(s.hugepages) : "" };
  const [v, setV] = useState(init);
  const { busy, error, run, box, needsAccept } = useOptionsSubmit(onClose, onDone);
  const body: CpuOptionsBody = {};
  const clear: string[] = [];
  if (v.cpuunits !== init.cpuunits) (v.cpuunits.trim() === "" ? clear.push("cpuunits") : (body.cpuunits = asNum(v.cpuunits)));
  if (v.cpulimit !== init.cpulimit) (v.cpulimit.trim() === "" ? clear.push("cpulimit") : (body.cpulimit = asNum(v.cpulimit)));
  if (v.affinity !== init.affinity) (v.affinity.trim() === "" ? clear.push("affinity") : (body.affinity = v.affinity.trim()));
  if (v.hugepages !== init.hugepages) (v.hugepages === "" ? clear.push("hugepages") : (body.hugepages = v.hugepages));
  if (clear.length) body.clear = clear;
  const ok = Object.keys(body).length > 0 && numOk(v.cpuunits, 1, 262144, true) && numOk(v.cpulimit, 0, 128, false) && (v.affinity.trim() === "" || /^[0-9]{1,4}(-[0-9]{1,4})?(,[0-9]{1,4}(-[0-9]{1,4})?)*$/.test(v.affinity.trim())) && !needsAccept;
  return (
    <Modal title={tr("Options du processeur")} subtitle={tr("Priorité, limite et placement sur les cœurs du nœud. Sur une machine en marche, le changement s'applique au prochain démarrage.")}
      onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel={tr("Enregistrer")} onSubmit={() => run((confirm) => api(`${base}/cpu-options`, { method: "PATCH", body: { ...body, confirm } }))}>
      <NumField label={tr("Poids CPU (cpuunits)")} value={v.cpuunits} onChange={(x) => setV({ ...v, cpuunits: x })} min={1} max={262144} hint={tr("Plus il est haut, plus la machine passe devant les autres quand le nœud est chargé")} />
      <NumField label={tr("Limite d'utilisation (cpulimit)")} value={v.cpulimit} onChange={(x) => setV({ ...v, cpulimit: x })} min={0} max={128} step={0.1} hint={tr("En nombre de cœurs ; 0 ou vide = illimité")} />
      <Field label={tr("Cœurs du nœud autorisés (affinity)")} value={v.affinity} onChange={(e) => setV({ ...v, affinity: e.target.value })} placeholder="0,5,8-11" hint={tr("Numéros ou plages ; vide = tous les cœurs")} />
      <Pick label={tr("Hugepages")} value={v.hugepages} onChange={(x) => setV({ ...v, hugepages: x })} choices={[["any", tr("N'importe quelle taille")], ["2", tr("2 Mo")], ["1024", tr("1 Go")]]} hint={tr("Le nœud doit avoir des pages réservées, sinon la machine ne démarre pas")} />
      {box}
    </Modal>);
}
