import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Guest } from "../lib/api";
import { PTYPES, PTYPE_LABEL, PTYPE_ONE, triOf, triVal, type PtDevice, type PtForm, type PtMapping, type PtPreview, type PtState, type PType, type Tri } from "../lib/types/passthrough";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

type Mode = { kind: "add"; type: PType } | { kind: "edit"; type: PType; dev: PtDevice } | { kind: "remove"; type: PType; dev: PtDevice };
const yn = (v: boolean | null | undefined, label: string) => (v === true ? `${label}` : v === false ? `sans ${label}` : null);

function describe(d: PtDevice): string {
  if (d.raw) return `${d.host ?? "?"} (hôte brut : réservé à root, non modifiable ici)`;
  const bits = [yn(d.pcie, "PCIe"), yn(d.rombar, "ROM"), yn(d.x_vga, "VGA principal"), d.mdev ? `mdev ${d.mdev}` : null, yn(d.usb3, "USB 3"),
    d.cache ? `cache ${d.cache}` : null, yn(d.direct_io, "E/S directes"), yn(d.expose_acl, "ACL"), yn(d.expose_xattr, "xattr")].filter(Boolean);
  return bits.join(" · ");
}

/** Périphériques PCI, USB et répertoires d'une VM, par CORRESPONDANCE du datacenter. Les périphériques « bruts » sont affichés mais jamais modifiés. */
export function PassthroughPanel({ connId, guest }: { connId: number; guest: Guest }) {
  const base = `/api/connections/${connId}/guests/${guest.node}/qemu/${guest.vmid}/passthrough`;
  const [mode, setMode] = useState<Mode | null>(null);
  const q = useQuery({ queryKey: ["passthrough", connId, guest.node, guest.vmid], queryFn: () => api<PtState>(base), staleTime: 0 });
  return (
    <section className="space-y-3" aria-label="Périphériques par correspondance">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Périphériques PCI, USB et répertoires</h3>
      <p className="text-sm text-muted">Un périphérique s'ajoute par une <b>correspondance</b> du datacenter (page Datacenter) : Proxmox ne l'accorde pas autrement à Kaji. Les changements ne s'appliquent qu'après un arrêt complet de la machine.</p>
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}
      {q.data?.running && <Notice kind="error">La machine tourne : les changements restent « en attente » jusqu'à son arrêt complet.</Notice>}
      {q.isLoading ? <p className="text-sm text-muted">Chargement…</p> : q.data && PTYPES.map((t) => (
        <div key={t} className="rounded-xl border border-line px-4">
          <div className="flex items-center justify-between py-2"><span className="text-sm font-medium">{PTYPE_LABEL[t]}</span>
            <Button variant="ghost" className="!px-3 !py-1" onClick={() => setMode({ kind: "add", type: t })}>+ Ajouter</Button></div>
          {q.data[t].length === 0 && <p className="pb-3 text-sm text-muted">Aucun.</p>}
          {q.data[t].map((d) => (
            <div key={d.key} className="flex items-center gap-3 border-t border-line/60 py-3 text-sm">
              <div className="w-24 shrink-0 font-mono text-xs text-muted">{d.key}</div>
              <div className="min-w-0 flex-1"><span className="font-mono">{d.mapping ?? "—"}</span> <span className="text-muted">{describe(d)}</span>
                {q.data.pending.includes(d.key) && <div className="mt-1 inline-block rounded-md bg-warn/15 px-2 py-0.5 text-xs text-warn">En attente</div>}</div>
              {!d.raw && <div className="flex gap-1.5"><Button variant="ghost" className="!px-3 !py-1" onClick={() => setMode({ kind: "edit", type: t, dev: d })}>Modifier</Button>
                <Button variant="danger" className="!px-3 !py-1" onClick={() => setMode({ kind: "remove", type: t, dev: d })}>Retirer</Button></div>}
            </div>))}
        </div>))}
      {mode && <PassthroughDialog connId={connId} guest={guest} base={base} mode={mode} machine={q.data?.machine ?? null} onClose={() => setMode(null)} />}
    </section>
  );
}

