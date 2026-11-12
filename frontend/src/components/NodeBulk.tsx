import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ClusterStatus, Guest } from "../lib/api";
import { BULK_LABEL } from "../lib/types/groupees";
import type { BulkAction, BulkPlan, BulkResult } from "../lib/types/groupees";
import { Modal } from "./Modal";
import { Button, Notice } from "./ui";

/**
 * Actions groupées d'un nœud : démarrer, arrêter ou migrer une SÉLECTION de machines (jamais « toutes » : la liste est explicite), avec aperçu `dry_run`
 * avant toute écriture, machines protégées refusées par le serveur, nom du nœud retapé. Sur un nœud hors ligne : Wake-on-LAN (nom retapé).
 */
export function NodeBulk({ connId, node, online }: { connId: number; node: string; online: boolean }) {
  const [open, setOpen] = useState(false), [wake, setWake] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  return (
    <div className="space-y-2">
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" disabled={!online} onClick={() => { setMsg(null); setOpen(true); }} className="!px-3 !py-1.5" title="Démarrer, arrêter ou migrer plusieurs machines de ce nœud en une fois">Actions groupées…</Button>
        <Button variant="ghost" disabled={online} onClick={() => { setMsg(null); setWake(true); }} className="!px-3 !py-1.5" title="Envoie un paquet Wake-on-LAN : seulement pour un nœud hors ligne">Réveiller le nœud…</Button>
      </div>
      {open && <BulkDialog connId={connId} node={node} onClose={() => setOpen(false)} onDone={(t) => { setMsg({ kind: "ok", text: t }); setOpen(false); }} />}
      {wake && <WakeDialog connId={connId} node={node} onClose={() => setWake(false)} onDone={(t) => { setMsg({ kind: "ok", text: t }); setWake(false); }} />}
    </div>
  );
}

