import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type { Guest } from "../lib/api";
import type { FwNode } from "../lib/types/reseau";
import { FwObjectsDialog } from "./FwObjectsDialog";
import { FwOptionsDialog } from "./FwOptionsDialog";
import { FwRulesDialog } from "./FwRulesDialog";
import { Options, Rules } from "./FwViews";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
type Open = "options" | "rules" | "objects" | null;

/**
 * Onglet « Pare-feu » d'une machine (VM ou LXC, M7) : options, règles, alias et IPSets de CETTE machine, avec les mêmes fenêtres, aperçus et verrous que la page « Réseau ».
 * Aucune route nouvelle : `GET /firewall/guests/{node}/{gtype}/{vmid}`, puis les routes d'écriture de la machine.
 */
export function FirewallTab({ connId, guest }: { connId: number; guest: Guest }) {
  const [open, setOpen] = useState<Open>(null);
  const target = { gtype: guest.type, vmid: guest.vmid };
  const fw = useQuery({ queryKey: ["fw-guest", connId, guest.node, guest.type, guest.vmid], staleTime: 0,
    queryFn: () => api<FwNode>(`/api/connections/${connId}/firewall/guests/${encodeURIComponent(guest.node)}/${guest.type}/${guest.vmid}`) });
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">{tr("Le pare-feu d'une machine ne filtre que ses cartes réseau dont la case « firewall » est cochée (onglet Matériel), et seulement si le pare-feu du datacenter est activé. Un pare-feu non activé ne filtre rien, même avec des règles.")}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" onClick={() => setOpen("options")}>{tr("Options…")}</Button>
        <Button variant="ghost" onClick={() => setOpen("rules")}>{tr("Règles…")}</Button>
        <Button variant="ghost" onClick={() => setOpen("objects")}>{tr("Alias et IPSets…")}</Button>
      </div>
      {fw.error ? <Notice kind="error">{(fw.error as Error).message}</Notice> : fw.isLoading ? <div className="panel h-24 animate-pulse" /> : fw.data && <>
        <section className="space-y-2"><h3 className="text-sm font-semibold">{tr("Options")}</h3><Options o={fw.data.options} /></section>
        <section className="space-y-2"><h3 className="text-sm font-semibold">{tr("Règles")}</h3><Rules rules={fw.data.rules} /></section></>}
      {open === "options" && <FwOptionsDialog connId={connId} node={guest.node} guest={target} onClose={() => setOpen(null)} />}
      {open === "rules" && <FwRulesDialog connId={connId} node={guest.node} guest={target} onClose={() => setOpen(null)} />}
      {open === "objects" && <FwObjectsDialog connId={connId} guest={{ node: guest.node, ...target }} onClose={() => setOpen(null)} />}
    </div>
  );
}
