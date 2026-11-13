import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { LONG_TASK_SECONDS, runTask } from "../lib/tasks";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Button, Notice } from "./ui";

const REFERENCE = /^(?:[a-zA-Z0-9][a-zA-Z0-9.-]*(?::[0-9]+)?\/)?[a-z0-9]+(?:[._-]+[a-z0-9]+)*(?:\/[a-z0-9]+(?:[._-]+[a-z0-9]+)*)*:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/;
const FILENAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$/;

/** Télécharger une image OCI (Proxmox 9) dans un stockage de modèles : le nœud la demande à un registre sur Internet. Le serveur revérifie tout. */
export function OciPullDialog({ connId, node, storage, onClose }: { connId: number; node: string; storage: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}`;
  const [reference, setReference] = useState(""), [filename, setFilename] = useState(""), [ok, setOk] = useState(false);
  const [tags, setTags] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const repo = reference.includes(":") && !/:[0-9]+\//.test(reference) && reference.lastIndexOf(":") > reference.lastIndexOf("/") ? reference.slice(0, reference.lastIndexOf(":")) : reference;
  const valid = REFERENCE.test(reference) && (filename === "" || (FILENAME.test(filename) && !filename.includes("..")));

  const listTags = async () => {
    setErr(null); setTags(null);
    try { setTags((await api<{ tags: string[] }>(`${base}/oci/tags?reference=${encodeURIComponent(repo)}`)).tags); } catch (e) { setErr((e as Error).message); }
  };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      await runTask(connId, node, () => api<{ upid: string }>(`${base}/storage/${encodeURIComponent(storage)}/oci-pull`, { method: "POST", body: { reference, ...(filename ? { filename } : {}), confirm: true } }),
        tr("Téléchargement"), LONG_TASK_SECONDS);
      toast("ok", tr("Image « {reference} » téléchargée dans {storage}", { reference, storage }));
      qc.invalidateQueries({ queryKey: ["storage-content", connId, node, storage] });
      onClose();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  return (
    <Modal title={tr("Télécharger une image OCI")} subtitle={tr("Le nœud {node} télécharge l'image depuis un registre sur Internet, dans le stockage {storage}.", { node, storage })}
      onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel={tr("Télécharger")} busy={busy} error={err} canSubmit={valid && ok}>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Image (registre/dépôt:étiquette)")}</span>
        <input className="field" value={reference} onChange={(e) => { setReference(e.target.value.trim()); setTags(null); }} placeholder="docker.io/library/alpine:3.20" autoComplete="off" spellCheck={false} /></label>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="ghost" className="!px-3 !py-1.5" disabled={!repo || busy} onClick={listTags}>{tr("Voir les étiquettes du dépôt")}</Button>
        {tags && (tags.length === 0 ? <span className="text-sm text-muted">{tr("Aucune étiquette.")}</span>
          : <select className="field !w-auto" aria-label={tr("Étiquette")} value="" onChange={(e) => e.target.value && setReference(`${repo}:${e.target.value}`)}>
            <option value="">{tr("Choisir une étiquette…")}</option>{tags.map((t) => <option key={t} value={t}>{t}</option>)}</select>)}
      </div>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Nom du fichier (facultatif)")}</span>
        <input className="field" value={filename} onChange={(e) => setFilename(e.target.value.trim())} placeholder="alpine-3.20" autoComplete="off" /></label>
      <Notice kind="error">{tr("Les registres locaux sont refusés. Une image déjà présente dans le stockage est refusée par Proxmox. Aucun identifiant de registre n'est géré (images publiques seulement).")}</Notice>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /><span>{tr("Je veux que le nœud télécharge cette image depuis Internet")}</span></label>
    </Modal>
  );
}
