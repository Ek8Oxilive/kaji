import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "../lib/api";
import { bytes } from "../lib/format";
import { LONG_TASK_SECONDS, waitTask } from "../lib/tasks";
import { Modal } from "./Modal";
import { Notice } from "./ui";

type Kind = "iso" | "vztmpl";
const KIND_LABEL: Record<Kind, string> = { iso: "Image ISO", vztmpl: "Modèle de conteneur" };
const EXT: Record<Kind, string> = { iso: ".iso ou .img", vztmpl: ".tar.gz, .tar.xz, .tar.zst ou .tar.bz2" };
const ALGOS: Record<string, number> = { sha256: 64, sha512: 128, sha384: 96, sha224: 56, sha1: 40, md5: 32 };
const MAX_UPLOAD = 20 * 1024 ** 3;

type Target = { connId: number; node: string; storage: string; kinds: Kind[]; onClose: () => void };

function useRefresh(connId: number, storage: string, node: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["storage-content", connId, node, storage] });
    qc.invalidateQueries({ queryKey: ["storages", connId] });
  };
}

function Checksum({ algo, setAlgo, value, setValue }: { algo: string; setAlgo: (a: string) => void; value: string; setValue: (v: string) => void }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2">
      <label className="block space-y-1 text-sm"><span className="text-muted">Somme de contrôle</span>
        <select className="field" value={algo} onChange={(e) => setAlgo(e.target.value)}><option value="">aucune</option>{Object.keys(ALGOS).map((a) => <option key={a}>{a}</option>)}</select></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">&nbsp;</span>
        <input className="field" disabled={!algo} value={value} onChange={(e) => setValue(e.target.value.trim())} placeholder="Valeur attendue (hexadécimal)" autoComplete="off" /></label>
    </div>
  );
}

const sumOk = (algo: string, value: string) => !algo || (value.length === ALGOS[algo] && /^[0-9a-fA-F]+$/.test(value));