function BulkDialog({ connId, node, onClose, onDone }: { connId: number; node: string; onClose: () => void; onDone: (t: string) => void }) {
  const url = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/bulk`;
  const guests = useQuery({ queryKey: ["guests", connId], queryFn: () => api<Guest[]>(`/api/connections/${connId}/guests`) });
  const cluster = useQuery({ queryKey: ["cluster-status", connId], queryFn: () => api<ClusterStatus>(`/api/connections/${connId}/cluster/status`) });
  const mine = (guests.data ?? []).filter((g) => g.node === node && !g.template && g.vmid !== null).sort((a, b) => (a.vmid ?? 0) - (b.vmid ?? 0));
  const others = (cluster.data?.nodes ?? []).filter((n) => n.online && n.name !== node);
  const [action, setAction] = useState<BulkAction>("startall"), [picked, setPicked] = useState<number[]>([]), [target, setTarget] = useState("");
  const [forceStop, setForceStop] = useState(false), [timeout, setTimeoutS] = useState("180"), [localDisks, setLocalDisks] = useState(false), [workers, setWorkers] = useState("1");
  const [plan, setPlan] = useState<BulkPlan | null>(null), [typed, setTyped] = useState(""), [accept, setAccept] = useState(false);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  useEffect(() => { setPlan(null); setErr(null); setAccept(false); }, [action, picked, target, forceStop, timeout, localDisks, workers]);   // retaper le nom ne réinitialise pas l'aperçu

  const body = (extra: Record<string, unknown>) => ({
    action, vmids: picked, ...(action === "stopall" ? { force_stop: forceStop, timeout: Number(timeout) || 180 } : {}),
    ...(action === "migrateall" ? { target, with_local_disks: localDisks, max_workers: Number(workers) || 1 } : {}), ...extra,
  });
  const look = async () => { setErr(null); try { setPlan(await api<BulkPlan>(url, { method: "POST", body: body({ dry_run: true }) })); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api<BulkResult>(url, { method: "POST", body: body({ confirm: true, type_name: typed, accept_running: accept }) });
      onDone(`${BULK_LABEL[action]} : ${r.vmids.length} machine(s) demandée(s) à Proxmox${r.upid ? " (tâche lancée)" : ""}. L'avancement est dans la page « Tâches ».`);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const needName = action !== "startall";
  const ready = !!plan && !plan.blocked && !busy && (!needName || typed === node) && (!plan.needs_accept_running || accept);
  const sel = (label: string, v: string, set: (s: string) => void, opts: [string, string][]) => (
    <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span><select className="field" value={v} onChange={(e) => set(e.target.value)}>{opts.map(([a, b]) => <option key={a} value={a}>{b}</option>)}</select></label>);

  return (
    <Modal title={`Actions groupées sur « ${node} »`} subtitle="Choisis les machines : rien n'est envoyé sans aperçu, et jamais « toutes les machines »." onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={BULK_LABEL[action]} danger={action !== "startall"} busy={busy} error={err} canSubmit={ready} wide>
      {sel("Action", action, (s) => setAction(s as BulkAction), [["startall", "Démarrer les machines choisies"], ["stopall", "Arrêter les machines choisies"], ["migrateall", "Migrer les machines choisies vers un autre nœud"]])}
      <fieldset className="space-y-1 text-sm"><legend className="text-muted">Machines de ce nœud ({picked.length} choisie(s))</legend>
        <div className="max-h-48 space-y-1 overflow-y-auto rounded-xl border border-line p-2">
          {guests.isLoading ? <p className="text-muted">Chargement…</p> : mine.length === 0 ? <p className="text-muted">Aucune machine sur ce nœud.</p> : mine.map((g) => (
            <label key={g.vmid} className="flex items-center gap-2"><input type="checkbox" checked={picked.includes(g.vmid!)} onChange={() => toggle(g.vmid!)} />
              <span className="font-mono text-xs text-muted">{g.type === "lxc" ? "ct" : "vm"}:{g.vmid}</span><span>{g.name ?? ""}</span>
              <span className="ml-auto text-xs text-muted">{g.status === "running" ? "en marche" : g.status === "paused" ? "en pause" : "arrêtée"}</span></label>))}
        </div>
      </fieldset>
      {action === "stopall" && <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={forceStop} onChange={(e) => setForceStop(e.target.checked)} /><span>Forcer l'arrêt après le délai</span></label>
        <label className="block space-y-1 text-sm"><span className="text-muted">Délai (secondes)</span><input className="field" type="number" min={10} max={7200} value={timeout} onChange={(e) => setTimeoutS(e.target.value)} /></label>
      </div>}
      {action === "migrateall" && <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {sel("Nœud cible", target, setTarget, [["", others.length ? "Choisir un nœud" : "Aucun autre nœud en ligne"], ...others.map((n) => [n.name, n.name] as [string, string])])}
        <label className="block space-y-1 text-sm"><span className="text-muted">Migrations en parallèle (1 à 8)</span><input className="field" type="number" min={1} max={8} value={workers} onChange={(e) => setWorkers(e.target.value)} /></label>
        <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={localDisks} onChange={(e) => setLocalDisks(e.target.checked)} /><span>Copier aussi les disques locaux</span></label>
      </div>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={picked.length === 0 || (action === "migrateall" && !target)} onClick={look}>Aperçu</button>
      {plan && (
        <div className="space-y-3 text-sm">
          {plan.blocked && <Notice kind="error"><b>Bloqué</b> : {plan.blocked}.</Notice>}
          {plan.apply.length > 0 && <p><b>{plan.apply.length} machine(s) concernée(s)</b> : <span className="text-muted">{plan.apply.map((g) => `${g.name ?? "#" + g.vmid} (${g.vmid})`).join(", ")}</span></p>}
          {plan.skipped.length > 0 && <p className="text-muted">Ignorées : {plan.skipped.map((g) => `${g.name ?? "#" + g.vmid} (${g.reason})`).join(", ")}.</p>}
          {!plan.blocked && plan.needs_accept_running && <Notice kind="error"><label className="flex gap-2"><input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
            <span>{plan.running.length} machine(s) en marche seront migrées à chaud (les conteneurs sont redémarrés). Je confirme.</span></label></Notice>}
          {!plan.blocked && needName && <label className="block text-xs text-muted">Retape <code>{node}</code> pour confirmer
            <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>}
        </div>)}
    </Modal>
  );
}

function WakeDialog({ connId, node, onClose, onDone }: { connId: number; node: string; onClose: () => void; onDone: (t: string) => void }) {
  const [typed, setTyped] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try { await api(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/wakeonlan`, { method: "POST", body: { confirm: true, type_name: typed } }); onDone(`Paquet Wake-on-LAN demandé pour « ${node} » : il peut mettre quelques minutes à apparaître en ligne.`); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  return (
    <Modal title={`Réveiller « ${node} » ?`} subtitle="Wake-on-LAN : l'adresse MAC doit être déclarée dans la configuration du nœud chez Proxmox." onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel="Réveiller" busy={busy} error={err} canSubmit={typed === node && !busy}>
      <label className="block text-xs text-muted">Retape <code>{node}</code> pour confirmer<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>
    </Modal>
  );
}
