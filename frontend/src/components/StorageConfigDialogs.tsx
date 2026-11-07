import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { CONTENT_LABEL, KINDS, type FieldDef, type StorageConfig, type StorageKind } from "../lib/types/stockage-config";
import { Modal } from "./Modal";
import { Notice } from "./ui";

type Values = Record<string, string | boolean>;
const NAME = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;
const csv = (s: string) => s.split(/[,\s;]+/).map((x) => x.trim()).filter(Boolean);
const asList = (v: unknown) => (Array.isArray(v) ? (v as string[]).join(", ") : "");

function initial(kind: StorageKind, cfg?: StorageConfig): { values: Values; content: string[]; nodes: string; disable: boolean } {
  const values: Values = {};
  for (const f of KINDS[kind].fields) {
    const v = cfg?.[f.key];
    values[f.key] = f.kind === "bool" ? v === true : f.kind === "list" ? asList(v) : f.kind === "password" ? "" : typeof v === "string" ? v : "";
  }
  return { values, content: cfg?.content ?? [], nodes: asList(cfg?.nodes), disable: cfg?.disable === true };
}

function Inputs({ kind, editing, values, set }: { kind: StorageKind; editing: boolean; values: Values; set: (k: string, v: string | boolean) => void }) {
  const input = (f: FieldDef) => {
    const locked = editing && f.create;                  // champ de création : Proxmox refuse de le changer ensuite
    if (f.kind === "bool") return (
      <label key={f.key} className="flex gap-2 text-sm"><input type="checkbox" disabled={locked} checked={values[f.key] === true} onChange={(e) => set(f.key, e.target.checked)} /><span>{f.label}</span></label>
    );
    return (
      <label key={f.key} className="block space-y-1 text-sm">
        <span className="text-muted">{f.label}{f.required && !editing ? " *" : ""}{locked ? " (non modifiable)" : ""}</span>
        {f.kind === "select"
          ? <select className="field" value={String(values[f.key])} onChange={(e) => set(f.key, e.target.value)}><option value="">(par défaut)</option>{f.options!.map((o) => <option key={o}>{o}</option>)}</select>
          : <input className="field" type={f.kind === "password" ? "password" : "text"} autoComplete="off" disabled={locked}
              value={String(values[f.key])} onChange={(e) => set(f.key, e.target.value)} />}
        {f.hint && <span className="block text-xs text-muted">{f.hint}</span>}
      </label>
    );
  };
  return <>{KINDS[kind].fields.map(input)}</>;
}

function Common({ kind, content, setContent, nodes, setNodes, disable, setDisable }: {
  kind: StorageKind; content: string[]; setContent: (c: string[]) => void; nodes: string; setNodes: (n: string) => void; disable: boolean; setDisable: (d: boolean) => void;
}) {
  return (
    <>
      <fieldset className="space-y-1.5"><legend className="text-sm text-muted">Contenu autorisé *</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {KINDS[kind].contents.map((c) => (
            <label key={c} className="flex gap-1.5 text-sm"><input type="checkbox" checked={content.includes(c)}
              onChange={(e) => setContent(e.target.checked ? [...content, c] : content.filter((x) => x !== c))} />{CONTENT_LABEL[c] ?? c}</label>
          ))}
        </div></fieldset>
      <label className="block space-y-1 text-sm"><span className="text-muted">Nœuds concernés</span>
        <input className="field" value={nodes} onChange={(e) => setNodes(e.target.value)} placeholder="Tous les nœuds" />
        <span className="block text-xs text-muted">Noms séparés par des virgules ; vide = tous.</span></label>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={disable} onChange={(e) => setDisable(e.target.checked)} /><span>Désactiver ce stockage</span></label>
    </>
  );
}

function useDone(connId: number, onClose: () => void) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["storages", connId] });
    qc.invalidateQueries({ queryKey: ["storage-config", connId] });
    onClose();
  };
}

const base = (connId: number) => `/api/connections/${connId}/storage-config`;

