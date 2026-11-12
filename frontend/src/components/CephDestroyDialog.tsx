import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { runTask } from "../lib/tasks";
import type { CephDestroyPreview, CephDestroyTarget, CephWriteResult } from "../lib/types/ceph";
import { UnvalidatedBanner } from "./CephPoolDialog";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Field, Notice } from "./ui";

import { tr } from "../lib/i18n";
const SEGMENT: Record<string, string> = { mon: "monitors", mgr: "managers", mds: "mds" };

/**
 * Détruire un pool, un OSD, un moniteur, un gestionnaire ou un MDS. Le serveur décide de tout : l'aperçu (`dry_run`) liste les REFUS (que rien ne lève) et les RISQUES ;
 * « Détruire » ne s'active que sans refus et quand le nom exact est retapé. Rien n'est supprimé sans `confirm` ni nom (vérifié côté serveur aussi).
 */
export function CephDestroyDialog({ connId, target, onClose }: { connId: number; target: CephDestroyTarget; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [cleanup, setCleanup] = useState(false), [removeStorages, setRemoveStorages] = useState(false), [typed, setTyped] = useState("");
  const [preview, setPreview] = useState<CephDestroyPreview | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);

  const url = (extra: Record<string, string>) => {
    const q = new URLSearchParams({ ...extra, ...(cleanup && target.kind === "osd" ? { cleanup: "true" } : {}), ...(removeStorages && target.kind === "pool" ? { remove_storages: "true" } : {}),
      ...(target.kind === "pool" && target.node ? { node: target.node } : {}) });
    const base = `/api/connections/${connId}/ceph`;
    const path = target.kind === "pool" ? `${base}/pools/${encodeURIComponent(target.name)}`
      : target.kind === "osd" ? `${base}/nodes/${encodeURIComponent(target.node ?? "")}/osds/${target.osdId}`
      : `${base}/nodes/${encodeURIComponent(target.node ?? "")}/${SEGMENT[target.kind]}/${encodeURIComponent(target.name)}`;
    return `${path}?${q}`;
  };

  useEffect(() => {
    let alive = true;
    setPreview(null); setTyped(""); setError(null);
    api<CephDestroyPreview>(url({ dry_run: "true" }), { method: "DELETE" }).then((p) => { if (alive) setPreview(p); }).catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cleanup, removeStorages]);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const res = await api<CephWriteResult>(url({ confirm: "true", name: typed }), { method: "DELETE" });
      const upid = res.upid;
      if (upid) await runTask(connId, res.node, async () => ({ upid }), tr("Détruire {name}", { name: target.name }), 300);
      toast("ok", tr("{name} détruit", { name: target.name }));
      await qc.invalidateQueries({ queryKey: ["ceph", connId] });
      onClose();
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  const blocked = !!preview?.blockers.length;
  const ready = !!preview && !blocked && typed === preview.expected_name;
  return (
    <Modal title={tr("Détruire {name}", { name: target.name })} subtitle={tr("Irréversible. Le serveur relit l'état de Ceph et dit ce qui bloque ou ce qui sera perdu.")} onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={tr("Détruire")} danger busy={busy} error={error} canSubmit={ready} wide>
      <UnvalidatedBanner />
      {target.kind === "osd" && <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={cleanup} onChange={(e) => setCleanup(e.target.checked)} />
        <span>{tr("Effacer aussi la table de partitions du disque (cleanup)")}</span></label>}
      {target.kind === "pool" && <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={removeStorages} onChange={(e) => setRemoveStorages(e.target.checked)} />
        <span>{tr("Retirer aussi les stockages Proxmox qui utilisent ce pool (pour tout le cluster)")}</span></label>}
      {!preview && !error && <p className="text-sm text-muted">{tr("Vérification en cours…")}</p>}
      {preview && blocked && <Notice kind="error"><b>{tr("Refusé")}</b> : <ul className="mt-1 list-disc space-y-1 pl-5">{preview.blockers.map((b) => <li key={b}>{b}</li>)}</ul></Notice>}
      {preview && preview.risks.length > 0 && <div className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn" role="alert">
        <p className="font-medium">{tr("Ce qui va se passer")}</p><ul className="list-disc space-y-1 pl-5">{preview.risks.map((r) => <li key={r}>{r}</li>)}</ul></div>}
      {preview && !blocked && <Field label={tr("Retape « {name} » pour confirmer", { name: preview.expected_name })} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoFocus />}
    </Modal>
  );
}
