import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { isErr, type FwRule } from "../lib/types/reseau";
import { Modal } from "./Modal";
import { Notice } from "./ui";

const PHRASE = "COUPURE POSSIBLE";
type Scope = "cluster" | "node" | "guest" | "group";
type Locks = { cut: string[]; live: string[]; inert: boolean };
type Op = { label: string; method: "POST" | "PUT" | "DELETE"; path: string; body: Record<string, unknown> };
const EMPTY = { type: "in", action: "ACCEPT", proto: "", dport: "", source: "", dest: "", macro: "", comment: "", enable: false };

/** Règles du pare-feu : ajouter, activer/désactiver, déplacer, supprimer. Chaque action passe par un aperçu (dry_run) des verrous décidés par le serveur. */
export function FwRulesDialog({ connId, node, onClose, guest, startAt }: { connId: number; node: string; onClose: () => void; guest?: { gtype: "qemu" | "lxc"; vmid: number }; startAt?: "node" }) {
  const qc = useQueryClient();
  const [scope, setScope] = useState<Scope>(guest ? "guest" : startAt ?? "cluster");
  const [vmid, setVmid] = useState(guest ? String(guest.vmid) : ""), [gtype, setGtype] = useState<"qemu" | "lxc">(guest?.gtype ?? "qemu"), [group, setGroup] = useState("");
  const [f, setF] = useState(EMPTY);
  const [op, setOp] = useState<Op | null>(null), [locks, setLocks] = useState<Locks | null>(null);
  const [ackLive, setAckLive] = useState(false), [ackCut, setAckCut] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [msg, setMsg] = useState<string | null>(null);

  const root = `/api/connections/${connId}/firewall`;
  const ready = scope === "cluster" || scope === "node" || (scope === "guest" && /^\d{3,9}$/.test(vmid)) || (scope === "group" && /^[A-Za-z][A-Za-z0-9_-]{1,17}$/.test(group));
  const wPath = scope === "cluster" ? "/cluster" : scope === "node" ? `/nodes/${encodeURIComponent(node)}` : scope === "guest" ? `/guests/${encodeURIComponent(node)}/${gtype}/${vmid}` : `/groups/${group}`;
  const rPath = scope === "group" ? `/cluster/groups/${group}` : scope === "cluster" ? "/cluster" : wPath;
  const rules = useQuery({
    queryKey: ["fw-rules", connId, rPath], enabled: ready,
    queryFn: async () => { const r = await api<FwRule[] | { rules: FwRule[] | { error: string } }>(`${root}${rPath}`); const x = Array.isArray(r) ? r : r.rules; if (!Array.isArray(x)) throw new Error(isErr(x) ? x.error : "Règles illisibles"); return x; },
  });
  const reset = () => { setOp(null); setLocks(null); setAckLive(false); setAckCut(false); setTyped(""); setErr(null); };
  const url = (o: Op, extra: Record<string, unknown>) => o.method === "DELETE" ? `${root}${o.path}?${new URLSearchParams(Object.entries({ confirm: true, ...extra }).map(([k, v]) => [k, String(v)]))}` : `${root}${o.path}`;
  const call = (o: Op, extra: Record<string, unknown>) => api<{ locks: Locks }>(url(o, extra), { method: o.method, ...(o.method === "DELETE" ? {} : { body: { ...o.body, ...extra } }) });

  const start = async (o: Op) => {
    reset(); setMsg(null); setOp(o);
    try { setLocks((await call(o, { dry_run: true })).locks); } catch (e) { setErr((e as Error).message); setOp(null); }
  };
  const run = async () => {
    if (!op) return;
    setBusy(true); setErr(null);
    try {
      await call(op, { confirm: true, ...(ackLive ? { acknowledge_live: true } : {}), ...(ackCut ? { acknowledge_cut_access: true, type_name: typed } : {}) });
      await qc.invalidateQueries({ queryKey: ["fw-rules"] }); await qc.invalidateQueries({ queryKey: ["fw-cluster", connId] }); await qc.invalidateQueries({ queryKey: ["fw-node", connId] });
      setMsg(`${op.label} : fait, relu chez Proxmox.`); reset();
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const cut = !!locks?.cut.length, live = !!locks?.live.length;
  const ok = !!op && !!locks && (!cut || (ackCut && typed === PHRASE)) && (!live || cut || ackLive);
  const clean = () => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "" && v !== undefined));
  const list = rules.data ?? [];

  return (
    <Modal title="Règles du pare-feu" subtitle="Chaque action montre d'abord ses verrous ; rien n'est écrit sans ton accord explicite." wide onClose={busy ? () => {} : onClose}
      onSubmit={run} submitLabel={op ? `Appliquer : ${op.label}` : "Appliquer"} danger={cut || live} busy={busy} error={err} canSubmit={ok}>
      {guest && <p className="text-sm text-muted">Machine {guest.gtype === "qemu" ? "VM" : "LXC"} {guest.vmid} sur {node}.</p>}
      {!guest && <div className="flex flex-wrap gap-2 text-sm">
        <select aria-label="Niveau" className="field !w-auto" value={scope} onChange={(e) => { setScope(e.target.value as Scope); reset(); }}>
          <option value="cluster">Datacenter</option><option value="node">Nœud {node}</option><option value="guest">Machine</option><option value="group">Groupe de sécurité</option></select>
        {scope === "guest" && <><select aria-label="Type" className="field !w-auto" value={gtype} onChange={(e) => setGtype(e.target.value as "qemu" | "lxc")}><option value="qemu">VM</option><option value="lxc">LXC</option></select>
          <input aria-label="Identifiant" placeholder="vmid" className="field !w-28" value={vmid} onChange={(e) => setVmid(e.target.value)} /></>}
        {scope === "group" && <input aria-label="Groupe" placeholder="nom du groupe" className="field !w-44" value={group} onChange={(e) => setGroup(e.target.value)} />}
      </div>}
      {msg && <Notice kind="ok">{msg}</Notice>}
      {rules.error && <Notice kind="error">{(rules.error as Error).message}</Notice>}
      {ready && !rules.error && (list.length === 0 ? <p className="text-sm text-muted">Aucune règle.</p> : (
        <ul className="space-y-1 text-sm">{list.map((r, i) => (
          <li key={r.pos} className={`flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-1.5 ${r.enable === false ? "opacity-50" : ""}`}>
            <span className="tabular-nums text-muted">{r.pos}</span><span>{r.type}</span>
            <b className={r.action === "ACCEPT" ? "text-ok" : r.action === "DROP" || r.action === "REJECT" ? "text-danger" : ""}>{r.action}</b>
            <span className="text-muted">{[r.macro ?? r.proto, r.source && `de ${r.source}`, r.dest && `vers ${r.dest}`, r.dport && `port ${r.dport}`, r.comment].filter(Boolean).join(" · ")}</span>
            <span className="ml-auto flex gap-1">
              <button type="button" className="rounded border border-line px-2" onClick={() => start({ label: `${r.enable ? "désactiver" : "activer"} #${r.pos}`, method: "PUT", path: `${wPath}/rules/${r.pos}`, body: { enable: !r.enable } })}>{r.enable ? "Désactiver" : "Activer"}</button>
              <button type="button" aria-label="Monter" disabled={i === 0} className="rounded border border-line px-2 disabled:opacity-30" onClick={() => start({ label: `monter #${r.pos}`, method: "PUT", path: `${wPath}/rules/${r.pos}/move`, body: { moveto: r.pos - 1 } })}>↑</button>
              <button type="button" aria-label="Descendre" disabled={i === list.length - 1} className="rounded border border-line px-2 disabled:opacity-30" onClick={() => start({ label: `descendre #${r.pos}`, method: "PUT", path: `${wPath}/rules/${r.pos}/move`, body: { moveto: r.pos + 1 } })}>↓</button>
              <button type="button" className="rounded border border-danger/50 px-2 text-danger" onClick={() => start({ label: `supprimer #${r.pos}`, method: "DELETE", path: `${wPath}/rules/${r.pos}`, body: {} })}>Supprimer</button>
            </span>
          </li>))}</ul>))}
      {ready && (
        <fieldset className="space-y-2 rounded-xl border border-line p-3 text-sm"><legend className="px-1 text-muted">Nouvelle règle (ajoutée en tête, désactivée sauf si tu coches « active »)</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <select aria-label="Sens" className="field" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>{(scope === "group" ? ["in", "out"] : scope === "guest" ? ["in", "out", "group"] : ["in", "out", "forward", "group"]).map((t) => <option key={t}>{t}</option>)}</select>
            <input aria-label="Action" className="field" list="fw-actions" value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })} /><datalist id="fw-actions"><option>ACCEPT</option><option>DROP</option><option>REJECT</option></datalist>
            <input aria-label="Protocole" placeholder="proto (tcp…)" className="field" value={f.proto} onChange={(e) => setF({ ...f, proto: e.target.value })} />
            <input aria-label="Port de destination" placeholder="port dest." className="field" value={f.dport} onChange={(e) => setF({ ...f, dport: e.target.value })} />
            <input aria-label="Source" placeholder="source" className="field" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} />
            <input aria-label="Destination" placeholder="destination" className="field" value={f.dest} onChange={(e) => setF({ ...f, dest: e.target.value })} />
            <input aria-label="Macro" placeholder="macro (SSH…)" className="field" value={f.macro} onChange={(e) => setF({ ...f, macro: e.target.value })} />
            <input aria-label="Commentaire" placeholder="commentaire" className="field" value={f.comment} onChange={(e) => setF({ ...f, comment: e.target.value })} />
          </div>
          <label className="flex gap-2"><input type="checkbox" checked={f.enable} onChange={(e) => setF({ ...f, enable: e.target.checked })} />Règle active</label>
          <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2" disabled={!f.action} onClick={() => start({ label: "ajouter une règle", method: "POST", path: `${wPath}/rules`, body: clean() })}>Aperçu des verrous</button>
        </fieldset>)}
      {op && locks && (
        <div className="space-y-3 text-sm">
          {locks.inert && <Notice kind="ok">Aucun verrou : le pare-feu concerné est désactivé, la règle ne s'appliquera qu'à son activation.</Notice>}
          {live && !cut && <Notice kind="error">{locks.live.join(" ; ")}.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ackLive} onChange={(e) => setAckLive(e.target.checked)} /><span>Je comprends que la modification s'applique tout de suite</span></label></Notice>}
          {cut && <Notice kind="error"><b>Coupure d'accès possible</b> : {locks.cut.join(" ; ")}.
            <label className="mt-2 flex gap-2"><input type="checkbox" checked={ackCut} onChange={(e) => setAckCut(e.target.checked)} /><span>Je comprends que cela peut couper l'accès à Proxmox et à Kaji</span></label>
            <label className="mt-2 block text-xs">Retape <code>{PHRASE}</code><input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label></Notice>}
        </div>)}
    </Modal>
  );
}
