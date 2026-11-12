import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { CONTENT_LABEL, KINDS, type FieldDef, type StorageConfig, type StorageKind } from "../lib/types/stockage-config";
import { Modal } from "./Modal";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
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
        <span className="text-muted">{f.label}{f.required && !editing ? " *" : ""}{locked ? tr(" (non modifiable)") : ""}</span>
        {f.kind === "select"
          ? <select className="field" value={String(values[f.key])} onChange={(e) => set(f.key, e.target.value)}><option value="">{tr("(par défaut)")}</option>{f.options!.map((o) => <option key={o}>{o}</option>)}</select>
          : <input className="field" type={f.kind === "password" ? "password" : f.kind === "number" ? "number" : "text"} min={f.kind === "number" ? 1 : undefined} max={f.kind === "number" ? 65535 : undefined} autoComplete="off" disabled={locked}
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
      <fieldset className="space-y-1.5"><legend className="text-sm text-muted">{tr("Contenu autorisé *")}</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {KINDS[kind].contents.map((c) => (
            <label key={c} className="flex gap-1.5 text-sm"><input type="checkbox" checked={content.includes(c)}
              onChange={(e) => setContent(e.target.checked ? [...content, c] : content.filter((x) => x !== c))} />{CONTENT_LABEL[c] ?? c}</label>
          ))}
        </div></fieldset>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Nœuds concernés")}</span>
        <input className="field" value={nodes} onChange={(e) => setNodes(e.target.value)} placeholder={tr("Tous les nœuds")} />
        <span className="block text-xs text-muted">{tr("Noms séparés par des virgules ; vide = tous.")}</span></label>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={disable} onChange={(e) => setDisable(e.target.checked)} /><span>{tr("Désactiver ce stockage")}</span></label>
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
  const [encrypt, setEncrypt] = useState(false);
  const [issuedKey, setIssuedKey] = useState<string | null>(null);
  const done = useDone(connId, onClose);
  const pick = (k: StorageKind) => { setKind(k); setSt(initial(k)); setErr(null); setEncrypt(false); };
  const set = (k: string, v: string | boolean) => setSt((s) => ({ ...s, values: { ...s.values, [k]: v } }));
  const missing = KINDS[kind].fields.some((f) => f.required && !String(st.values[f.key]).trim());
  const ok = NAME.test(name) && !missing && st.content.length > 0;

  const submit = async () => {
    setBusy(true); setErr(null);
    const body: Record<string, unknown> = { storage: name, type: kind, content: st.content };
    for (const f of KINDS[kind].fields) {
      const v = st.values[f.key];
      if (f.kind === "bool") { if (v === true) body[f.key] = true; }
      else if (String(v).trim()) body[f.key] = f.kind === "list" ? csv(String(v)) : f.kind === "number" ? Number(v) : String(v).trim();
    }
    if (csv(st.nodes).length) body.nodes = csv(st.nodes);
    if (st.disable) body.disable = true;
    if (kind === "pbs" && encrypt) body.encryption_key = "autogen";
    try {
      const r = await api<{ encryption_key?: string }>(base(connId), { method: "POST", body });
      if (r.encryption_key) { setIssuedKey(r.encryption_key); setBusy(false); } else done();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  if (issuedKey) return <KeyDialog storage={name} secret={issuedKey} onDone={done} />;
  return (
    <Modal title={tr("Ajouter un stockage")} subtitle={tr("Ajoute le stockage à la configuration du cluster ; aucune donnée existante n'est touchée.")}
      onClose={onClose} onSubmit={submit} submitLabel={tr("Ajouter")} busy={busy} error={err} canSubmit={ok}>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Type")}</span>
        <select className="field" value={kind} onChange={(e) => pick(e.target.value as StorageKind)}>
          {(Object.keys(KINDS) as StorageKind[]).map((k) => <option key={k} value={k}>{KINDS[k].label}</option>)}</select></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Identifiant *")}</span>
        <input className="field" value={name} autoComplete="off" onChange={(e) => setName(e.target.value)} />
        <span className="block text-xs text-muted">{tr("Lettres, chiffres, - et _ (40 caractères au plus).")}</span></label>
      <Inputs kind={kind} editing={false} values={st.values} set={set} />
      {kind === "pbs" && (
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={encrypt} onChange={(e) => setEncrypt(e.target.checked)} />
          <span>{tr("Chiffrer les sauvegardes (Proxmox génère une clé, affichée une seule fois)")}</span></label>
      )}
      <Common kind={kind} content={st.content} setContent={(content) => setSt((s) => ({ ...s, content }))} nodes={st.nodes}
        setNodes={(nodes) => setSt((s) => ({ ...s, nodes }))} disable={st.disable} setDisable={(disable) => setSt((s) => ({ ...s, disable }))} />
    </Modal>
  );
}

/** Clé de chiffrement PBS : affichée UNE seule fois. Sans elle, les sauvegardes chiffrées sont perdues. On ne ferme qu'après confirmation. */
function KeyDialog({ storage, secret, onDone }: { storage: string; secret: string; onDone: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => { try { await navigator.clipboard.writeText(secret); setCopied(true); } catch { /* le texte reste sélectionnable */ } };
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4">
      <div role="dialog" aria-modal="true" aria-label={tr("Clé de chiffrement")} className="panel rise w-full max-w-lg space-y-4 p-6">
        <h2 className="text-lg font-semibold">{tr("Clé de chiffrement de {storage}", { storage })}</h2>
        <Notice kind="error">{tr("Garde cette clé en lieu sûr (gestionnaire de mots de passe). Elle ne sera")}{" "}<b>{tr("plus jamais affichée")}</b>{" "}{tr(": sans elle, les sauvegardes chiffrées de ce stockage sont irrécupérables.")}</Notice>
        <textarea readOnly rows={4} value={secret} onFocus={(e) => e.currentTarget.select()} className="field font-mono text-xs" aria-label={tr("Clé de chiffrement")} />
        <div className="flex items-center justify-between gap-3">
          <Button type="button" variant="ghost" onClick={copy}>{copied ? tr("Copiée") : tr("Copier")}</Button>
          <label className="flex gap-2 text-sm"><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /><span>{tr("J'ai conservé la clé")}</span></label>
        </div>
        <div className="flex justify-end"><Button type="button" onClick={onDone} disabled={!saved}>{tr("Terminer")}</Button></div>
      </div>
    </div>
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
      else if (!String(v).trim()) { if (["options", "domain", "subdir", "namespace", "fingerprint"].includes(f.key)) reset.push(f.key); }
      else body[f.key] = f.kind === "list" ? csv(String(v)) : f.kind === "number" ? Number(v) : String(v).trim();
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
    <Modal title={tr("Modifier {storage}", { storage: cfg.storage })} subtitle={tr("{label} : le type, le chemin et le serveur ne se changent pas après la création.", { label: KINDS[kind].label })}
      onClose={onClose} onSubmit={submit} submitLabel={tr("Enregistrer")} busy={busy} error={err} canSubmit={st.content.length > 0}>
      {cfg.secrets_set?.length ? <p className="text-xs text-muted">{tr("Secret défini : {p} (non affiché).", { p: cfg.secrets_set.join(", ") })}</p> : null}
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
    <Modal title={tr("Retirer {storage} ?", { storage })} onClose={onClose} onSubmit={submit} submitLabel={tr("Retirer")} danger busy={busy} error={err} canSubmit={typed === storage}>
      <Notice kind="error">{tr("Le stockage est retiré de la configuration du cluster. Les fichiers restent sur le disque, mais les machines, ISO et sauvegardes qui l'utilisent ne le trouveront plus.")}</Notice>
      <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{storage}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>
    </Modal>
  );
}
