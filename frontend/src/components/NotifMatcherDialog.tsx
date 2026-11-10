import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { SEVERITIES, type NotifMatcher, type NotifMatcherDetail, type NotifPreview, type NotifTarget } from "../lib/types/notifications";
import { Modal } from "./Modal";
import { Field, Notice } from "./ui";

export type MatcherMode = { kind: "new" } | { kind: "edit" | "delete"; matcher: NotifMatcher };
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

/** Règles de notification (matchers) : quelles notifications partent vers quelles cibles. */
export function NotifMatcherDialog({ connId, mode, targets, onClose }: { connId: number; mode: MatcherMode; targets: NotifTarget[]; onClose: () => void }) {
  const qc = useQueryClient();
  const k = mode.kind, m = mode.kind === "new" ? null : mode.matcher;
  const detail = useQuery({ queryKey: ["notif-matcher", connId, m?.name], queryFn: () => api<NotifMatcherDetail>(`/api/connections/${connId}/notifications/matchers/${m!.name}`), enabled: k === "edit" });
  const d = detail.data;
  const [name, setName] = useState(""), [comment, setComment] = useState(""), [tgs, setTgs] = useState<string[]>([]), [sev, setSev] = useState<string[]>([]), [mmode, setMmode] = useState<"" | "all" | "any">("");
  const [fields, setFields] = useState(""), [cal, setCal] = useState(""), [invert, setInvert] = useState(false), [disable, setDisable] = useState(false), [typed, setTyped] = useState("");
  const [preview, setPreview] = useState<NotifPreview | null>(null), [busy, setBusy] = useState(false), [done, setDone] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (d) { setComment(d.comment ?? ""); setTgs(d.targets); setSev(d.match_severity); setMmode(d.mode); setFields(d.match_field.join("\n")); setCal(d.match_calendar.join("\n")); setInvert(d.invert); setDisable(d.disable); } }, [d]);
  useEffect(() => { setPreview(null); setErr(null); }, [name, comment, tgs, sev, mmode, fields, cal, invert, disable]);
  const toggle = (arr: string[], set: (a: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const body = (extra: Record<string, unknown>) => {
    const b: Record<string, unknown> = {}, clear: string[] = [];
    const same = (a: string[], c: string[]) => a.join("|") === c.join("|");
    if (k === "new" || !same(tgs, d?.targets ?? [])) b.target = tgs;
    if (k === "new" ? sev.length : !same(sev, d?.match_severity ?? [])) { if (sev.length) b.match_severity = sev; else clear.push("match_severity"); }
    if (k === "new" ? lines(fields).length : !same(lines(fields), d?.match_field ?? [])) { if (lines(fields).length) b.match_field = lines(fields); else clear.push("match_field"); }
    if (k === "new" ? lines(cal).length : !same(lines(cal), d?.match_calendar ?? [])) { if (lines(cal).length) b.match_calendar = lines(cal); else clear.push("match_calendar"); }
    if (mmode && mmode !== d?.mode) b.mode = mmode;
    if (k === "new" ? invert : invert !== d?.invert) b.invert_match = invert;
    if (k === "new" ? disable : disable !== d?.disable) b.disable = disable;
    if (comment !== (d?.comment ?? "")) { if (comment) b.comment = comment; else if (k === "edit") clear.push("comment"); }
    return { ...b, ...(clear.length ? { clear } : {}), ...(k === "new" ? { name } : {}), ...(k === "edit" ? { digest: d?.digest } : {}), ...extra };
  };
  const base = `/api/connections/${connId}/notifications/matchers`;
  const request = (extra: Record<string, unknown>) => k === "new" ? { path: base, init: { method: "POST", body: body(extra) } }
    : k === "edit" ? { path: `${base}/${m!.name}`, init: { method: "PUT", body: body(extra) } }
    : { path: `${base}/${m!.name}?${new URLSearchParams({ ...(extra.dry_run ? { dry_run: "true" } : { confirm: "true", type_name: typed }) })}`, init: { method: "DELETE" } };
  const look = async () => { setErr(null); try { const r = request({ dry_run: true }); setPreview(await api<NotifPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try { const r = request({ confirm: true }); await api(r.path, r.init); await qc.invalidateQueries({ queryKey: ["notifications", connId] }); setDone(k === "delete" ? "Règle supprimée." : "Enregistré, relu chez Proxmox."); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const ready = !!preview && (k !== "delete" || typed === m?.name);
  if (done) return <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit><Notice kind="ok">{done}</Notice></Modal>;
  return (
    <Modal title={k === "new" ? "Ajouter une règle" : k === "edit" ? `Modifier ${m!.name}` : `Supprimer ${m!.name}`} subtitle="Une règle envoie les notifications qui correspondent vers ses cibles." onClose={busy ? () => {} : onClose}
      onSubmit={run} submitLabel={k === "delete" ? "Supprimer" : "Appliquer"} danger={k === "delete"} busy={busy} error={err} canSubmit={ready} wide>
      {k === "delete" ? <Notice kind="error">La règle <code>{m!.name}</code> sera supprimée. Retape <code>{m!.name}</code> pour confirmer.<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-2" /></Notice>
        : k === "edit" && !d ? <p className="text-sm text-muted">Chargement…</p> : <>
        {k === "new" && <Field label="Nom" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} hint="Lettre puis lettres, chiffres, . _ -" autoComplete="off" />}
        <fieldset className="space-y-1 text-sm"><legend className="text-muted">Cibles (au moins une)</legend>
          {targets.map((t) => <label key={t.name} className="mr-4 inline-flex items-center gap-2"><input type="checkbox" checked={tgs.includes(t.name)} onChange={() => toggle(tgs, setTgs, t.name)} /><span className="font-mono">{t.name}</span></label>)}</fieldset>
        <fieldset className="space-y-1 text-sm"><legend className="text-muted">Gravités (vide = toutes)</legend>
          {SEVERITIES.map((s) => <label key={s} className="mr-4 inline-flex items-center gap-2"><input type="checkbox" checked={sev.includes(s)} onChange={() => toggle(sev, setSev, s)} />{s}</label>)}</fieldset>
        <label className="block space-y-1.5 text-sm"><span className="text-muted">Champs (une ligne chacun : <code>exact:type=vzdump</code> ou <code>regex:hostname=^pve</code>)</span><textarea className="field min-h-[4rem] font-mono text-xs" value={fields} onChange={(e) => setFields(e.target.value)} /></label>
        <label className="block space-y-1.5 text-sm"><span className="text-muted">Calendrier (une ligne chacun, ex. <code>mon..fri 08-18</code>)</span><textarea className="field min-h-[3rem] font-mono text-xs" value={cal} onChange={(e) => setCal(e.target.value)} /></label>
        <div className="grid gap-4 sm:grid-cols-2"><label className="block space-y-1.5 text-sm"><span className="text-muted">Mode</span><select className="field" value={mmode} onChange={(e) => setMmode(e.target.value as typeof mmode)}><option value="">Défaut (toutes les conditions)</option><option value="all">all : toutes les conditions</option><option value="any">any : une suffit</option></select></label>
          <Field label="Commentaire" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} hint="ASCII uniquement" autoComplete="off" /></div>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={invert} onChange={(e) => setInvert(e.target.checked)} />Inverser la correspondance</label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={disable} onChange={(e) => setDisable(e.target.checked)} /><span><b>Désactivée</b></span></label>
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={k === "new" ? !name || tgs.length === 0 : k === "edit" ? !d : false} onClick={look}>Aperçu</button>
      {preview && <Notice kind="ok">{k === "delete" ? <>Sera supprimé : <code>{m!.name}</code></> : <>Sera envoyé : <code>{Object.entries(preview.params ?? {}).map(([a, b]) => `${a}=${Array.isArray(b) ? b.join("|") : b}`).join(", ") || "rien"}</code>{preview.remove?.length ? <> · retiré : <code>{preview.remove.join(", ")}</code></> : null}</>}</Notice>}
    </Modal>
  );
}