export function AddStorageDialog({ connId, onClose }: { connId: number; onClose: () => void }) {
  const [kind, setKind] = useState<StorageKind>("dir");
  const [name, setName] = useState("");
  const [st, setSt] = useState(() => initial("dir"));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const done = useDone(connId, onClose);
  const pick = (k: StorageKind) => { setKind(k); setSt(initial(k)); setErr(null); };
  const set = (k: string, v: string | boolean) => setSt((s) => ({ ...s, values: { ...s.values, [k]: v } }));
  const missing = KINDS[kind].fields.some((f) => f.required && !String(st.values[f.key]).trim());
  const ok = NAME.test(name) && !missing && st.content.length > 0;

  const submit = async () => {
    setBusy(true); setErr(null);
    const body: Record<string, unknown> = { storage: name, type: kind, content: st.content };
    for (const f of KINDS[kind].fields) {
      const v = st.values[f.key];
      if (f.kind === "bool") { if (v === true) body[f.key] = true; }
      else if (String(v).trim()) body[f.key] = f.kind === "list" ? csv(String(v)) : String(v).trim();
    }
    if (csv(st.nodes).length) body.nodes = csv(st.nodes);
    if (st.disable) body.disable = true;
    try { await api(base(connId), { method: "POST", body }); done(); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  return (
    <Modal title="Ajouter un stockage" subtitle="Ajoute le stockage à la configuration du cluster ; aucune donnée existante n'est touchée."
      onClose={onClose} onSubmit={submit} submitLabel="Ajouter" busy={busy} error={err} canSubmit={ok}>
      <label className="block space-y-1 text-sm"><span className="text-muted">Type</span>
        <select className="field" value={kind} onChange={(e) => pick(e.target.value as StorageKind)}>
          {(Object.keys(KINDS) as StorageKind[]).map((k) => <option key={k} value={k}>{KINDS[k].label}</option>)}</select></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">Identifiant *</span>
        <input className="field" value={name} autoComplete="off" onChange={(e) => setName(e.target.value)} />
        <span className="block text-xs text-muted">Lettres, chiffres, - et _ (40 caractères au plus).</span></label>
      <Inputs kind={kind} editing={false} values={st.values} set={set} />
      <Common kind={kind} content={st.content} setContent={(content) => setSt((s) => ({ ...s, content }))} nodes={st.nodes}
        setNodes={(nodes) => setSt((s) => ({ ...s, nodes }))} disable={st.disable} setDisable={(disable) => setSt((s) => ({ ...s, disable }))} />
    </Modal>
  );
}

export function EditStorageDialog({ connId, cfg, onClose }: { connId: number; cfg: StorageConfig; onClose: () => void }) {
  const kind = cfg.type as StorageKind;
  const [st, setSt] = useState(() => initial(kind, cfg));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const done = useDone(connId, onClose);
  const set = (k: string, v: string | boolean) => setSt((s) => ({ ...s, values: { ...s.values, [k]: v } }));
  const orig = initial(kind, cfg);

  const submit = async () => {
    setBusy(true); setErr(null);
    const body: Record<string, unknown> = {};
    const reset: string[] = [];
    for (const f of KINDS[kind].fields.filter((f) => !f.create)) {
      const v = st.values[f.key];
      if (f.kind === "password") { if (String(v)) body[f.key] = String(v); continue; }
      if (v === orig.values[f.key]) continue;
      if (f.kind === "bool") body[f.key] = v === true;
      else if (!String(v).trim()) { if (["options", "domain", "subdir", "namespace"].includes(f.key)) reset.push(f.key); }
      else body[f.key] = f.kind === "list" ? csv(String(v)) : String(v).trim();
    }
    if (st.content.join() !== orig.content.join()) body.content = st.content;
    if (st.nodes !== orig.nodes) { if (csv(st.nodes).length) body.nodes = csv(st.nodes); else reset.push("nodes"); }
    if (st.disable !== orig.disable) body.disable = st.disable;
    if (reset.length) body.reset = reset;
    if (cfg.digest) body.digest = cfg.digest;
    try { await api(`${base(connId)}/${encodeURIComponent(cfg.storage)}`, { method: "PUT", body }); done(); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  return (
    <Modal title={`Modifier ${cfg.storage}`} subtitle={`${KINDS[kind].label} : le type, le chemin et le serveur ne se changent pas après la création.`}
      onClose={onClose} onSubmit={submit} submitLabel="Enregistrer" busy={busy} error={err} canSubmit={st.content.length > 0}>
      {cfg.secrets_set?.length ? <p className="text-xs text-muted">Secret défini : {cfg.secrets_set.join(", ")} (non affiché).</p> : null}
      <Inputs kind={kind} editing values={st.values} set={set} />
      <Common kind={kind} content={st.content} setContent={(content) => setSt((s) => ({ ...s, content }))} nodes={st.nodes}
        setNodes={(nodes) => setSt((s) => ({ ...s, nodes }))} disable={st.disable} setDisable={(disable) => setSt((s) => ({ ...s, disable }))} />
    </Modal>
  );
}

export function DeleteStorageDialog({ connId, storage, onClose }: { connId: number; storage: string; onClose: () => void }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const done = useDone(connId, onClose);
  const submit = async () => {
    setBusy(true); setErr(null);
    try { await api(`${base(connId)}/${encodeURIComponent(storage)}?confirm=true&name=${encodeURIComponent(typed)}`, { method: "DELETE" }); done(); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  return (
    <Modal title={`Retirer ${storage} ?`} onClose={onClose} onSubmit={submit} submitLabel="Retirer" danger busy={busy} error={err} canSubmit={typed === storage}>
      <Notice kind="error">Le stockage est retiré de la configuration du cluster. Les fichiers restent sur le disque, mais les machines, ISO et sauvegardes qui l'utilisent ne le trouveront plus.</Notice>
      <label className="block text-xs text-muted">Retape <code>{storage}</code> pour confirmer
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>
    </Modal>
  );
}
