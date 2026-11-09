import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./Modal";
import { Notice } from "./ui";

const PHRASE = "COUPURE POSSIBLE";
type Locks = { cut: string[]; live: string[]; inert: boolean };
type Preview = { locks: Locks; pending?: { zones: string[]; vnets: string[]; subnets: string[] } };
export type SdnMode = { kind: "zone" } | { kind: "vnet"; zone?: string } | { kind: "subnet"; vnet: string } | { kind: "delete"; what: "zones" | "vnets" | "subnets" | "controllers" | "ipams" | "dns" | "fabrics"; id: string; vnet?: string } | { kind: "apply" } | { kind: "rollback" };
const ZONE_TYPES = ["simple", "vlan", "qinq", "vxlan", "evpn"];

/** SDN : tout s'écrit EN ATTENTE ; appliquer pousse la configuration sur tous les nœuds. Chaque action montre d'abord ses verrous. */
export function SdnDialog({ connId, mode, onClose }: { connId: number; mode: SdnMode; onClose: () => void }) {
  const qc = useQueryClient();
  const [id, setId] = useState(""), [type, setType] = useState("simple"), [bridge, setBridge] = useState(""), [tag, setTag] = useState(""), [zone, setZone] = useState(mode.kind === "vnet" ? mode.zone ?? "" : "");
  const [alias, setAlias] = useState(""), [cidr, setCidr] = useState(""), [gw, setGw] = useState(""), [snat, setSnat] = useState(false), [peers, setPeers] = useState(""), [controller, setController] = useState(""), [vrf, setVrf] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [ackLive, setAckLive] = useState(false), [ackCut, setAckCut] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [done, setDone] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  const base = `/api/connections/${connId}/sdn`;

  const op = () => {
    switch (mode.kind) {
      case "zone": return { method: "POST", url: `${base}/zones`, body: { zone: id, type, ...(bridge ? { bridge } : {}), ...(tag && type === "qinq" ? { tag: Number(tag) } : {}), ...(peers ? { peers: peers.split(/[\s,]+/).filter(Boolean) } : {}), ...(controller ? { controller } : {}), ...(vrf ? { vrf_vxlan: Number(vrf) } : {}) } };
      case "vnet": return { method: "POST", url: `${base}/vnets`, body: { vnet: id, zone, ...(alias ? { alias } : {}), ...(tag ? { tag: Number(tag) } : {}) } };
      case "subnet": return { method: "POST", url: `${base}/vnets/${mode.vnet}/subnets`, body: { subnet: cidr, ...(gw ? { gateway: gw } : {}), snat } };
      case "delete": return { method: "DELETE", url: `${base}/${mode.what === "subnets" ? `vnets/${mode.vnet}/subnets` : mode.what}/${mode.id}`, body: {} };
      case "apply": return { method: "POST", url: `${base}/apply`, body: {} };
      default: return { method: "POST", url: `${base}/rollback`, body: {} };
    }
  };
  const send = (extra: Record<string, unknown>) => {
    const o = op();
    if (o.method === "DELETE") return api<Preview>(`${o.url}?${new URLSearchParams(Object.entries({ confirm: true, ...extra }).map(([k, v]) => [k, String(v)]))}`, { method: "DELETE" });
    return api<Preview>(o.url, { method: "POST", body: { ...o.body, ...extra } });
  };
  const look = async () => { setErr(null); try { setPreview(await send({ dry_run: true })); } catch (e) { setErr((e as Error).message); } };
  useEffect(() => { setPreview(null); setAckLive(false); setAckCut(false); setTyped(""); setErr(null); }, [id, type, bridge, tag, zone, alias, cidr, gw, snat, peers, controller, vrf]);
  useEffect(() => { if (mode.kind === "apply" || mode.kind === "rollback" || mode.kind === "delete") void look(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      await send({ confirm: true, ...(ackLive ? { acknowledge_live: true } : {}), ...(ackCut ? { acknowledge_cut_access: true, type_name: typed } : {}) });
      await qc.invalidateQueries({ queryKey: ["sdn", connId] });
      setDone(mode.kind === "apply" ? "Configuration SDN appliquée sur les nœuds." : mode.kind === "rollback" ? "Modifications SDN annulées." : "Enregistré EN ATTENTE : rien n'est appliqué tant que tu n'as pas cliqué sur « Appliquer ».");
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const cut = !!preview?.locks.cut.length, live = !!preview?.locks.live.length;
  const form = mode.kind === "zone" || mode.kind === "vnet" || mode.kind === "subnet";
  const ready = !!preview && (!cut || (ackCut && typed === PHRASE)) && (!live || cut || ackLive);
  const inp = (label: string, v: string, set: (s: string) => void, ph = "") => <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span><input className="field" value={v} placeholder={ph} onChange={(e) => set(e.target.value)} /></label>;
  const title = { zone: "Ajouter une zone SDN", vnet: "Ajouter un VNet", subnet: "Ajouter un sous-réseau", delete: "Supprimer (en attente)", apply: "Appliquer le SDN", rollback: "Annuler les modifications SDN" }[mode.kind];
  if (done) return <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit><Notice kind="ok">{done}</Notice></Modal>;
  return (
    <Modal title={title} subtitle="Tout est écrit en attente ; appliquer pousse la configuration sur tous les nœuds." onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel="Confirmer" danger={cut || live} busy={busy} error={err} canSubmit={ready}>
      {mode.kind === "zone" && <>{inp("Identifiant (8 caractères max, minuscules)", id, setId, "zone1")}
        <label className="block space-y-1 text-sm"><span className="text-muted">Type</span><select className="field" value={type} onChange={(e) => setType(e.target.value)}>{ZONE_TYPES.map((t) => <option key={t}>{t}</option>)}</select></label>
        {(type === "vlan" || type === "qinq") && inp("Bridge", bridge, setBridge, "vmbr0")}{type === "qinq" && inp("Tag de service", tag, setTag)}{type === "vxlan" && inp("Pairs (IP)", peers, setPeers)}
        {type === "evpn" && <>{inp("Contrôleur", controller, setController)}{inp("VRF VXLAN", vrf, setVrf)}</>}</>}
      {mode.kind === "vnet" && <>{inp("Identifiant", id, setId, "vnet1")}{inp("Zone", zone, setZone)}{inp("Alias", alias, setAlias)}{inp("Tag (zones VLAN)", tag, setTag)}</>}
      {mode.kind === "subnet" && <>{inp(`Sous-réseau de ${mode.vnet} (CIDR)`, cidr, setCidr, "10.99.0.0/24")}{inp("Passerelle", gw, setGw)}<label className="flex gap-2 text-sm"><input type="checkbox" checked={snat} onChange={(e) => setSnat(e.target.checked)} />SNAT</label></>}
      {mode.kind === "delete" && <p className="text-sm">Supprimer <b>{mode.id}</b> de la configuration en attente.</p>}
      {form && <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm" onClick={look}>Aperçu des verrous</button>}
      {preview?.pending && <p className="text-xs text-muted">En attente : zones {preview.pending.zones.join(", ") || "–"} · VNets {preview.pending.vnets.join(", ") || "–"} · sous-réseaux {preview.pending.subnets.join(", ") || "–"}</p>}
      {preview && (
        <div className="space-y-3 text-sm">
          {preview.locks.inert && <Notice kind="ok">Aucun verrou : enregistré en attente, sans effet tant qu'il n'est pas appliqué.</Notice>}
          {live && !cut && <Notice kind="error">{preview.locks.live.join(" ; ")}.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ackLive} onChange={(e) => setAckLive(e.target.checked)} /><span>Je comprends que la configuration sera poussée sur les nœuds</span></label></Notice>}
          {cut && <Notice kind="error"><b>Coupure possible</b> : {preview.locks.cut.join(" ; ")}.
            <label className="mt-2 flex gap-2"><input type="checkbox" checked={ackCut} onChange={(e) => setAckCut(e.target.checked)} /><span>Je comprends que cela peut couper des machines ou le réseau des nœuds</span></label>
            <label className="mt-2 block text-xs">Retape <code>{PHRASE}</code><input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label></Notice>}
        </div>)}
    </Modal>
  );
}
