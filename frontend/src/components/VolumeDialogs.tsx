import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { LONG_TASK_SECONDS, waitTask } from "../lib/tasks";
import { Modal } from "./Modal";
import { Notice } from "./ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "–");
const path = (connId: number, node: string, storage: string) => `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/storage/${encodeURIComponent(storage)}`;

function useRefresh(connId: number, node: string, storage: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["storage-content", connId, node, storage] });
    qc.invalidateQueries({ queryKey: ["storages", connId] });
  };
}

/** Types de fichier que le serveur accepte de supprimer ici (les disques de machines et les sauvegardes ont leurs propres garde-fous). */
export const FILE_KINDS = ["iso", "vztmpl", "snippets", "import"] as const;
export type FileKind = (typeof FILE_KINDS)[number];
export const isFileKind = (c: string | null): c is FileKind => !!c && (FILE_KINDS as readonly string[]).includes(c);
/** Sauvegarde vzdump sur un stockage de fichiers (les sauvegardes d'un PBS ne se protègent pas d'ici). */
export const BACKUP_FILE = /^vzdump-(qemu|lxc)-[0-9]{3,9}-[0-9]{4}_[0-9]{2}_[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2}\.(vma|tar)(\.(zst|gz|lzo))?$/;

export function DeleteFileDialog({ connId, node, storage, kind, name, onClose }: { connId: number; node: string; storage: string; kind: FileKind; name: string; onClose: () => void }) {
  const refresh = useRefresh(connId, node, storage);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      await api(`${path(connId, node, storage)}/files/${kind}/${encodeURIComponent(name)}?confirm=true&typed=${encodeURIComponent(typed)}`, { method: "DELETE" });
      refresh(); onClose();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  return (
    <Modal title={`Supprimer ${name} ?`} onClose={onClose} onSubmit={submit} submitLabel="Supprimer" danger busy={busy} error={err} canSubmit={typed === name}>
      <Notice kind="error">Suppression définitive du fichier sur {storage}. Kaji ne vérifie pas si une machine l'utilise encore (une ISO montée, par exemple).</Notice>
      <label className="block text-xs text-muted">Retape <code>{name}</code> pour confirmer
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>
    </Modal>
  );
}

type Item = { volid: string; vmid: number | null; type: string | null; date: string | null; mark: "keep" | "remove" | "protected" | "renamed" | null };
type Preview = { items: Item[]; counts: Record<string, number>; remove: number };
const MARK: Record<string, string> = { keep: "Gardée", remove: "Supprimée", protected: "Protégée", renamed: "Nom non standard" };
const RULES = [["keep_last", "Dernières"], ["keep_hourly", "Par heure"], ["keep_daily", "Par jour"], ["keep_weekly", "Par semaine"], ["keep_monthly", "Par mois"], ["keep_yearly", "Par an"]] as const;

