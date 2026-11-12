import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type { FwNode } from "../lib/types/reseau";
import { FwOptionsDialog } from "./FwOptionsDialog";
import { FwRulesDialog } from "./FwRulesDialog";
import { Options, Rules } from "./FwViews";
import { Button, Notice } from "./ui";

/**
 * Section « Pare-feu » de la page d'un nœud (M7) : options et règles de CE nœud, avec les mêmes fenêtres, aperçus et verrous que la page « Réseau »
 * (elles s'ouvrent déjà réglées sur le nœud). Aucune route nouvelle : `GET /firewall/nodes/{node}`, puis les routes d'écriture du nœud.
 * Activer le pare-feu d'un nœud peut couper l'accès au cluster : le verrou « coupure possible » reste exigé par le serveur.
 */
export function NodeFirewall({ connId, node }: { connId: number; node: string }) {
  const [open, setOpen] = useState<"options" | "rules" | null>(null);
  const fw = useQuery({ queryKey: ["fw-node", connId, node], staleTime: 15_000,
    queryFn: () => api<FwNode>(`/api/connections/${connId}/firewall/nodes/${encodeURIComponent(node)}`) });
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">Le pare-feu d'un nœud filtre le trafic vers le nœud lui-même (administration, console, migration), seulement si le pare-feu du datacenter est activé. Un pare-feu non activé ne filtre rien, même avec des règles.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" onClick={() => setOpen("options")}>Options…</Button>
        <Button variant="ghost" onClick={() => setOpen("rules")}>Règles…</Button>
      </div>
      {fw.error ? <Notice kind="error">{(fw.error as Error).message}</Notice> : fw.isLoading ? <div className="panel h-24 animate-pulse" /> : fw.data && <>
        <section className="space-y-2"><h3 className="text-sm font-semibold">Options</h3><Options o={fw.data.options} /></section>
        <section className="space-y-2"><h3 className="text-sm font-semibold">Règles</h3><Rules rules={fw.data.rules} /></section></>}
      {open === "options" && <FwOptionsDialog connId={connId} node={node} startAt="node" onClose={() => setOpen(null)} />}
      {open === "rules" && <FwRulesDialog connId={connId} node={node} startAt="node" onClose={() => setOpen(null)} />}
    </div>
  );
}
