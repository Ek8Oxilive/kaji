import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest } from "../lib/api";
import type { MonitorCommands, MonitorResult } from "../lib/types/moniteur";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
/**
 * Onglet « Moniteur » (VM) : le moniteur QEMU en LECTURE SEULE. Seules les commandes « info … » proposées par le serveur sont
 * exécutables (jamais une commande libre) ; la VM doit être en marche. Le serveur relit l'état et nettoie la sortie.
 */
export function MonitorTab({ connId, guest, running }: { connId: number; guest: Guest; running: boolean }) {
  const base = `/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/qemu/${guest.vmid}/monitor`;
  const cmds = useQuery({ queryKey: ["monitor-commands", connId, guest.node, guest.vmid], queryFn: () => api<MonitorCommands>(base), staleTime: 300_000 });
  const [command, setCommand] = useState("info status");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<MonitorResult | null>(null);

  const run = async () => {
    setBusy(true); setErr(null);
    try {
      setResult(await api<MonitorResult>(base, { method: "POST", body: { command } }));
    } catch (e) { setErr((e as Error).message); setResult(null); }
    setBusy(false);
  };

  if (cmds.isLoading) return <div className="panel h-40 animate-pulse" />;
  if (cmds.error || !cmds.data) return <Notice kind="error">{(cmds.error as Error | null)?.message ?? tr("Commandes illisibles")} — <button className="underline" onClick={() => cmds.refetch()}>{tr("réessayer")}</button></Notice>;

  return (
    <div className="panel space-y-4 p-5">
      <div>
        <h3 className="font-semibold">{tr("Moniteur QEMU (lecture seule)")}</h3>
        <p className="text-sm text-muted">{tr("Interroge l'état de la machine avec les commandes « info » de QEMU. Aucune commande ne modifie la VM ; une commande libre n'est pas possible.")}</p>
      </div>
      {!running && <Notice kind="error">{tr("La VM doit être en marche pour interroger le moniteur.")}</Notice>}
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-60 flex-1 space-y-1.5"><span className="text-sm text-muted">{tr("Commande")}</span>
          <select className="field" value={command} onChange={(e) => setCommand(e.target.value)}>
            {cmds.data.commands.map((c) => <option key={c.command} value={c.command}>{c.command} — {tr(c.label)}</option>)}
          </select></label>
        <Button onClick={run} disabled={busy || !running}>{busy ? "…" : tr("Exécuter")}</Button>
      </div>
      {err && <Notice kind="error">{err}</Notice>}
      {result && (
        <div className="space-y-1.5">
          <p className="text-xs text-muted"><code>{result.command}</code>{result.truncated && tr(" — sortie tronquée")}</p>
          <pre className="max-h-[28rem] overflow-auto whitespace-pre rounded-xl border border-line bg-surface2 p-3 text-xs" aria-label={tr("Sortie du moniteur")}>{result.output || tr("(aucune sortie)")}</pre>
        </div>
      )}
    </div>
  );
}
