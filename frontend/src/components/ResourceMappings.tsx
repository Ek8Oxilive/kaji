import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type NodeInfo } from "../lib/api";
import { MTYPES, MTYPE_LABEL, emptyEntry, type MapEntry, type Mapping, type MappingPreview, type MType, type PciDevice, type UsbDevice } from "../lib/types/mappings";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

import { tr } from "../lib/i18n";
type Mode = { kind: "new" } | { kind: "edit"; row: Mapping } | { kind: "delete"; row: Mapping };

const summary = (t: MType, e: MapEntry) => [e.node, t === "pci" ? e.path : t === "usb" ? e.path ? `${e.id} (${e.path})` : e.id : e.path, t === "pci" ? e.id : null].filter(Boolean).join(" · ");
const clean = (e: MapEntry): MapEntry => ({ ...e, path: e.path || null, id: e.id || null, subsystem_id: e.subsystem_id || null, description: e.description || null });
const keep = (t: MType, e: MapEntry) => {
  const c = clean(e);
  return t === "dir" ? { node: c.node, path: c.path } : t === "usb" ? { node: c.node, id: c.id, path: c.path, description: c.description }
    : { node: c.node, path: c.path, id: c.id, iommugroup: c.iommugroup, subsystem_id: c.subsystem_id, description: c.description };
};

