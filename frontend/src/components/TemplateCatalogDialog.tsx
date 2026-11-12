import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type LxcTemplates } from "../lib/api";
import { LONG_TASK_SECONDS, runTask } from "../lib/tasks";
import type { TemplateDownloadBody } from "../lib/types/modeles-lxc";
import { useToast } from "./Toast";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
/**
 * Télécharger un modèle de conteneur du catalogue OFFICIEL de Proxmox (aucune URL libre) vers un stockage de modèles.
 * Le serveur relit le catalogue et le stockage, et refuse (422) un nom hors catalogue ou (409) un modèle déjà présent.
 */
export function TemplateCatalogDialog({ connId, node, storage, onClose }: { connId: number; node: string; storage?: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}`;
  const tpls = useQuery({ queryKey: ["lxc-templates", connId, node], queryFn: () => api<LxcTemplates>(`${base}/templates`), staleTime: 30_000 });
  const [target, setTarget] = useState(storage ?? "");
  const [q, setQ] = useState(""), [section, setSection] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { if (!target && tpls.data?.storages.length) setTarget(tpls.data.storages[0]); }, [tpls.data, target]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const items = tpls.data?.downloadable ?? [];
  const sections = useMemo(() => [...new Set(items.map((a) => a.section).filter((s): s is string => !!s))].sort(), [items]);
  const present = useMemo(() => new Set((tpls.data?.local ?? []).filter((l) => l.storage === target).map((l) => l.name)), [tpls.data, target]);
  // Par défaut, seulement l'architecture du nœud : un modèle arm64 serait inutilisable sur un nœud amd64 (essai réel, ticket #205).
  const [allArch, setAllArch] = useState(false);
  const nodeArch = tpls.data?.node_architecture ?? null;
  const otherArch = nodeArch !== null && items.some((a) => a.architecture && a.architecture !== nodeArch);
  const shown = items.filter((a) => (section === "all" || a.section === section)
    && (allArch || nodeArch === null || !a.architecture || a.architecture === nodeArch)
    && `${a.template} ${a.os ?? ""} ${a.description ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()));

  const download = async (template: string) => {
    setBusy(template); setErr(null);
    try {
      const body: TemplateDownloadBody = { storage: target, template };
      await runTask(connId, node, () => api<{ upid: string }>(`${base}/aplinfo`, { method: "POST", body }), tr("Téléchargement"), LONG_TASK_SECONDS);
      toast("ok", tr("Modèle « {template} » téléchargé dans {target}", { template, target }));
      await qc.invalidateQueries({ queryKey: ["lxc-templates", connId, node] });
      qc.invalidateQueries({ queryKey: ["storage-content", connId, node, target] });
    } catch (e) { setErr((e as Error).message); }
    setBusy(null);
  };

  return (
    <div className="fixed inset-0 z-[70] grid place-items-center bg-black/60 p-4" onClick={busy ? undefined : onClose}>
      <div role="dialog" aria-modal="true" aria-label={tr("Télécharger un modèle de conteneur")} className="panel rise flex max-h-[88vh] w-full max-w-2xl flex-col gap-4 p-6" onClick={(e) => e.stopPropagation()}>
        <div>
          <h2 className="text-lg font-semibold">{tr("Télécharger un modèle de conteneur")}</h2>
          <p className="text-sm text-muted">{tr("Catalogue officiel de Proxmox, vers un stockage de modèles du nœud {node}. Proxmox vérifie les sommes de contrôle.", { node })}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block text-xs text-muted">{tr("Stockage")}<select className="field mt-1" value={target} onChange={(e) => setTarget(e.target.value)} disabled={!!storage || !!busy}>
              {(storage ? [storage] : tpls.data?.storages ?? []).map((s) => <option key={s}>{s}</option>)}
            </select></label>
          <label className="block text-xs text-muted">{tr("Section")}<select className="field mt-1" value={section} onChange={(e) => setSection(e.target.value)}>
              <option value="all">{tr("Toutes")}</option>{sections.map((s) => <option key={s}>{s}</option>)}
            </select></label>
          <label className="block text-xs text-muted">{tr("Recherche")}<input className="field mt-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr("alpine, debian, turnkey…")} /></label>
        </div>
        {otherArch && (
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={allArch} onChange={(e) => setAllArch(e.target.checked)} />{tr("Afficher aussi les autres architectures (ce nœud est en {nodeArch})", { nodeArch })}</label>
        )}
        {tpls.isLoading && <p className="text-sm text-muted">{tr("Chargement du catalogue…")}</p>}
        {tpls.isError && <Notice kind="error">{tr("Liste indisponible : {message}", { message: (tpls.error as Error).message })}</Notice>}
        {tpls.isSuccess && tpls.data.downloadable === null && <Notice kind="error">{tr("Catalogue indisponible : le nœud n'a pas pu le lire (droits ou accès Internet).")}</Notice>}
        {tpls.isSuccess && tpls.data.storages.length === 0 && <Notice kind="error">{tr("Aucun stockage de ce nœud n'accepte les modèles de conteneur.")}</Notice>}
        {err && <Notice kind="error">{err}</Notice>}
        <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto rounded-xl border border-line">
          {shown.map((a) => (
            <li key={a.template} className="flex items-center justify-between gap-3 p-3 text-sm">
              <div className="min-w-0">
                <p className="truncate font-medium">{a.template}</p>
                <p className="truncate text-xs text-muted">{[a.section, a.architecture, a.description].filter(Boolean).join(" · ")}</p>
              </div>
              {present.has(a.template)
                ? <span className="shrink-0 text-xs text-muted">{tr("Déjà présent")}</span>
                : <Button variant="ghost" className="!px-3 !py-1.5" disabled={!!busy || !target} onClick={() => download(a.template)}>{busy === a.template ? tr("En cours…") : tr("Télécharger")}</Button>}
            </li>
          ))}
          {tpls.isSuccess && shown.length === 0 && tpls.data.downloadable !== null && <li className="p-3 text-sm text-muted">{tr("Aucun modèle ne correspond.")}</li>}
        </ul>
        <div className="flex justify-end"><Button variant="ghost" onClick={onClose} disabled={!!busy}>{tr("Fermer")}</Button></div>
      </div>
    </div>
  );
}