/** Téléverser un fichier du navigateur vers un stockage (envoi en flux, avec progression). */
export function UploadDialog({ connId, node, storage, kinds, onClose }: Target) {
  const refresh = useRefresh(connId, storage, node);
  const [kind, setKind] = useState<Kind>(kinds[0]);
  const [file, setFile] = useState<File | null>(null);
  const [algo, setAlgo] = useState(""), [sum, setSum] = useState("");
  const [sent, setSent] = useState<number | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const busy = sent !== null || waiting;
  const okName = !!file && /^[A-Za-z0-9][A-Za-z0-9._+()-]{0,200}$/.test(file.name) && !file.name.includes("..");
  const nameHint = file && !okName ? "Nom de fichier refusé : lettres, chiffres, . _ + ( ) - seulement ; renomme le fichier." : null;
  const tooBig = !!file && file.size > MAX_UPLOAD;

  const submit = () => {
    if (!file) return;
    setErr(null); setSent(0);
    const q = new URLSearchParams({ filename: file.name, content: kind });
    if (algo) { q.set("checksum_algorithm", algo); q.set("checksum", sum); }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/storage/${encodeURIComponent(storage)}/upload?${q}`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => setSent(e.loaded);
    xhr.onerror = () => { setErr("Envoi interrompu"); setSent(null); };
    xhr.onload = async () => {
      let body: { upid?: string; detail?: unknown } | null = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* corps illisible */ }
      if (xhr.status !== 202 || !body?.upid) {
        setErr(typeof body?.detail === "string" ? body.detail : `Erreur ${xhr.status}`); setSent(null); return;
      }
      setSent(null); setWaiting(true);
      try {
        const t = await waitTask(connId, node, body.upid, LONG_TASK_SECONDS);
        if (!t) throw new Error("L'import prend trop de temps (voir l'onglet Tâches)");
        if (!t.ok) throw new Error(`Le nœud a refusé le fichier (${t.exitstatus ?? "erreur"})`);
        refresh(); onClose();
      } catch (e) { setErr(e instanceof ApiError || e instanceof Error ? e.message : "Erreur"); setWaiting(false); }
    };
    xhr.send(file);
  };

  return (
    <Modal title={`Téléverser vers ${storage}`} subtitle={`Nœud ${node}. Le fichier passe par Kaji sans y être enregistré.`} onClose={busy ? () => {} : onClose}
      onSubmit={submit} submitLabel="Téléverser" busy={busy} error={err} canSubmit={okName && !tooBig && sumOk(algo, sum)}>
      {kinds.length > 1 && (
        <label className="block space-y-1 text-sm"><span className="text-muted">Type de fichier</span>
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>{kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></label>
      )}
      <label className="block space-y-1 text-sm"><span className="text-muted">Fichier ({EXT[kind]})</span>
        <input type="file" className="field" disabled={busy} accept={kind === "iso" ? ".iso,.img" : ".gz,.xz,.zst,.bz2"} onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      {file && <p className="text-xs text-muted">{file.name} · {bytes(file.size)}</p>}
      {nameHint && <Notice kind="error">{nameHint}</Notice>}
      {tooBig && <Notice kind="error">Fichier trop gros (20 Gio au plus).</Notice>}
      <Checksum algo={algo} setAlgo={setAlgo} value={sum} setValue={setSum} />
      {sent !== null && file && (
        <div role="progressbar" aria-valuenow={Math.round((sent / file.size) * 100)} aria-valuemin={0} aria-valuemax={100} className="space-y-1">
          <div className="h-2 overflow-hidden rounded-full bg-surface2"><div className="h-full bg-accent transition-all" style={{ width: `${(sent / file.size) * 100}%` }} /></div>
          <p className="text-xs text-muted">{bytes(sent)} / {bytes(file.size)}</p>
        </div>
      )}
      {waiting && <p className="text-sm text-muted">Envoyé. Le nœud vérifie et enregistre le fichier…</p>}
    </Modal>
  );
}

type Meta = { filename: string | null; mimetype: string | null; size: number | null };

/** Faire télécharger un fichier par le nœud depuis une URL (le fichier ne passe pas par ton navigateur). */
export function UrlDownloadDialog({ connId, node, storage, kinds, onClose }: Target) {
  const refresh = useRefresh(connId, storage, node);
  const [kind, setKind] = useState<Kind>(kinds[0]);
  const [url, setUrl] = useState(""), [name, setName] = useState("");
  const [algo, setAlgo] = useState(""), [sum, setSum] = useState("");
  const [verify, setVerify] = useState(true);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [busy, setBusy] = useState(false), [checking, setChecking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const okUrl = /^https?:\/\/\S+$/.test(url);
  const okName = /^[A-Za-z0-9][A-Za-z0-9._+()-]{0,200}$/.test(name) && !name.includes("..");

  const inspect = async () => {
    setChecking(true); setErr(null); setMeta(null);
    try {
      const m = await api<Meta>(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/url-metadata?url=${encodeURIComponent(url)}&verify_certificates=${verify}`);
      setMeta(m);
      if (!name && m.filename && /^[A-Za-z0-9][A-Za-z0-9._+()-]{0,200}$/.test(m.filename)) setName(m.filename);
    } catch (e) { setErr((e as Error).message); }
    setChecking(false);
  };

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const { upid } = await api<{ upid: string }>(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/storage/${encodeURIComponent(storage)}/download-url`, {
        method: "POST", body: { url, filename: name, content: kind, verify_certificates: verify, ...(algo ? { checksum_algorithm: algo, checksum: sum } : {}) } });
      const t = await waitTask(connId, node, upid, LONG_TASK_SECONDS);
      if (!t) throw new Error("Le téléchargement prend trop de temps (voir l'onglet Tâches)");
      if (!t.ok) throw new Error(`Téléchargement échoué (${t.exitstatus ?? "erreur"})`);
      refresh(); onClose();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  return (
    <Modal title={`Télécharger vers ${storage}`} subtitle={`Le nœud ${node} télécharge le fichier lui-même.`} onClose={busy ? () => {} : onClose}
      onSubmit={submit} submitLabel="Télécharger" busy={busy} error={err} canSubmit={okUrl && okName && sumOk(algo, sum)}>
      {kinds.length > 1 && (
        <label className="block space-y-1 text-sm"><span className="text-muted">Type de fichier</span>
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>{kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></label>
      )}
      <label className="block space-y-1 text-sm"><span className="text-muted">Adresse (http ou https)</span>
        <div className="flex gap-2">
          <input className="field" value={url} onChange={(e) => { setUrl(e.target.value.trim()); setMeta(null); }} placeholder="https://…/debian.iso" autoComplete="off" />
          <button type="button" className="rounded-xl border border-line bg-surface2 px-3 text-sm disabled:opacity-50" disabled={!okUrl || checking || busy} onClick={inspect}>{checking ? "…" : "Vérifier"}</button>
        </div>
        <span className="block text-xs text-muted">Les adresses locales (127.0.0.1, localhost…) sont refusées.</span></label>
      {meta && <p className="text-xs text-muted">Trouvé : {meta.filename ?? "nom inconnu"} · {meta.size != null ? bytes(meta.size) : "taille inconnue"} · {meta.mimetype ?? "type inconnu"}</p>}
      <label className="block space-y-1 text-sm"><span className="text-muted">Nom du fichier ({EXT[kind]})</span>
        <input className="field" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" /></label>
      <Checksum algo={algo} setAlgo={setAlgo} value={sum} setValue={setSum} />
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} /><span>Vérifier le certificat du site</span></label>
      {!verify && <Notice kind="error">Sans vérification du certificat, le fichier peut venir d'un autre serveur que celui annoncé : utilise une somme de contrôle.</Notice>}
      {busy && <p className="text-sm text-muted">Téléchargement en cours sur le nœud… (suivi aussi dans l'onglet Tâches)</p>}
    </Modal>
  );
}
