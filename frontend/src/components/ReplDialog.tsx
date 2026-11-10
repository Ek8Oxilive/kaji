import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ClusterStatus, Guest } from "../lib/api";
import type { ReplMode, ReplPreview } from "../lib/types/ha";
import { Modal } from "./Modal";
import { Field, Notice } from "./ui";

type Tri = "" | "yes" | "no";
const tri = (t: Tri) => (t === "yes" ? true : t === "no" ? false : undefined);
const triOf = (v: boolean | null | undefined): Tri => (v === true ? "yes" : v === false ? "no" : "");

/**
 * Écriture de la réplication : créer, modifier, supprimer un job, lancer maintenant. Aperçu (`dry_run`) d'abord : le serveur annonce les bloqueurs (pas de ZFS, disque hors ZFS)
 * et les verrous. Supprimer sans conserver les copies exige de retaper le nom du job.
 */
export function ReplDialog({ connId, mode, presetGuest, onClose }: { connId: number; mode: ReplMode; presetGuest?: number; onClose: () => void }) {
  const qc = useQueryClient();
  const k = mode.kind, job = mode.kind === "new" ? null : mode.job;
  const guests = useQuery({ queryKey: ["guests", connId], queryFn: () => api<Guest[]>(`/api/connections/${connId}/guests`), enabled: k === "new" });
  const cluster = useQuery({ queryKey: ["cluster-status", connId], queryFn: () => api<ClusterStatus>(`/api/connections/${connId}/cluster/status`), enabled: k === "new" });
  const [guest, setGuest] = useState(presetGuest !== undefined ? String(presetGuest) : ""), [target, setTarget] = useState(""), [schedule, setSchedule] = useState(job?.schedule ?? ""), [rate, setRate] = useState(job?.rate?.toString() ?? ""),
    [comment, setComment] = useState(job?.comment ?? ""), [disable, setDisable] = useState<Tri>(triOf(job?.disable)), [keep, setKeep] = useState(false), [typed, setTyped] = useState("");
  const [preview, setPreview] = useState<ReplPreview | null>(null), [ackLive, setAckLive] = useState(false);
  const [busy, setBusy] = useState(false), [done, setDone] = useState(false), [err, setErr] = useState<string | null>(null);
  useEffect(() => { setPreview(null); setAckLive(false); setErr(null); }, [guest, target, schedule, rate, comment, disable, keep]);   // retaper le nom du job ne réinitialise pas l'aperçu

  const base = `/api/connections/${connId}/replication`;
  const chosen = (guests.data ?? []).find((g) => String(g.vmid) === guest);
  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));

  const request = (extra: Record<string, unknown>) => {
    if (k === "delete") {
      const q = new URLSearchParams(Object.entries({ ...extra, keep, ...(typed ? { type_name: typed } : {}) }).filter(([, v]) => v !== undefined && v !== false).map(([a, v]) => [a, String(v)]));
      return { path: `${base}/${encodeURIComponent(job!.id)}?${q}`, init: { method: "DELETE" } };
    }
    if (k === "now") return { path: `${base}/${encodeURIComponent(job!.id)}/now`, init: { method: "POST", body: extra } };
    const f: Record<string, unknown> = {}, clear: string[] = [];
    const put = (name: string, v: unknown, was: unknown) => { if (v !== undefined && v !== "") f[name] = v; else if (job && was !== null && was !== undefined) clear.push(name); };
    put("schedule", schedule.trim() || undefined, job?.schedule); put("rate", num(rate), job?.rate); put("comment", comment.trim() || undefined, job?.comment); put("disable", tri(disable), job?.disable);
    return k === "new" ? { path: base, init: { method: "POST", body: { guest: Number(guest), target, ...f, ...extra } } }
      : { path: `${base}/${encodeURIComponent(job!.id)}`, init: { method: "PUT", body: { ...f, ...(clear.length ? { clear } : {}), ...extra } } };
  };
  const look = async () => { setErr(null); try { const r = request({ dry_run: true }); setPreview(await api<ReplPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try { const r = request({ confirm: true, ...(ackLive ? { acknowledge_live: true } : {}) }); await api(r.path, r.init); await qc.invalidateQueries({ queryKey: ["ha", connId] }); setDone(true); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };

  const blocked = !!preview?.blocked, live = !!preview?.locks.live.length;
  const retypeOk = k !== "delete" || keep || typed === job?.id;
  const ready = !!preview && !blocked && (!live || ackLive) && retypeOk;
  const title = k === "new" ? "Nouveau job de réplication" : k === "edit" ? `Modifier le job ${job!.id}` : k === "delete" ? `Supprimer le job ${job!.id}` : `Lancer ${job!.id} maintenant`;
  const select = (label: string, v: string, set: (s: string) => void, opts: [string, string][]) => (
    <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span><select className="field" value={v} onChange={(e) => set(e.target.value)}>{opts.map(([val, text]) => <option key={val} value={val}>{text}</option>)}</select></label>);

  if (done) return <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit><Notice kind="ok">{k === "delete" ? "Job marqué pour suppression : Proxmox le retire au prochain passage sur le nœud source." : "Enregistré, relu chez Proxmox."}</Notice></Modal>;
  return (
    <Modal title={title} subtitle="Rien n'est écrit sans aperçu : le serveur dit ce qui bloque et ce qui est verrouillé." onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={k === "delete" ? "Supprimer" : k === "now" ? "Lancer" : "Appliquer"} danger={live || k === "delete"} busy={busy} error={err} canSubmit={ready} wide>
      {k === "new" && <>
        {presetGuest !== undefined ? <p className="text-sm"><span className="text-muted">Machine à répliquer</span> <b>{chosen ? `${chosen.name ?? chosen.vmid} (#${presetGuest})` : `#${presetGuest}`}</b></p> : select("Machine à répliquer", guest, (s) => { setGuest(s); setTarget(""); }, [["", guests.isLoading ? "Chargement…" : "Choisir une machine"], ...(guests.data ?? []).filter((g) => !g.template && g.vmid !== null).map((g) => [String(g.vmid), `${g.type === "lxc" ? "ct" : "vm"}:${g.vmid} · ${g.name ?? ""} (${g.node})`] as [string, string])])}
        {select("Nœud cible", target, setTarget, [["", "Choisir un nœud"], ...(cluster.data?.nodes ?? []).filter((n) => n.online && n.name !== chosen?.node).map((n) => [n.name, n.name] as [string, string])])}
      </>}
      {(k === "new" || k === "edit") && <>
        <Field label="Planification" value={schedule} maxLength={128} onChange={(e) => setSchedule(e.target.value)} hint="Calendrier systemd : */15, mon..fri 02:00… Vide = défaut de Proxmox (*/15)" />
        <Field label="Débit maximal (Mo/s)" type="number" min={1} step="any" value={rate} onChange={(e) => setRate(e.target.value)} hint="Vide = illimité" />
        <Field label="Commentaire" value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
        {select("Désactivé", disable, (s) => setDisable(s as Tri), [["", "Défaut (actif)"], ["yes", "Oui"], ["no", "Non"]])}
      </>}
      {k === "delete" && <>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} /><span>Conserver les copies déjà répliquées sur le nœud cible</span></label>
        {!keep && <Notice kind="error">Sans cette case, les copies sur le nœud cible seront <b>détruites</b>. Retape <code>{job!.id}</code> pour confirmer.<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-2" /></Notice>}
      </>}
      {k === "now" && <p className="text-sm text-muted">Lance la synchronisation sur le nœud source <code>{job!.source ?? "?"}</code>, sans attendre la planification.</p>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={k === "new" && (!guest || !target)} onClick={look}>Aperçu</button>
      {preview && (
        <div className="space-y-3 text-sm">
          {blocked && <Notice kind="error"><b>Bloqué</b> : {(preview.blockers ?? []).join(" ; ")}.</Notice>}
          {!blocked && preview.locks.inert && <Notice kind="ok">Aucun verrou : le job sera créé, la première synchronisation suivra la planification.</Notice>}
          {live && !blocked && <Notice kind="error">{preview.locks.live.join(" ; ")}.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ackLive} onChange={(e) => setAckLive(e.target.checked)} /><span>Je comprends que cela s'applique tout de suite</span></label></Notice>}
        </div>)}
    </Modal>
  );
}