/** Élagage manuel en deux temps : aperçu calculé par Proxmox, puis exécution qui exige le nombre exact vu dans l'aperçu. */
export function PruneDialog({ connId, node, storage, onClose }: { connId: number; node: string; storage: string; onClose: () => void }) {
  const refresh = useRefresh(connId, node, storage);
  const [rules, setRules] = useState<Record<string, string>>({});
  const [vmid, setVmid] = useState(""), [gtype, setGtype] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const request = () => {
    const body: Record<string, unknown> = {};
    const kept = Object.entries(rules).filter(([, v]) => v.trim());
    if (kept.length) body.retention = Object.fromEntries(kept.map(([k, v]) => [k, Number(v)]));
    if (vmid.trim()) body.vmid = Number(vmid);
    if (gtype) body.guest_type = gtype;
    return body;
  };
  const changed = () => { setPreview(null); setTyped(""); setErr(null); };

  const look = async () => {
    setLoading(true); setErr(null);
    try { setPreview(await api<Preview>(`${path(connId, node, storage)}/prune/preview`, { method: "POST", body: request() })); }
    catch (e) { setErr((e as Error).message); }
    setLoading(false);
  };
  const run = async () => {
    if (!preview) return;
    setBusy(true); setErr(null);
    try {
      const { upid } = await api<{ upid: string | null }>(`${path(connId, node, storage)}/prune`, { method: "POST", body: { ...request(), confirm: true, type_name: typed, expected_remove: preview.remove } });
      if (upid) {
        const t = await waitTask(connId, node, upid, LONG_TASK_SECONDS);
        if (!t) throw new Error("L'élagage prend trop de temps (voir l'onglet Tâches)");
        if (!t.ok) throw new Error(`Élagage échoué (${t.exitstatus ?? "erreur"})`);
      }
      refresh(); onClose();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  const ready = !!preview && preview.remove > 0 && typed === storage;
  return (
    <Modal title={`Élaguer les sauvegardes de ${storage}`} subtitle="Supprime les sauvegardes qui dépassent les règles de conservation. Les sauvegardes protégées ne sont jamais touchées."
      onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel={preview ? `Supprimer ${preview.remove} sauvegarde(s)` : "Supprimer"} danger busy={busy} error={err} canSubmit={ready} wide>
      <div className="grid grid-cols-3 gap-2">
        {RULES.map(([k, l]) => (
          <label key={k} className="block space-y-1 text-sm"><span className="text-muted">{l}</span>
            <input className="field" type="number" min={1} max={9999} value={rules[k] ?? ""} onChange={(e) => { setRules({ ...rules, [k]: e.target.value }); changed(); }} /></label>
        ))}
      </div>
      <p className="text-xs text-muted">Aucune règle saisie : Proxmox applique celles du stockage.</p>
      <div className="grid grid-cols-2 gap-2">
        <label className="block space-y-1 text-sm"><span className="text-muted">Numéro de machine (facultatif)</span>
          <input className="field" type="number" min={100} value={vmid} onChange={(e) => { setVmid(e.target.value); changed(); }} /></label>
        <label className="block space-y-1 text-sm"><span className="text-muted">Type (facultatif)</span>
          <select className="field" value={gtype} onChange={(e) => { setGtype(e.target.value); changed(); }}><option value="">VM et conteneurs</option><option value="qemu">VM</option><option value="lxc">Conteneurs</option></select></label>
      </div>
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={loading || busy} onClick={look}>{loading ? "Calcul…" : "Aperçu"}</button>
      {preview && (
        <div className="space-y-3">
          <p className="text-sm">{preview.remove > 0 ? <b>{preview.remove} sauvegarde(s) seraient supprimées</b> : "Rien à supprimer avec ces règles."} · gardées : {preview.counts.keep ?? 0} · protégées : {preview.counts.protected ?? 0}{preview.counts.renamed ? ` · nom non standard (ignorées) : ${preview.counts.renamed}` : ""}</p>
          <div className="max-h-56 overflow-auto rounded-xl border border-line">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-line text-left text-muted"><th className="px-3 py-1.5 font-normal">Sauvegarde</th><th className="px-3 py-1.5 font-normal">Date</th><th className="px-3 py-1.5 font-normal">Sort</th></tr></thead>
              <tbody>{preview.items.map((i) => (
                <tr key={i.volid} className={`border-b border-line/60 last:border-0 ${i.mark === "remove" ? "text-danger" : ""}`}>
                  <td className="max-w-xs truncate px-3 py-1.5" title={i.volid}>{i.volid.split("/").pop()}</td><td className="whitespace-nowrap px-3 py-1.5">{when(i.date)}</td><td className="px-3 py-1.5">{i.mark ? MARK[i.mark] : "–"}</td>
                </tr>))}</tbody>
            </table>
          </div>
          {preview.remove > 0 && (
            <label className="block text-xs text-muted">Retape <code>{storage}</code> pour confirmer
              <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>
          )}
        </div>
      )}
    </Modal>
  );
}
