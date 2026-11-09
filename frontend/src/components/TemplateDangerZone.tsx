import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createPortal } from "react-dom";
import { api, type Guest, type HwConfig } from "../lib/api";
import { DeleteGuestDialog } from "./HardwareDialogs";
import { useToast } from "./Toast";
import { Button, Notice } from "./ui";

/**
 * Supprimer un MODÈLE (VM ou LXC). La page d'un modèle n'a pas d'onglets, donc pas d'onglet Matériel : sans cette zone,
 * un modèle ne se supprimait que par l'API (essai réel, ticket #203). Même fenêtre, même nom à retaper, mêmes refus du serveur.
 */
export function TemplateDangerZone({ connId, guest, onDeleted }: { connId: number; guest: Guest; onDeleted: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const base = `/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/${guest.type}/${guest.vmid}`;
  const cfg = useQuery({ queryKey: ["hw", connId, guest.node, guest.type, guest.vmid], queryFn: () => api<HwConfig>(`${base}/config`), staleTime: 0 });
  const name = guest.name ?? String(guest.vmid);
  return (
    <section className="panel space-y-3 p-5" aria-label="Zone dangereuse">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Zone dangereuse</h2>
      {cfg.error && <Notice kind="error">{(cfg.error as Error).message} — <button className="underline" onClick={() => cfg.refetch()}>réessayer</button></Notice>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm text-muted">Détruit le modèle et ses disques « base-… », sans retour possible. Les clones complets ne sont pas touchés ; Proxmox peut refuser si des clones liés en dépendent.</span>
        <Button variant="danger" disabled={!cfg.data || guest.status !== "stopped"} onClick={() => setOpen(true)} title="Supprime le modèle et ses disques, sans retour possible" className="!px-3 !py-1">Supprimer le modèle</Button>
      </div>
      {cfg.data && open && createPortal(
        <DeleteGuestDialog cfg={cfg.data} name={name} node={guest.node} connId={connId} base={base} onClose={() => setOpen(false)}
          onDeleted={async () => { toast("ok", `Modèle « ${name} » supprimé`); await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] }); onDeleted(); }} />,
        document.body)}
    </section>
  );
}
