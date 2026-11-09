import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { NetIface } from "../lib/types/reseau";
import { Modal } from "./Modal";
import { Notice } from "./ui";

const PHRASE = "COUPURE POSSIBLE";
type Locks = { cut: string[]; live: string[]; inert: boolean };
type Preview = { locks: Locks; changes?: string | null };
export type NetMode = { kind: "create" } | { kind: "edit"; iface: NetIface } | { kind: "delete"; iface: NetIface } | { kind: "apply" } | { kind: "revert" };
const BOND_MODES = ["", "balance-rr", "active-backup", "balance-xor", "broadcast", "802.3ad", "balance-tlb", "balance-alb", "balance-slb", "lacp-balance-slb", "lacp-balance-tcp"];

/** Réseau d'un nœud : préparer (en attente), appliquer, annuler. Chaque action montre d'abord ses verrous ; appliquer recharge le réseau du nœud, sans retour arrière automatique. */
export function NetWriteDialog({ connId, node, mode, ifaces, pendingDiff, onClose }: { connId: number; node: string; mode: NetMode; ifaces: NetIface[]; pendingDiff: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const edit = mode.kind === "edit" ? mode.iface : null;
  const [type, setType] = useState<"bridge" | "bond" | "vlan">("bridge");
  const [name, setName] = useState(""), [cidr, setCidr] = useState(edit?.cidr ?? ""), [gw, setGw] = useState(edit?.gateway ?? ""), [mtu, setMtu] = useState(edit?.mtu ? String(edit.mtu) : "");
  const [comments, setComments] = useState(edit?.comments ?? ""), [ports, setPorts] = useState((edit?.bridge_ports ?? edit?.slaves ?? []).join(" ")), [vlanAware, setVlanAware] = useState(!!edit?.bridge_vlan_aware);
  const [bondMode, setBondMode] = useState(edit?.bond_mode ?? ""), [vlanId, setVlanId] = useState(edit?.vlan_id ? String(edit.vlan_id) : ""), [raw, setRaw] = useState(edit?.vlan_raw_device ?? "");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [ackLive, setAckLive] = useState(false), [ackCut, setAckCut] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [done, setDone] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  const kind = edit ? (edit.type as string) : type;
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/network`;
  const list = (s: string) => s.split(/[\s,]+/).filter(Boolean);

  const fields = () => {
    const x: Record<string, unknown> = {};
    if (cidr) x.cidr = cidr; if (gw) x.gateway = gw; if (mtu) x.mtu = Number(mtu); if (comments) x.comments = comments;
    if (kind === "bridge") { x.bridge_vlan_aware = vlanAware; if (ports || edit) x.bridge_ports = list(ports); }
    if (kind === "bond") { x.slaves = list(ports); if (bondMode) x.bond_mode = bondMode; }
    if (kind === "vlan" && vlanId) { x.vlan_id = Number(vlanId); if (raw) x.vlan_raw_device = raw; }
    return x;
  };
  const clearList = () => edit ? ([["cidr", edit.cidr, cidr], ["gateway", edit.gateway, gw], ["comments", edit.comments, comments]] as const).filter(([, was, now]) => was && !now).map(([k]) => k) : [];
  const op = () => {
    switch (mode.kind) {
      case "create": return { method: "POST", url: `${base}/interfaces`, body: { type, iface: name, ...fields() } };
      case "edit": return { method: "PUT", url: `${base}/interfaces/${encodeURIComponent(mode.iface.iface)}`, body: { ...fields(), ...(clearList().length ? { clear: clearList() } : {}) } };
      case "delete": return { method: "DELETE", url: `${base}/interfaces/${encodeURIComponent(mode.iface.iface)}`, body: {} };
      case "apply": return { method: "POST", url: `${base}/apply`, body: {} };
      default: return { method: "POST", url: `${base}/revert`, body: {} };
    }
  };
  const send = (extra: Record<string, unknown>) => {
    const o = op();
    if (o.method === "DELETE") return api<Preview>(`${o.url}?${new URLSearchParams(Object.entries({ confirm: true, ...extra }).map(([k, v]) => [k, String(v)]))}`, { method: "DELETE" });
    return api<Preview>(o.url, { method: o.method as "POST" | "PUT", body: { ...o.body, ...extra } });
  };
  useEffect(() => { setPreview(null); setAckLive(false); setAckCut(false); setTyped(""); setErr(null); }, [type, name, cidr, gw, mtu, comments, ports, vlanAware, bondMode, vlanId, raw]);
  useEffect(() => { if (mode.kind === "apply" || mode.kind === "revert" || mode.kind === "delete") void look(); /* aperçu d'emblée */ }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const look = async () => { setErr(null); try { setPreview(await send({ dry_run: true })); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      await send({ confirm: true, ...(ackLive ? { acknowledge_live: true } : {}), ...(ackCut ? { acknowledge_cut_access: true, type_name: typed } : {}) });
      await qc.invalidateQueries({ queryKey: ["network", connId] });
      setDone(mode.kind === "apply" ? "Modifications appliquées : le réseau du nœud a été rechargé. Si Kaji ne répond plus, l'accès a été coupé : corrige depuis la console du nœud."
        : mode.kind === "revert" ? "Modifications en attente annulées." : "Modification enregistrée EN ATTENTE : rien n'est appliqué tant que tu n'as pas cliqué sur « Appliquer ».");
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const cut = !!preview?.locks.cut.length, live = !!preview?.locks.live.length;
  const formOk = mode.kind === "create" ? !!name : true;
  const ready = !!preview && (!cut || (ackCut && typed === PHRASE)) && (!live || cut || ackLive);
  const titles = { create: "Ajouter une interface", edit: `Modifier ${edit?.iface}`, delete: `Supprimer ${mode.kind === "delete" ? mode.iface.iface : ""}`, apply: "Appliquer les modifications réseau", revert: "Annuler les modifications en attente" };

  if (done) return <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit><Notice kind="ok">{done}</Notice></Modal>;
  const inp = (label: string, v: string, set: (s: string) => void, ph = "") => <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span><input className="field" value={v} placeholder={ph} onChange={(e) => set(e.target.value)} /></label>;
  return (
    <Modal title={titles[mode.kind]} subtitle="Préparer une modification n'applique rien. Appliquer recharge le réseau du nœud, sans retour arrière automatique." onClose={busy ? () => {} : onClose}
      onSubmit={run} submitLabel="Confirmer" danger={cut || live} busy={busy} error={err} canSubmit={ready}>
      {(mode.kind === "create" || mode.kind === "edit") && <>
        {mode.kind === "create" && <>
          <label className="block space-y-1 text-sm"><span className="text-muted">Type</span><select className="field" value={type} onChange={(e) => setType(e.target.value as "bridge" | "bond" | "vlan")}><option value="bridge">Bridge Linux</option><option value="bond">Bond</option><option value="vlan">VLAN</option></select></label>
          {inp("Nom", name, setName, type === "bridge" ? "vmbr1" : type === "bond" ? "bond0" : "nic0.100")}</>}
        {inp("Adresse IPv4 (CIDR)", cidr, setCidr, "10.0.0.2/24")}{inp("Passerelle IPv4", gw, setGw)}{inp("MTU", mtu, setMtu, "1500")}{inp("Commentaire", comments, setComments)}
        {kind === "bridge" && <>{inp("Ports (séparés par un espace)", ports, setPorts, "nic1")}<label className="flex gap-2 text-sm"><input type="checkbox" checked={vlanAware} onChange={(e) => setVlanAware(e.target.checked)} />Compatible VLAN</label></>}
        {kind === "bond" && <>{inp("Esclaves", ports, setPorts, "nic1 nic2")}<label className="block space-y-1 text-sm"><span className="text-muted">Mode</span><select className="field" value={bondMode} onChange={(e) => setBondMode(e.target.value)}>{BOND_MODES.map((m) => <option key={m} value={m}>{m || "Par défaut"}</option>)}</select></label></>}
        {kind === "vlan" && <>{inp("ID du VLAN", vlanId, setVlanId)}{inp("Carte (vlanID uniquement)", raw, setRaw)}</>}
        <p className="text-xs text-muted">Cartes existantes : {ifaces.filter((i) => i.type === "eth").map((i) => i.iface).join(", ") || "–"}</p>
        <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!formOk} onClick={look}>Aperçu des verrous</button></>}
      {mode.kind === "apply" && pendingDiff && <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-line p-2 font-mono text-xs">{pendingDiff}</pre>}
      {preview && (
        <div className="space-y-3 text-sm">
          {preview.locks.inert && <Notice kind="ok">Aucun verrou : la modification est enregistrée en attente, sans effet tant qu'elle n'est pas appliquée.</Notice>}
          {live && !cut && <Notice kind="error">{preview.locks.live.join(" ; ")}.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ackLive} onChange={(e) => setAckLive(e.target.checked)} /><span>Je comprends que le réseau du nœud sera rechargé</span></label></Notice>}
          {cut && <Notice kind="error"><b>Coupure d'accès possible</b> : {preview.locks.cut.join(" ; ")}.
            <label className="mt-2 flex gap-2"><input type="checkbox" checked={ackCut} onChange={(e) => setAckCut(e.target.checked)} /><span>Je comprends que cela peut couper l'accès à Proxmox et à Kaji</span></label>
            <label className="mt-2 block text-xs">Retape <code>{PHRASE}</code><input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label></Notice>}
        </div>)}
    </Modal>
  );
}
