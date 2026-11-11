import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./Modal";
import { Notice } from "./ui";

const PHRASE = "COUPURE POSSIBLE";
type Level = "cluster" | "node" | "guest";
type Tri = "" | "yes" | "no";
type Preview = { params: Record<string, string | number>; remove: string[]; locks: { cut: string[]; live: string[]; inert: boolean }; phrase: string | null };
const POLICIES = ["", "ACCEPT", "REJECT", "DROP"], FORWARD = ["", "ACCEPT", "DROP"], LOGS = ["", "emerg", "alert", "crit", "err", "warning", "notice", "info", "debug", "nolog"];

/** Options du pare-feu du datacenter ou d'un nœud. L'aperçu (dry_run) montre les verrous ; la coupure possible exige une case ET la phrase `COUPURE POSSIBLE`. */
export function FwOptionsDialog({ connId, node, onClose, guest }: { connId: number; node: string; onClose: () => void; guest?: { gtype: "qemu" | "lxc"; vmid: number } }) {
  const qc = useQueryClient();
  const [level, setLevel] = useState<Level>(guest ? "guest" : "cluster");
  const [dhcp, setDhcp] = useState<Tri>(""), [ipfilter, setIpfilter] = useState<Tri>(""), [macfilter, setMacfilter] = useState<Tri>(""), [ndp, setNdp] = useState<Tri>(""), [radv, setRadv] = useState<Tri>("");
  const [enable, setEnable] = useState<Tri>(""), [ebtables, setEbtables] = useState<Tri>(""), [nosmurfs, setNosmurfs] = useState<Tri>(""), [tcpflags, setTcpflags] = useState<Tri>("");
  const [pin, setPin] = useState(""), [pout, setPout] = useState(""), [pfwd, setPfwd] = useState(""), [lin, setLin] = useState(""), [lout, setLout] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [ackLive, setAckLive] = useState(false), [ackCut, setAckCut] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [done, setDone] = useState(false), [err, setErr] = useState<string | null>(null);
  const url = level === "guest" ? `/api/connections/${connId}/firewall/guests/${encodeURIComponent(node)}/${guest!.gtype}/${guest!.vmid}/options` : level === "cluster" ? `/api/connections/${connId}/firewall/cluster/options` : `/api/connections/${connId}/firewall/nodes/${encodeURIComponent(node)}/options`;
  const b = (t: Tri) => (t === "yes" ? true : t === "no" ? false : undefined);

  const body = () => {
    const x: Record<string, unknown> = {};
    const set = (k: string, v: unknown) => { if (v !== undefined && v !== "") x[k] = v; };
    set("enable", b(enable));
    if (level === "guest") { set("dhcp", b(dhcp)); set("ipfilter", b(ipfilter)); set("macfilter", b(macfilter)); set("ndp", b(ndp)); set("radv", b(radv)); set("policy_in", pin); set("policy_out", pout); set("log_level_in", lin); set("log_level_out", lout); }
    else if (level === "cluster") { set("ebtables", b(ebtables)); set("policy_in", pin); set("policy_out", pout); set("policy_forward", pfwd); }
    else { set("log_level_in", lin); set("log_level_out", lout); set("nosmurfs", b(nosmurfs)); set("tcpflags", b(tcpflags)); }
    return x;
  };
  const changed = Object.keys(body()).length > 0;
  useEffect(() => { setPreview(null); setAckLive(false); setAckCut(false); setTyped(""); setErr(null); }, [level, enable, ebtables, nosmurfs, tcpflags, pin, pout, pfwd, lin, lout, dhcp, ipfilter, macfilter, ndp, radv]);

  const look = async () => {
    setErr(null);
    try { setPreview(await api<Preview>(url, { method: "PUT", body: { ...body(), dry_run: true } })); } catch (e) { setErr((e as Error).message); }
  };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      await api(url, { method: "PUT", body: { ...body(), confirm: true, ...(ackLive ? { acknowledge_live: true } : {}), ...(ackCut ? { acknowledge_cut_access: true, type_name: typed } : {}) } });
      await qc.invalidateQueries({ queryKey: ["fw-cluster", connId] }); await qc.invalidateQueries({ queryKey: ["fw-node", connId] }); await qc.invalidateQueries({ queryKey: ["fw-guest", connId] });
      setDone(true);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const cut = !!preview?.locks.cut.length, live = !!preview?.locks.live.length;
  const ready = !!preview && (!cut || (ackCut && typed === PHRASE)) && (!live || cut || ackLive);

  const tri = (label: string, v: Tri, set: (t: Tri) => void, yes = "Activer", no = "Désactiver") => (
    <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span>
      <select className="field" value={v} onChange={(e) => set(e.target.value as Tri)}><option value="">Ne pas changer</option><option value="yes">{yes}</option><option value="no">{no}</option></select></label>);
  const pick = (label: string, v: string, set: (s: string) => void, opts: string[]) => (
    <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span>
      <select className="field" value={v} onChange={(e) => set(e.target.value)}>{opts.map((o) => <option key={o} value={o}>{o || "Ne pas changer"}</option>)}</select></label>);

  if (done) return <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit><Notice kind="ok">Options du pare-feu enregistrées ({level === "guest" ? `machine ${guest!.vmid}` : level === "cluster" ? "datacenter" : node}). Relues chez Proxmox.</Notice></Modal>;
  return (
    <Modal title="Options du pare-feu" subtitle="Les modifications dangereuses sont verrouillées : l'aperçu dit pourquoi, et rien n'est écrit sans ton accord explicite." onClose={busy ? () => {} : onClose}
      onSubmit={run} submitLabel="Appliquer" danger={cut || live} busy={busy} error={err} canSubmit={ready}>
      {guest ? <p className="text-sm text-muted">Machine {guest.gtype === "qemu" ? "VM" : "LXC"} {guest.vmid} sur {node}.</p> : <label className="block space-y-1 text-sm"><span className="text-muted">Niveau</span>
        <select className="field" value={level} onChange={(e) => setLevel(e.target.value as Level)}><option value="cluster">Datacenter</option><option value="node">Nœud {node}</option></select></label>}
      {tri("Pare-feu", enable, setEnable, "Activer (filtre tout de suite)", "Désactiver")}
      {level === "guest" ? <>
        {pick("Politique entrante par défaut", pin, setPin, POLICIES)}{pick("Politique sortante par défaut", pout, setPout, POLICIES)}
        {pick("Journal des paquets entrants", lin, setLin, LOGS)}{pick("Journal des paquets sortants", lout, setLout, LOGS)}
        {tri("Client DHCP autorisé", dhcp, setDhcp, "Autoriser", "Interdire")}{tri("Filtre d'adresses IP (ipfilter)", ipfilter, setIpfilter)}{tri("Filtre d'adresses MAC", macfilter, setMacfilter)}
        {tri("NDP (IPv6)", ndp, setNdp, "Autoriser", "Interdire")}{tri("Annonces de routeur (radv)", radv, setRadv, "Autoriser", "Interdire")}
      </> : level === "cluster" ? <>
        {pick("Politique entrante par défaut", pin, setPin, POLICIES)}{pick("Politique sortante par défaut", pout, setPout, POLICIES)}{pick("Politique de transfert par défaut", pfwd, setPfwd, FORWARD)}{tri("ebtables", ebtables, setEbtables)}
      </> : <>
        {pick("Journal des paquets entrants", lin, setLin, LOGS)}{pick("Journal des paquets sortants", lout, setLout, LOGS)}{tri("Protection nosmurfs", nosmurfs, setNosmurfs)}{tri("Filtre des drapeaux TCP", tcpflags, setTcpflags)}
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!changed} onClick={look}>Aperçu des verrous</button>
      {preview && (
        <div className="space-y-3 text-sm">
          {preview.locks.inert && <Notice kind="ok">Aucun verrou : ce niveau est désactivé, les réglages s'appliqueront à son activation.</Notice>}
          {live && !cut && <Notice kind="error">{preview.locks.live.join(" ; ")}.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ackLive} onChange={(e) => setAckLive(e.target.checked)} /><span>Je comprends que la modification s'applique tout de suite</span></label></Notice>}
          {cut && <Notice kind="error"><b>Coupure d'accès possible</b> : {preview.locks.cut.join(" ; ")}.
            <label className="mt-2 flex gap-2"><input type="checkbox" checked={ackCut} onChange={(e) => setAckCut(e.target.checked)} /><span>Je comprends que cela peut couper l'accès à Proxmox et à Kaji</span></label>
            <label className="mt-2 block text-xs">Retape <code>{PHRASE}</code><input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label></Notice>}
        </div>)}
    </Modal>
  );
}
