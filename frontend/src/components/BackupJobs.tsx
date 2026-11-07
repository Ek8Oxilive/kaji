import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type Guest, type NodeInfo, type Pool } from "../lib/api";
import { confirmReasons } from "../lib/confirmRisk";
import { DAYS, buildSchedule, describeSchedule, parseSchedule } from "../lib/schedule";
import type { BackupCompress, BackupMode, BackupStore, Job, JobCreateBody, JobPatchBody, JobRetention, JobSelection, JobSelectionBody } from "../lib/types/sauvegardes";
import { COMPRESS, MODES } from "./BackupDialogs";
import { ConfirmDialog } from "./ConfirmDialog";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

const enc = encodeURIComponent;
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "–");
const warn = "rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn";
const radio = "mt-0.5 size-4 accent-[var(--accent)]";

const KEEP: { key: keyof Omit<JobRetention, "keep_all">; label: string }[] = [
  { key: "keep_last", label: "Dernières sauvegardes" }, { key: "keep_hourly", label: "Par heure" }, { key: "keep_daily", label: "Par jour" },
  { key: "keep_weekly", label: "Par semaine" }, { key: "keep_monthly", label: "Par mois" }, { key: "keep_yearly", label: "Par an" },
];
const KEEP_TEXT: Record<string, string> = { keep_last: "dernières", keep_hourly: "heures", keep_daily: "jours", keep_weekly: "semaines", keep_monthly: "mois", keep_yearly: "ans" };

const describeRetention = (r: JobRetention | null) =>
  !r ? "Celle du stockage" : r.keep_all ? "Tout garder" : Object.entries(r).map(([k, v]) => `${v} ${KEEP_TEXT[k] ?? k}`).join(" · ");
const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const sortedSel = (s: JobSelection | JobSelectionBody): unknown => (s.type === "vmids" ? { type: "vmids", vmids: [...s.vmids].sort((a, b) => a - b) } : s);

// ------------------------------------------------------------------------------------------------ panneau