function PassthroughDialog({ connId, guest, base, mode, machine, onClose }: { connId: number; guest: Guest; base: string; mode: Mode; machine: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const t = mode.type, k = mode.kind, dev = mode.kind === "add" ? null : mode.dev;
  const mappings = useQuery({ queryKey: ["mappings", connId, t], queryFn: () => api<PtMapping[]>(`/api/connections/${connId}/mappings/${t}`), enabled: k !== "remove" });
  const [f, setF] = useState<PtForm>({ mapping: "", pcie: "", rombar: "", x_vga: "", mdev: "", usb3: "", cache: "", direct_io: "", expose_acl: "", expose_xattr: "" });
  const [preview, setPreview] = useState<PtPreview | null>(null), [busy, setBusy] = useState(false), [done, setDone] = useState(false), [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (dev) setF({ mapping: dev.mapping ?? "", pcie: triOf(dev.pcie), rombar: triOf(dev.rombar), x_vga: triOf(dev.x_vga), mdev: dev.mdev ?? "", usb3: triOf(dev.usb3), cache: dev.cache ?? "",
      direct_io: triOf(dev.direct_io), expose_acl: triOf(dev.expose_acl), expose_xattr: triOf(dev.expose_xattr) });
  }, [dev]);
  useEffect(() => { setPreview(null); setErr(null); }, [f]);
  const set = <K extends keyof PtForm>(key: K) => (v: PtForm[K]) => setF((cur) => ({ ...cur, [key]: v }));
  const body = (extra: Record<string, unknown>) => {
    const b: Record<string, unknown> = { mapping: f.mapping };
    if (t === "pci") Object.assign(b, { pcie: triVal(f.pcie), rombar: triVal(f.rombar), x_vga: triVal(f.x_vga), mdev: f.mdev || undefined });
    if (t === "usb") b.usb3 = triVal(f.usb3);
    if (t === "dir") Object.assign(b, { cache: f.cache || undefined, direct_io: triVal(f.direct_io), expose_acl: triVal(f.expose_acl), expose_xattr: triVal(f.expose_xattr) });
    return { ...b, ...extra };
  };
  const request = (dry: boolean) => k === "add" ? { path: `${base}/${t}`, init: { method: "POST", body: body(dry ? { dry_run: true } : {}) } }
    : k === "edit" ? { path: `${base}/${t}/${dev!.key}`, init: { method: "PUT", body: body(dry ? { dry_run: true } : {}) } }
    : { path: `${base}/${t}/${dev!.key}?${dry ? "dry_run=true" : "confirm=true"}`, init: { method: "DELETE" } };
  const look = async () => { setErr(null); try { const r = request(true); setPreview(await api<PtPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try { const r = request(false); await api(r.path, r.init); await qc.invalidateQueries({ queryKey: ["passthrough", connId, guest.node, guest.vmid] }); await qc.invalidateQueries({ queryKey: ["hw", connId, guest.node, guest.type, guest.vmid] }); setDone(true); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const tri = (label: string, key: "pcie" | "rombar" | "x_vga" | "usb3" | "direct_io" | "expose_acl" | "expose_xattr", hint?: string) => (
    <label className="block space-y-1.5 text-sm"><span className="text-muted">{label}</span>
      <select className="field" value={f[key]} onChange={(e) => set(key)(e.target.value as Tri)}><option value="">Défaut de Proxmox</option><option value="yes">Oui</option><option value="no">Non</option></select>
      {hint && <span className="block text-xs text-muted">{hint}</span>}</label>);
  const chosen = mappings.data?.find((m) => m.id === f.mapping);
  const title = k === "add" ? `Ajouter un ${PTYPE_ONE[t]}` : k === "edit" ? `Modifier ${dev!.key}` : `Retirer ${dev!.key}`;
  if (done) return <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit><Notice kind="ok">{k === "remove" ? "Périphérique retiré de la configuration." : "Enregistré, relu chez Proxmox."} Les changements s'appliquent après un arrêt complet de la machine.</Notice></Modal>;
  return (
    <Modal title={title} subtitle="L'aperçu dit ce qui sera écrit dans la configuration de la VM." onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel={k === "remove" ? "Retirer" : "Appliquer"}
      danger={k === "remove"} busy={busy} error={err} canSubmit={!!preview} wide>
      {k === "remove" ? <Notice kind="error">Retire <code>{dev!.key}</code> (<code>{dev!.mapping}</code>) de la configuration de la machine ; le périphérique lui-même et la correspondance ne sont pas touchés.</Notice> : <>
        <label className="block space-y-1.5 text-sm"><span className="text-muted">Correspondance</span>
          <select className="field" value={f.mapping} onChange={(e) => set("mapping")(e.target.value)}><option value="">Choisir une correspondance</option>
            {(mappings.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.id}{m.description ? ` · ${m.description}` : ""}{m.map.some((e) => e.node === guest.node) ? "" : ` (aucune entrée pour ${guest.node})`}</option>)}</select>
          {(mappings.data ?? []).length === 0 && !mappings.isLoading && <span className="block text-xs text-muted">Aucune correspondance {PTYPE_ONE[t]} : crée-en une dans la page Datacenter.</span>}</label>
        {t === "pci" && <><div className="grid gap-4 sm:grid-cols-3">{tri("PCIe", "pcie", machine?.startsWith("q35") ? undefined : "Demande le type de machine q35")}{tri("ROM de la carte", "rombar")}{tri("Carte graphique principale", "x_vga")}</div>
          {chosen?.mdev && <Field label="Type de périphérique médié (mdev)" value={f.mdev} onChange={(e) => set("mdev")(e.target.value)} placeholder="nvidia-63" autoComplete="off" />}</>}
        {t === "usb" && tri("USB 3", "usb3")}
        {t === "dir" && <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5 text-sm"><span className="text-muted">Cache</span><select className="field" value={f.cache} onChange={(e) => set("cache")(e.target.value)}><option value="">Défaut de Proxmox</option>{["always", "auto", "metadata", "never"].map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
          {tri("E/S directes", "direct_io")}{tri("Exposer les ACL", "expose_acl")}{tri("Exposer les attributs étendus", "expose_xattr")}</div>}
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={k !== "remove" && !f.mapping} onClick={look}>Aperçu</button>
      {preview && <div className="space-y-3 text-sm">
        <Notice kind="ok">{k === "remove" ? <>Sera retiré : <code>{preview.remove}</code>.</> : <>Sera écrit : <code>{preview.key} = {preview.value}</code>.</>}</Notice>
        {(preview.warnings ?? []).map((w) => <Notice key={w} kind="error">{w}.</Notice>)}
        {preview.running && <Notice kind="error">La machine tourne : le changement restera en attente jusqu'à son arrêt complet.</Notice>}
      </div>}
    </Modal>
  );
}
