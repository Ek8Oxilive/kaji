import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { PowerAction, PowerCheck } from "../lib/types/alimentation";
import { Button, Notice } from "./ui";

import { tr, T } from "../lib/i18n";
const LABEL: Record<PowerAction, [string, string]> = { reboot: [T("Redémarrer le nœud"), T("Redémarrer")], shutdown: [T("Éteindre le nœud"), T("Éteindre")] };

/** Boutons + boîte de confirmation forte : conséquences lues auprès de Proxmox, nom du nœud retapé, cases à cocher si nécessaire. */
export function NodePower({ connId, node, online }: { connId: number; node: string; online: boolean }) {
  const [action, setAction] = useState<PowerAction | null>(null);
  const [typed, setTyped] = useState("");
  const [guests, setGuests] = useState(false);
  const [quorum, setQuorum] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const url = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/power`;
  const check = useQuery({ queryKey: ["node-power", connId, node], enabled: action !== null, staleTime: 0, gcTime: 0, queryFn: () => api<PowerCheck>(url) });
  useEffect(() => { if (!action) { setTyped(""); setGuests(false); setQuorum(false); } }, [action]);
  const c = check.data;
  const blocked = !!c && c.protected_running.length > 0;
  const ready = !!c && !busy && !blocked && typed === node && (c.running_guests.length === 0 || guests) && (!c.quorum_loss || quorum);

  const send = async () => {
    if (!action) return;
    setBusy(true);
    try {
      await api(url, { method: "POST", body: { action, confirm: true, type_name: typed, accept_guests: guests, accept_quorum_loss: quorum } });
      setMsg({ kind: "ok", text: action === "reboot" ? tr("Redémarrage de « {node} » demandé : le nœud va devenir injoignable quelques minutes.", { node }) : tr("Arrêt de « {node} » demandé. Il faudra le rallumer à la main.", { node }) });
      setAction(null);
    } catch (e) { setMsg({ kind: "error", text: (e as Error).message }); setAction(null); }
    setBusy(false);
  };

  return (
    <div className="space-y-2">
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" disabled={!online} onClick={() => { setMsg(null); setAction("reboot"); }} className="!px-3 !py-1.5">{tr("Redémarrer le nœud")}</Button>
        <Button variant="danger" disabled={!online} onClick={() => { setMsg(null); setAction("shutdown"); }} className="!px-3 !py-1.5">{tr("Éteindre le nœud")}</Button>
      </div>
      {action && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4" onClick={() => setAction(null)}>
          <div role="dialog" aria-modal="true" aria-label={tr(LABEL[action][0])} className="panel rise w-full max-w-md space-y-4 p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">{tr(LABEL[action][0])} « {node} » ?</h2>
            {check.isLoading ? <div className="h-16 animate-pulse rounded bg-surface2" />
              : check.error || !c ? <Notice kind="error">{tr("Impossible de lire l'état du cluster : l'action est refusée par précaution.")}</Notice>
              : <div className="space-y-3 text-sm text-muted">
                {blocked && <Notice kind="error">{tr("Machine protégée en marche sur ce nœud ({p}) : arrête-la ou migre-la d'abord.", { p: c.protected_running.join(", ") })}</Notice>}
                {c.running_guests.length > 0 && (
                  <label className="flex gap-2"><input type="checkbox" checked={guests} onChange={(e) => setGuests(e.target.checked)} />
                    <span>{tr("{length} machine(s) en marche seront arrêtées : {p}.", { length: c.running_guests.length, p: c.running_guests.map((g) => `${g.name ?? "#" + g.vmid} (${g.vmid})`).join(", ") })}</span></label>)}
                {c.quorum_loss && (
                  <label className="flex gap-2"><input type="checkbox" checked={quorum} onChange={(e) => setQuorum(e.target.checked)} />
                    <span>{tr("Les {nodes_online_after} nœud(s) restant(s) perdront le", { nodes_online_after: c.nodes_online_after })}{" "}<b>{tr("quorum")}</b>{" "}{tr(": plus de démarrage de machine ni de changement de configuration tant que ce nœud ne revient pas.")}</span></label>)}
                {action === "shutdown" && <p>{tr("Un nœud éteint ne se rallume pas depuis Kaji (Wake-on-LAN ou bouton physique).")}</p>}
                <label className="block text-xs">{tr("Retape")}{" "}<code>{node}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg" /></label>
              </div>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setAction(null)}>{tr("Annuler")}</Button>
              <Button variant="danger" onClick={send} disabled={!ready}>{busy ? "…" : tr(LABEL[action][1])}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
