import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { runTask } from "../lib/tasks";
import { Button, Notice } from "./ui";

export type VolumeKind = "lvm" | "lvmthin" | "directory" | "zfs";
const KIND: Record<VolumeKind, string> = { lvm: "le groupe LVM", lvmthin: "le pool LVM-thin", directory: "le répertoire", zfs: "le pool ZFS" };

/** Supprimer un volume VIDE. Le serveur relit tout (contenu, stockages, disques système) et refuse si le volume n'est pas vide. */
export function DiskDeleteDialog({ connId, node, kind, name, vg, onClose }: { connId: number; node: string; kind: VolumeKind; name: string; vg?: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [typed, setTyped] = useState("");
  const [cleanConfig, setCleanConfig] = useState(true);
  const [cleanDisks, setCleanDisks] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      await runTask(connId, node, () => api(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/disks/${kind}/${encodeURIComponent(name)}/delete`,
        { method: "POST", body: { confirm: true, type_name: typed, vg, cleanup_config: cleanConfig, cleanup_disks: cleanDisks } }), "Suppression", 600);
      qc.invalidateQueries({ queryKey: ["node-disks", connId, node] });
      qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
      qc.invalidateQueries({ queryKey: ["storages"] });
      onClose();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4" onClick={busy ? undefined : onClose}>
      <div role="dialog" aria-modal="true" aria-label={`Supprimer ${name}`} className="panel rise w-full max-w-md space-y-4 p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold">Supprimer {KIND[kind]} « {name} » sur {node} ?</h2>
        <Notice kind="error">Action destructive. Kaji ne supprime qu'un volume <b>vide</b> et jamais un volume système : s'il contient des disques de machines, des sauvegardes ou d'autres données, supprime-les d'abord dans Proxmox.</Notice>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={cleanConfig} onChange={(e) => setCleanConfig(e.target.checked)} /><span>Retirer aussi les stockages Proxmox qui l'utilisent</span></label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={cleanDisks} onChange={(e) => setCleanDisks(e.target.checked)} /><span>Effacer ensuite les disques (signatures et partitions)</span></label>
        <label className="block text-xs text-muted">Retape <code>{name}</code> pour confirmer
          <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg" /></label>
        {err && <Notice kind="error">{err}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Annuler</Button>
          <Button variant="danger" onClick={submit} disabled={busy || typed !== name}>{busy ? "En cours…" : "Supprimer"}</Button>
        </div>
      </div>
    </div>
  );
}