export function JobsPanel({ connId, nodes, guests, stores }: { connId: number; nodes: NodeInfo[]; guests: Guest[]; stores: BackupStore[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const base = `/api/connections/${connId}/backup-jobs`;
  const jobs = useQuery({ queryKey: ["backup-jobs", connId], queryFn: () => api<Job[]>(base), staleTime: 15_000 });
  const [edit, setEdit] = useState<Job | "new" | null>(null);
  const [del, setDel] = useState<Job | null>(null);
  const [toggle, setToggle] = useState<{ job: Job; reasons: string[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const names = useMemo(() => new Map(guests.map((g) => [g.vmid, g.name])), [guests]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["backup-jobs", connId] });

  const describeSelection = (s: JobSelection) =>
    s.type === "all" ? "Toutes les machines" : s.type === "pool" ? `Pool ${s.pool}` : s.type === "vmids" ? s.vmids.map((v) => names.get(v) ?? `#${v}`).join(", ") : "–";

  /** Active ou désactive un job. Le serveur dit si une confirmation est nécessaire (activer un job en mode « Arrêt »). */
  const setEnabled = async (job: Job, confirm: boolean) => {
    setBusy(job.id); setError(null);
    try {
      await api(`${base}/${enc(job.id)}`, { method: "PUT", body: { enabled: !job.enabled, ...(confirm ? { confirm: true } : {}) } });
      toast("ok", `Job ${!job.enabled ? "activé" : "désactivé"}`);
      await refresh();
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setToggle({ job, reasons }); else setError((e as Error).message);
    } finally { setBusy(null); }
  };

  const remove = async (job: Job) => {
    setBusy(job.id); setError(null); setDel(null);
    try {
      await api(`${base}/${enc(job.id)}?confirm=true`, { method: "DELETE" });
      toast("ok", "Job supprimé (les sauvegardes déjà faites sont conservées)");
      await refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  const rows = jobs.data ?? [];
  return (
    <section className="space-y-3" aria-label="Sauvegardes planifiées">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Sauvegardes planifiées <span className="text-sm font-normal text-muted">({rows.length})</span></h2>
        <div className="flex items-center gap-3">
          <Button onClick={() => setEdit("new")} className="!px-3 !py-1.5" disabled={jobs.isLoading || stores.length === 0}
            title={stores.length === 0 ? "Aucun stockage n'accepte les sauvegardes" : undefined}>Nouveau job</Button>
          <Button variant="ghost" onClick={() => jobs.refetch()} disabled={jobs.isFetching} className="!px-3 !py-1.5">
            <span className={jobs.isFetching ? "inline-block animate-spin" : ""}>↻</span> Actualiser
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted">Créer, modifier ou supprimer un job exige le droit <code>Sys.Modify</code> sur « / » dans Proxmox. La lecture n'en a pas besoin.</p>

      {jobs.error && <Notice kind="error">{(jobs.error as Error).message} — <button className="underline" onClick={() => jobs.refetch()}>réessayer</button></Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      {jobs.isLoading ? <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="panel h-12 animate-pulse" />)}</div>
        : rows.length === 0 && !jobs.error ? <div className="panel p-6 text-muted">Aucune sauvegarde planifiée sur ce cluster.</div>
        : rows.length > 0 && (
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[60rem] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th scope="col" className="px-4 py-2 font-normal">État</th><th scope="col" className="px-4 py-2 font-normal">Planification</th>
                  <th scope="col" className="px-4 py-2 font-normal">Machines</th><th scope="col" className="px-4 py-2 font-normal">Stockage</th>
                  <th scope="col" className="px-4 py-2 font-normal">Mode</th><th scope="col" className="px-4 py-2 font-normal">Rétention</th>
                  <th scope="col" className="px-4 py-2 font-normal">Prochaine exécution</th><th scope="col" className="px-4 py-2 text-right font-normal"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((j) => (
                  <tr key={j.id} className="border-b border-line/60 last:border-0 align-top">
                    <td className="px-4 py-2">
                      <button type="button" onClick={() => setEnabled(j, false)} disabled={busy === j.id} aria-pressed={j.enabled}
                        title={j.enabled ? "Désactiver ce job" : "Activer ce job"}
                        className={`flex items-center gap-1.5 text-xs transition disabled:opacity-50 ${j.enabled ? "text-ok" : "text-muted"}`}>
                        <span className={`size-2 rounded-full ${j.enabled ? "bg-ok" : "bg-muted"}`} />{j.enabled ? "Actif" : "Désactivé"}
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2" title={j.id}>{describeSchedule(j.schedule)}{j.node && <span className="block text-xs text-muted">nœud {j.node}</span>}</td>
                    <td className="max-w-[16rem] px-4 py-2"><span className="block truncate" title={describeSelection(j.selection)}>{describeSelection(j.selection)}</span></td>
                    <td className="px-4 py-2 text-muted">{j.storage ?? "–"}</td>
                    <td className="px-4 py-2 text-muted">{MODES.find((m) => m.id === j.mode)?.label ?? j.mode}<span className="block text-xs">{COMPRESS.find((c) => c.id === (j.compress ?? "zstd"))?.id ?? j.compress}</span></td>
                    <td className="px-4 py-2 text-muted">{describeRetention(j.retention)}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-muted">{j.enabled ? when(j.next_run) : "–"}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" className="!px-3 !py-1 text-xs" onClick={() => setEdit(j)} disabled={busy === j.id}>Modifier</Button>
                        <Button variant="danger" className="!px-3 !py-1 text-xs" onClick={() => setDel(j)} disabled={busy === j.id}>Supprimer</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

      {edit && <JobDialog connId={connId} job={edit === "new" ? null : edit} nodes={nodes} guests={guests} stores={stores} onClose={() => setEdit(null)} />}
      {del && (
        <ConfirmDialog title="Supprimer ce job planifié ?" confirmLabel="Supprimer le job" danger onCancel={() => setDel(null)} onConfirm={() => remove(del)}>
          Le job « {describeSchedule(del.schedule)} » ne s'exécutera plus. <strong className="text-fg">Les sauvegardes déjà faites ne sont pas supprimées.</strong>
        </ConfirmDialog>
      )}
      {toggle && (
        <ConfirmDialog title="Confirmer l'activation ?" confirmLabel="Confirmer" danger onCancel={() => setToggle(null)} onConfirm={() => { const t = toggle; setToggle(null); setEnabled(t.job, true); }}>
          <ul className="list-disc space-y-1 pl-5">{toggle.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </ConfirmDialog>
      )}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ création / modification

function PoolSelect({ connId, value, onChange }: { connId: number; value: string; onChange: (v: string) => void }) {
  const pools = useQuery({ queryKey: ["pools", connId], queryFn: () => api<Pool[]>(`/api/connections/${connId}/pools`), staleTime: 30_000, retry: false });
  if (pools.data && pools.data.length > 0) {
    return (
      <select className="field" aria-label="Pool" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choisir un pool…</option>
        {value && !pools.data.some((p) => p.poolid === value) && <option value={value}>{value} (actuel)</option>}
        {pools.data.map((p) => <option key={p.poolid} value={p.poolid}>{p.poolid}{p.comment ? ` · ${p.comment}` : ""}</option>)}
      </select>
    );
  }
  return <input className="field" aria-label="Pool" placeholder="Nom du pool" value={value} onChange={(e) => onChange(e.target.value.trim())} />;
}

type RetKind = "storage" | "all" | "limit";

export function JobDialog({ connId, job, nodes, guests, stores, onClose }: { connId: number; job: Job | null; nodes: NodeInfo[]; guests: Guest[]; stores: BackupStore[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const parsed = parseSchedule(job?.schedule ?? null);
  const [days, setDays] = useState<string[]>(parsed?.days ?? DAYS.map((d) => d.id));
  const [time, setTime] = useState(parsed?.time ?? "02:00");
  const [rawSchedule, setRawSchedule] = useState(!!job && !parsed);     // planification créée ailleurs : conservée tant qu'on n'y touche pas
  const options = stores.filter((s) => s.active).filter((s, i, all) => all.findIndex((x) => x.storage === s.storage) === i);
  const [storage, setStorage] = useState(job?.storage ?? options[0]?.storage ?? "");
  const [selType, setSelType] = useState<"vmids" | "pool" | "all">(job?.selection.type === "all" || job?.selection.type === "pool" ? job.selection.type : "vmids");
  const [vmids, setVmids] = useState<number[]>(job?.selection.type === "vmids" ? job.selection.vmids : []);
  const [pool, setPool] = useState(job?.selection.type === "pool" ? job.selection.pool : "");
  const [mode, setMode] = useState<BackupMode>(job?.mode ?? "snapshot");
  const [compress, setCompress] = useState<BackupCompress>(job?.compress ?? "zstd");
  const [retKind, setRetKind] = useState<RetKind>(!job?.retention ? "storage" : job.retention.keep_all ? "all" : "limit");
  const [keep, setKeep] = useState<Record<string, string>>(() => Object.fromEntries(KEEP.map((k) => [k.key, job?.retention?.[k.key] != null ? String(job.retention[k.key]) : ""])));
  const [node, setNode] = useState(job?.node ?? "");
  const [enabled, setEnabled] = useState(job?.enabled ?? true);
  const [notes, setNotes] = useState(job?.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [risk, setRisk] = useState<string[] | null>(null);

  const keepNums = KEEP.map((k) => ({ key: k.key, raw: keep[k.key].trim() })).filter((k) => k.raw !== "");
  const keepOk = keepNums.length > 0 && keepNums.every((k) => /^[0-9]+$/.test(k.raw) && Number(k.raw) >= 1 && Number(k.raw) <= 999);
  const retention: JobRetention | undefined = retKind === "all" ? { keep_all: true } : retKind === "limit" && keepOk
    ? Object.fromEntries(keepNums.map((k) => [k.key, Number(k.raw)])) : undefined;
  const selection: JobSelectionBody | null = selType === "all" ? { type: "all" } : selType === "pool" ? (pool ? { type: "pool", pool } : null) : vmids.length > 0 ? { type: "vmids", vmids } : null;
  const schedule = buildSchedule(days, time);
  const scheduleOk = rawSchedule || (days.length > 0 && /^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(time));
  const notesOk = notes.length <= 200 && !/[\\\u0000-\u001f\u007f]/.test(notes);
  const retOk = retKind !== "limit" || keepOk;
  const valid = scheduleOk && !!storage && !!selection && retOk && notesOk;

  /** Corps à envoyer : à la création, tout ; à la modification, seulement ce qui a changé. `null` : rien n'a changé. */
  const body = useMemo((): JobCreateBody | JobPatchBody | null => {
    if (!valid || !selection) return null;
    if (!job) {
      return { schedule, storage, selection, mode, compress, enabled, ...(retention ? { retention } : {}), ...(node ? { node } : {}), ...(notes.trim() ? { notes: notes.trim() } : {}) };
    }
    const p: JobPatchBody = {};
    if (!rawSchedule && schedule !== job.schedule) p.schedule = schedule;
    if (storage !== job.storage) p.storage = storage;
    if (!sameJson(sortedSel(selection), sortedSel(job.selection))) p.selection = selection;
    if (mode !== job.mode) p.mode = mode;
    if (compress !== (job.compress ?? "zstd")) p.compress = compress;
    if (retention && !sameJson(retention, job.retention)) p.retention = retention;
    if ((node || null) !== job.node) p.node = node || null;
    if (enabled !== job.enabled) p.enabled = enabled;
    if ((notes.trim() || null) !== job.notes) p.notes = notes.trim() || null;
    return Object.keys(p).length ? p : null;
  }, [valid, selection, job, rawSchedule, schedule, storage, mode, compress, retention, node, enabled, notes]);

  // Une confirmation ne vaut que pour la demande qui l'a provoquée : si un champ change, les raisons ne sont plus celles-là.
  const bodyKey = JSON.stringify(body);
  useEffect(() => { setRisk(null); }, [bodyKey]);

  const send = async (confirm: boolean) => {
    if (!body) return;
    setBusy(true); setError(null);
    try {
      const payload = { ...body, ...(confirm ? { confirm: true } : {}) };
      if (job) await api(`/api/connections/${connId}/backup-jobs/${enc(job.id)}`, { method: "PUT", body: payload });
      else await api(`/api/connections/${connId}/backup-jobs`, { method: "POST", body: payload });
      toast("ok", job ? "Job modifié" : "Job créé");
      await qc.invalidateQueries({ queryKey: ["backup-jobs", connId] });
      onClose();
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setRisk(reasons); else setError((e as Error).message);
    } finally { setBusy(false); }
  };

  const toggleDay = (d: string) => setDays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]));
  const toggleVm = (id: number) => setVmids((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  const storageList = job?.storage && !options.some((s) => s.storage === job.storage) ? [{ storage: job.storage, shared: false, node: "", active: false, avail: null }, ...options] : options;

  return (
    <Modal wide title={job ? "Modifier le job planifié" : "Nouveau job planifié"} subtitle={job ? describeSchedule(job.schedule) : "Une sauvegarde automatique, à heure fixe."}
      onClose={onClose} busy={busy} error={error} canSubmit={!!body} submitLabel={risk ? "Confirmer et enregistrer" : "Enregistrer"} danger={!!risk}
      onSubmit={() => send(!!risk)}>
      <fieldset className="space-y-2">
        <legend className="text-sm text-muted">Planification</legend>
        {rawSchedule ? (
          <div className="space-y-2 rounded-xl border border-line bg-surface2 p-3 text-sm">
            <p>Planification actuelle : <code>{job?.schedule}</code>. Elle a été créée ailleurs et Kaji la conserve telle quelle.</p>
            <Button type="button" variant="ghost" className="!px-3 !py-1 text-xs" onClick={() => setRawSchedule(false)}>La remplacer par une planification Kaji</Button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Jours">
              {DAYS.map((d) => (
                <button key={d.id} type="button" aria-pressed={days.includes(d.id)} onClick={() => toggleDay(d.id)}
                  className={`rounded-full border px-3 py-1 text-xs transition ${days.includes(d.id) ? "border-accent bg-accent text-accentfg" : "border-line bg-surface2 text-muted hover:text-fg"}`}>{d.short}</button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm"><span className="text-muted">Heure</span>
                <input type="time" className="field !w-auto !py-1.5" value={time} onChange={(e) => setTime(e.target.value)} aria-invalid={!scheduleOk} /></label>
              <span className="text-sm text-muted">{scheduleOk ? describeSchedule(schedule) : "Choisis au moins un jour et une heure."}</span>
            </div>
          </>
        )}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-1.5"><span className="text-sm text-muted">Stockage de destination</span>
          <select className="field" value={storage} onChange={(e) => setStorage(e.target.value)}>
            {storageList.length === 0 && <option value="">Aucun stockage de sauvegarde</option>}
            {storageList.map((s) => <option key={s.storage} value={s.storage}>{s.storage}{s.shared ? " (partagé)" : ""}</option>)}
          </select></label>
        <label className="block space-y-1.5"><span className="text-sm text-muted">Nœud</span>
          <select className="field" value={node} onChange={(e) => setNode(e.target.value)}>
            <option value="">Tous les nœuds</option>{nodes.map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}
          </select></label>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm text-muted">Machines à sauvegarder</legend>
        {([["vmids", "Des machines précises"], ["pool", "Un pool"], ["all", "Toutes les machines"]] as const).map(([t, l]) => (
          <label key={t} className="flex items-center gap-2 text-sm"><input type="radio" name="sel" className={radio} checked={selType === t} onChange={() => setSelType(t)} />{l}</label>
        ))}
        {selType === "vmids" && (
          <div className="max-h-40 space-y-1 overflow-y-auto rounded-xl border border-line bg-surface2 p-3" role="group" aria-label="Machines">
            {guests.length === 0 && <p className="text-sm text-muted">Aucune machine.</p>}
            {guests.map((g) => (
              <label key={g.vmid} className="flex items-center gap-2 text-sm"><input type="checkbox" className={radio} checked={vmids.includes(g.vmid)} onChange={() => toggleVm(g.vmid)} />
                {g.name ?? g.vmid} <span className="text-xs text-muted">#{g.vmid} · {g.type === "qemu" ? "VM" : "LXC"} · {g.node}</span></label>
            ))}
          </div>
        )}
        {selType === "pool" && <PoolSelect connId={connId} value={pool} onChange={setPool} />}
        {selType === "all" && <p className={warn}>Toutes les machines du cluster seront sauvegardées, y compris celles créées plus tard.</p>}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm text-muted">Mode</legend>
        {MODES.map((m) => (
          <label key={m.id} className="flex items-start gap-2 text-sm"><input type="radio" name="mode" className={radio} checked={mode === m.id} onChange={() => setMode(m.id)} />
            <span>{m.label} <span className="block text-xs text-muted">{m.hint}</span></span></label>
        ))}
        {mode === "stop" && <p className={warn}>Le mode « Arrêt » <strong>éteint chaque machine à chaque exécution</strong> du job. Une confirmation te sera demandée.</p>}
      </fieldset>

      <label className="block space-y-1.5"><span className="text-sm text-muted">Compression</span>
        <select className="field" value={compress} onChange={(e) => setCompress(e.target.value as BackupCompress)}>{COMPRESS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>

      <fieldset className="space-y-2">
        <legend className="text-sm text-muted">Rétention</legend>
        {(job?.retention ? ([["all", "Garder toutes les sauvegardes"], ["limit", "Limiter le nombre de sauvegardes gardées"]] as const)
          : ([["storage", "Utiliser la rétention du stockage"], ["all", "Garder toutes les sauvegardes"], ["limit", "Limiter le nombre de sauvegardes gardées"]] as const)
        ).map(([k, l]) => (
          <label key={k} className="flex items-center gap-2 text-sm"><input type="radio" name="ret" className={radio} checked={retKind === k} onChange={() => setRetKind(k)} />{l}</label>
        ))}
        {retKind === "limit" && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {KEEP.map((k) => (
                <Field key={k.key} label={k.label} type="number" min={1} max={999} value={keep[k.key]} onChange={(e) => setKeep((cur) => ({ ...cur, [k.key]: e.target.value }))} />
              ))}
            </div>
            <p className={keepOk || keepNums.length === 0 ? "text-xs text-muted" : "text-xs text-danger"}>
              {keepNums.length === 0 || keepOk ? "Au moins une règle, de 1 à 999. Les règles s'additionnent : une sauvegarde est gardée si l'une d'elles la couvre."
                : "Chaque valeur doit être un entier de 1 à 999 (zéro est refusé : il supprimerait tout)."}
            </p>
          </div>
        )}
        {job?.retention && <p className="text-xs text-muted">Une fois une rétention définie, Kaji ne permet pas de revenir à celle du stockage.</p>}
      </fieldset>

      <Field label="Notes (facultatif)" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={200} aria-invalid={!notesOk}
        hint={notesOk ? "Une seule ligne. Proxmox y remplace {{guestname}}, {{vmid}}, {{node}}, {{cluster}}." : "Une seule ligne, sans antislash."} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className={radio} checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Job activé</label>

      {risk && (
        <div className={`${warn} space-y-2`} role="alert">
          <p className="font-medium">Confirmation requise</p>
          <ul className="list-disc space-y-1 pl-5">{risk.map((r) => <li key={r}>{r}</li>)}</ul>
          <p>Clique sur « Confirmer et enregistrer » pour continuer, ou modifie le formulaire.</p>
        </div>
      )}
    </Modal>
  );
}