/** Datacenter → Resource Mappings : correspondances PCI, USB et répertoires. Utiliser une correspondance dans une VM n'est pas encore proposé. */
export function ResourceMappings({ connId }: { connId: number }) {
  const [type, setType] = useState<MType>("pci");
  const [mode, setMode] = useState<Mode | null>(null);
  const q = useQuery({ queryKey: ["mappings", connId, type], queryFn: () => api<Mapping[]>(`/api/connections/${connId}/mappings/${type}`) });
  return (
    <section className="space-y-3" aria-label={tr("Correspondances de ressources")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{tr("Correspondances de ressources")}</h2>
        <Button variant="ghost" onClick={() => setMode({ kind: "new" })}>{tr("Ajouter une correspondance…")}</Button>
      </div>
      <p className="text-sm text-muted">{tr("Une correspondance donne un nom logique à un périphérique PCI ou USB, ou à un répertoire, sur chaque nœud : une machine peut ensuite l'utiliser quel que soit le nœud où elle tourne.")}</p>
      <div role="tablist" className="flex gap-2">{MTYPES.map((t) => (
        <button key={t} role="tab" aria-selected={t === type} className={`rounded-xl border px-3 py-1.5 text-sm ${t === type ? "border-accent bg-accent/15" : "border-line bg-surface2 text-muted"}`} onClick={() => setType(t)}>{MTYPE_LABEL[t]}</button>))}</div>
      {q.error ? <Notice kind="error">{(q.error as Error).message}</Notice> : (q.data ?? []).length === 0 ? <p className="text-sm text-muted">{q.isLoading ? tr("Chargement…") : tr("Aucune correspondance {p}.", { p: MTYPE_LABEL[type] })}</p> : (
        <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[34rem] text-sm">
          <thead><tr className="border-b border-line text-left text-xs text-muted">{[tr("Nom"), tr("Description"), tr("Entrées"), ""].map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead>
          <tbody>{(q.data ?? []).map((r) => (
            <tr key={r.id} className="border-b border-line/60 align-top last:border-0">
              <td className="px-4 py-2 font-mono">{r.id}{r.type === "pci" && r.mdev ? <span className="ml-2 text-xs text-muted">{tr("mdev")}</span> : null}</td>
              <td className="px-4 py-2 text-muted">{r.description ?? ""}</td>
              <td className="px-4 py-2 font-mono text-xs text-muted">{r.map.length === 0 ? tr("illisible") : r.map.map((e, i) => <div key={i}>{summary(r.type, e)}</div>)}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMode({ kind: "edit", row: r })}>{tr("Modifier")}</button><button className="text-danger underline" onClick={() => setMode({ kind: "delete", row: r })}>{tr("Supprimer")}</button></td>
            </tr>))}</tbody></table></div>)}
      {mode && <MappingDialog connId={connId} type={type} mode={mode} onClose={() => setMode(null)} />}
    </section>
  );
}

function MappingDialog({ connId, type, mode, onClose }: { connId: number; type: MType; mode: Mode; onClose: () => void }) {
  const qc = useQueryClient();
  const k = mode.kind, row = mode.kind === "new" ? null : mode.row;
  const nodes = useQuery({ queryKey: ["nodes", connId], queryFn: () => api<NodeInfo[]>(`/api/connections/${connId}/nodes`), enabled: k !== "delete" });
  const detail = useQuery({ queryKey: ["mapping", connId, type, row?.id], queryFn: () => api<Mapping>(`/api/connections/${connId}/mappings/${type}/${row!.id}`), enabled: k === "edit" });
  const d = detail.data;
  const [id, setId] = useState(""), [desc, setDesc] = useState(""), [entries, setEntries] = useState<MapEntry[]>([]), [mdev, setMdev] = useState(false), [lmc, setLmc] = useState(false);
  const [preview, setPreview] = useState<MappingPreview | null>(null), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [done, setDone] = useState(false), [err, setErr] = useState<string | null>(null);
  const firstNode = nodes.data?.[0]?.node ?? "";
  useEffect(() => { if (k === "new" && firstNode && entries.length === 0) setEntries([emptyEntry(firstNode)]); }, [k, firstNode, entries.length]);
  useEffect(() => { if (d) { setDesc(d.description ?? ""); setEntries(d.map.map((e) => ({ ...e }))); setMdev(!!d.mdev); setLmc(!!d.live_migration_capable); } }, [d]);
  useEffect(() => { setPreview(null); setErr(null); }, [id, desc, entries, mdev, lmc]);          // retaper l'identifiant à supprimer ne réinitialise pas l'aperçu
  const setEntry = (i: number, patch: Partial<MapEntry>) => setEntries((cur) => cur.map((e, j) => (j === i ? { ...e, ...patch } : e)));

  const base = `/api/connections/${connId}/mappings/${type}`;
  const body = (extra: Record<string, unknown>) => {
    const map = entries.map((e) => keep(type, e));
    if (k === "new") return { id, description: desc || undefined, map, ...(type === "pci" ? { mdev, live_migration_capable: lmc } : {}), ...extra };
    const b: Record<string, unknown> = {}, clear: string[] = [];
    if (JSON.stringify(map) !== JSON.stringify(d!.map.map((e) => keep(type, e)))) b.map = map;
    if (desc !== (d!.description ?? "")) { if (desc) b.description = desc; else clear.push("description"); }
    if (type === "pci") {
      if (mdev !== !!d!.mdev) b.mdev = mdev;
      if (lmc !== !!d!.live_migration_capable) b.live_migration_capable = lmc;
    }
    return { ...b, ...(clear.length ? { clear } : {}), digest: d!.digest ?? undefined, ...extra };
  };
  const request = (extra: Record<string, unknown>) => k === "new" ? { path: base, init: { method: "POST", body: body(extra) } }
    : k === "edit" ? { path: `${base}/${row!.id}`, init: { method: "PUT", body: body(extra) } }
    : { path: `${base}/${row!.id}?${new URLSearchParams({ ...(extra.dry_run ? { dry_run: "true" } : { confirm: "true", type_name: typed }) })}`, init: { method: "DELETE" } };
  const look = async () => { setErr(null); try { const r = request({ dry_run: true }); setPreview(await api<MappingPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try { const r = request({}); await api(r.path, r.init); await qc.invalidateQueries({ queryKey: ["mappings", connId, type] }); setDone(true); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const used = preview?.used_by ?? [];
  const ready = !!preview && (k !== "delete" || (typed === row?.id && used.length === 0));
  const readyToLook = k === "new" ? id !== "" && entries.length > 0 : k === "edit" ? !!d && entries.length > 0 : true;
  const title = k === "new" ? tr("Ajouter une correspondance {p}", { p: MTYPE_LABEL[type] }) : k === "edit" ? `Modifier ${row!.id}` : `Supprimer ${row!.id}`;

  if (done) return <Modal title={tr("Fait")} onClose={onClose} onSubmit={onClose} submitLabel={tr("Fermer")} canSubmit><Notice kind="ok">{k === "delete" ? tr("Correspondance supprimée.") : tr("Enregistré, relu chez Proxmox.")}</Notice></Modal>;
  return (
    <Modal title={title} subtitle={tr("L'aperçu dit ce qui sera envoyé : rien n'est écrit sans lui.")} onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={k === "delete" ? tr("Supprimer") : tr("Appliquer")} danger={k === "delete"} busy={busy} error={err} canSubmit={ready} wide>
      {k === "delete" ? <>
        <Notice kind="error">{tr("Les machines qui citent")}{" "}<code>{row!.id}</code>{" "}{tr("ne pourraient plus démarrer : Kaji refuse tant qu'une VM l'utilise. Retape")}{" "}<code>{row!.id}</code>{" "}{tr("pour confirmer.")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-2" aria-label={tr("Identifiant retapé")} /></Notice>
      </> : k === "edit" && !d ? <p className="text-sm text-muted">{tr("Chargement…")}</p> : <>
        {k === "new" && <Field label={tr("Nom")} value={id} onChange={(e) => setId(e.target.value)} maxLength={64} hint={tr("Lettre puis lettres, chiffres, _ ou -")} autoComplete="off" />}
        <Field label={tr("Description")} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={500} autoComplete="off" />
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{tr("Entrées (une par nœud et par périphérique)")}</h3>
          {entries.map((e, i) => <EntryEditor key={i} connId={connId} type={type} entry={e} nodes={(nodes.data ?? []).map((n) => n.node)} onChange={(p) => setEntry(i, p)}
            onRemove={entries.length > 1 ? () => setEntries((cur) => cur.filter((_, j) => j !== i)) : undefined} />)}
          <Button type="button" variant="ghost" onClick={() => setEntries((cur) => [...cur, emptyEntry(firstNode)])} disabled={entries.length >= 32}>{tr("Ajouter une entrée")}</Button>
        </div>
        {type === "pci" && <div className="space-y-2 text-sm">
          <label className="flex gap-2"><input type="checkbox" checked={mdev} onChange={(e) => setMdev(e.target.checked)} /><span>{tr("Périphériques médiés (")}<code>{tr("mdev")}</code>{tr(", vGPU)")}</span></label>
          <label className="flex gap-2"><input type="checkbox" checked={lmc} onChange={(e) => setLmc(e.target.checked)} /><span>{tr("Migration à chaud possible (expérimental : demande un matériel et un pilote compatibles)")}</span></label>
        </div>}
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!readyToLook} onClick={look}>{tr("Aperçu")}</button>
      {preview && <div className="space-y-3 text-sm">
        {k === "delete" ? <Notice kind="ok">{tr("Sera supprimée :")}{" "}<code>{row!.id}</code>.</Notice>
          : <Notice kind="ok">{tr("Sera envoyé :")}{" "}<code>{Object.entries(preview.params ?? {}).map(([a, b]) => `${a}=${Array.isArray(b) ? b.length + tr(" entrée(s)") : String(b)}`).join(", ") || tr("rien")}</code>{preview.remove?.length ? <>{" "}{tr("· retiré :")}{" "}<code>{preview.remove.join(", ")}</code></> : null}.</Notice>}
        {used.length > 0 && <Notice kind="error">{tr("Utilisée par {p} : retire-la de ces machines avant de la supprimer.", { p: used.join(", ") })}</Notice>}
      </div>}
    </Modal>
  );
}

function EntryEditor({ connId, type, entry, nodes, onChange, onRemove }: { connId: number; type: MType; entry: MapEntry; nodes: string[]; onChange: (p: Partial<MapEntry>) => void; onRemove?: () => void }) {
  const hw = useQuery({ queryKey: ["hardware", connId, entry.node, type], enabled: type !== "dir" && !!entry.node, retry: false, staleTime: 30_000,
    queryFn: () => api<(PciDevice | UsbDevice)[]>(`/api/connections/${connId}/nodes/${entry.node}/hardware/${type}`) });
  const options = useMemo(() => (hw.data ?? []).map((x, i) => {
    if (type === "pci") { const p = x as PciDevice; return { key: String(i), label: `${p.id} · ${p.map_id}${p.device_name ? ` · ${p.device_name}` : ""}${p.iommugroup !== null ? ` · groupe IOMMU ${p.iommugroup}` : ""}`, fill: { path: p.id, id: p.map_id, iommugroup: p.iommugroup, subsystem_id: p.subsystem_id } }; }
    const u = x as UsbDevice; return { key: String(i), label: `${u.map_id}${u.product ? ` · ${u.product}` : ""}${u.map_path ? ` · port ${u.map_path}` : ""}`, fill: { id: u.map_id, path: u.map_path } };
  }), [hw.data, type]);
  return (
    <div className="space-y-3 rounded-xl border border-line p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Nœud")}</span>
          <select className="field" value={entry.node} onChange={(e) => onChange({ node: e.target.value })}>{nodes.map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
        {type !== "dir" && <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Matériel détecté sur ce nœud")}</span>
          <select className="field" value="" onChange={(e) => { const o = options.find((x) => x.key === e.target.value); if (o) onChange(o.fill); }}>
            <option value="">{hw.isLoading ? tr("Lecture…") : hw.error ? "Liste indisponible : saisie manuelle" : tr("Remplir depuis le matériel…")}</option>
            {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}</select></label>}
      </div>
      {type === "pci" && <div className="grid gap-3 sm:grid-cols-2">
        <Field label={tr("Chemin PCI")} value={entry.path ?? ""} onChange={(e) => onChange({ path: e.target.value })} placeholder="0000:00:04.0" hint={tr("Adresses séparées par « ; » pour plusieurs fonctions")} autoComplete="off" />
        <Field label={tr("Identifiant (vendeur:périphérique)")} value={entry.id ?? ""} onChange={(e) => onChange({ id: e.target.value })} placeholder="8086:1903" autoComplete="off" />
        <Field label={tr("Identifiant du sous-système (facultatif)")} value={entry.subsystem_id ?? ""} onChange={(e) => onChange({ subsystem_id: e.target.value })} placeholder={tr("103c:8767")} autoComplete="off" />
        <Field label={tr("Groupe IOMMU (facultatif)")} type="number" value={entry.iommugroup ?? ""} onChange={(e) => onChange({ iommugroup: e.target.value === "" ? null : Number(e.target.value) })} />
      </div>}
      {type === "usb" && <div className="grid gap-3 sm:grid-cols-2">
        <Field label={tr("Identifiant (vendeur:produit)")} value={entry.id ?? ""} onChange={(e) => onChange({ id: e.target.value })} placeholder={tr("0bda:b00a")} autoComplete="off" />
        <Field label={tr("Port (bus-port, facultatif)")} value={entry.path ?? ""} onChange={(e) => onChange({ path: e.target.value })} placeholder="1-13" hint={tr("Sans port, n'importe quel port convient")} autoComplete="off" />
      </div>}
      {type === "dir" && <Field label={tr("Chemin du répertoire (absolu)")} value={entry.path ?? ""} onChange={(e) => onChange({ path: e.target.value })} placeholder={tr("/srv/partage")} autoComplete="off" />}
      {type !== "dir" && <Field label={tr("Description de l'entrée (facultatif)")} value={entry.description ?? ""} onChange={(e) => onChange({ description: e.target.value })} maxLength={200} autoComplete="off" hint={tr("Sans virgule, égal ni guillemet")} />}
      {onRemove && <div className="text-right"><button type="button" className="text-xs text-danger underline" onClick={onRemove}>{tr("Retirer cette entrée")}</button></div>}
    </div>
  );
}
