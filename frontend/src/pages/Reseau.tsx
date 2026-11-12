import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { FwObjectsDialog } from "../components/FwObjectsDialog";
import { FwOptionsDialog } from "../components/FwOptionsDialog";
import { NetWriteDialog, type NetMode } from "../components/NetWriteDialog";
import { SdnDialog, type SdnMode } from "../components/SdnDialog";
import { FwRulesDialog } from "../components/FwRulesDialog";
import { Empty, Options, Rules, Table, yn } from "../components/FwViews";
import { Button, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import type { SdnSubnet, SdnVnet, SdnZone } from "../lib/types/sdn";
import { isErr, type FwCluster, type FwNode, type FwPart, type NetIface, type NetworkInfo } from "../lib/types/reseau";

import { tr } from "../lib/i18n";
const TYPE_LABEL: Record<string, string> = { get bridge() { return tr("Bridge"); }, get bond() { return tr("Bond"); }, get eth() { return tr("Carte"); }, vlan: "VLAN", get alias() { return tr("Alias"); }, OVSBridge: "Bridge OVS", get unknown() { return tr("Autre"); } };

function Section({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) {
  return <section className="space-y-3"><h2 className="text-lg font-semibold">{title}</h2>{children}{hint && <p className="text-xs text-muted">{hint}</p>}</section>;
}
function Iface({ i, onEdit, onDelete }: { i: NetIface; onEdit: () => void; onDelete: () => void }) {
  const managed = ["bridge", "bond", "vlan", "eth"].includes(i.type);
  const addr = i.cidr ?? i.address ?? i.cidr6 ?? i.address6 ?? "–";
  const links = [...i.bridge_ports, ...i.slaves, ...(i.vlan_id !== null ? [tr("VLAN {vlan_id} sur {p}", { vlan_id: i.vlan_id, p: i.vlan_raw_device ?? "?" })] : [])].join(", ") || "–";
  return (
    <tr className="border-b border-line/60 last:border-0">
      <td className="px-4 py-2 font-mono">{i.iface}{i.has_gateway && <span className="ml-2 rounded-full border border-warn/50 px-2 py-0.5 font-sans text-xs text-warn" title={tr("Porte la passerelle par défaut : probablement le réseau d'administration")}>{tr("administration")}</span>}</td>
      <td className="px-4 py-2 text-muted">{TYPE_LABEL[i.type] ?? i.type}</td>
      <td className="px-4 py-2 tabular-nums">{addr}{i.gateway ? <span className="block text-xs text-muted">{tr("via {gateway}", { gateway: i.gateway })}</span> : null}</td>
      <td className="px-4 py-2 text-muted">{links}{i.bridge_vlan_aware ? <span className="block text-xs">{tr("VLAN aware {p}", { p: i.bridge_vids ?? "" })}</span> : null}</td>
      <td className="px-4 py-2 text-muted">{tr("{p} · démarrage {p2}", { p: i.active === false ? "inactif" : "actif", p2: yn(i.autostart) })}</td>
      <td className="px-4 py-2 text-right">{managed && <span className="flex justify-end gap-1"><button type="button" className="rounded border border-line px-2" onClick={onEdit}>{tr("Modifier")}</button>{i.type !== "eth" && <button type="button" className="rounded border border-danger/50 px-2 text-danger" onClick={onDelete}>{tr("Supprimer")}</button>}</span>}</td>
    </tr>
  );
}

function VnetRow({ v, connId, onAddSubnet, onDelete, onDeleteSubnet }: { v: SdnVnet; connId: number | null; onAddSubnet: () => void; onDelete: () => void; onDeleteSubnet: (s: string) => void }) {
  const subs = useQuery({ queryKey: ["sdn", connId, "subnets", v.vnet], queryFn: () => api<SdnSubnet[]>(`/api/connections/${connId}/sdn/vnets/${v.vnet}/subnets`), enabled: connId !== null });
  return (
    <tr className="border-b border-line/60 align-top last:border-0"><td className="px-4 py-2 font-mono">{v.vnet}</td><td className="px-4 py-2 text-muted">{v.zone}</td>
      <td className="px-4 py-2 text-muted">{[v.alias, v.tag && `tag ${v.tag}`, v.vlanaware && "VLAN aware"].filter(Boolean).join(" · ") || "–"}
        {(subs.data ?? []).map((s) => <span key={s.subnet} className="mt-1 flex items-center gap-2 text-xs">{s.cidr ?? s.subnet}{s.gateway ? ` via ${s.gateway}` : ""}{s.state ? ` (${s.state})` : ""}<button type="button" className="rounded border border-danger/50 px-1 text-danger" onClick={() => onDeleteSubnet(s.subnet)}>{tr("×")}</button></span>)}</td>
      <td className="px-4 py-2 text-muted">{v.state ?? tr("appliqué")}</td>
      <td className="px-4 py-2 text-right"><span className="flex justify-end gap-1"><button type="button" className="rounded border border-line px-2" onClick={onAddSubnet}>{tr("+ sous-réseau")}</button><button type="button" className="rounded border border-danger/50 px-2 text-danger" onClick={onDelete}>{tr("Supprimer")}</button></span></td></tr>
  );
}

export function Reseau({ onGoConnections }: { onGoConnections: () => void }) {
  const { active, id } = useActiveConnection();
  const nodes = useQuery({ queryKey: ["nodes", id], queryFn: () => api<{ node: string }[]>(`/api/connections/${id}/nodes`), enabled: id !== null });
  const [node, setNode] = useState("");
  const [objects, setObjects] = useState(false);
  const [options, setOptions] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [sdnMode, setSdnMode] = useState<SdnMode | null>(null);
  const [netMode, setNetMode] = useState<NetMode | null>(null);
  useEffect(() => { if (!node && nodes.data?.length) setNode(nodes.data[0].node); }, [nodes.data, node]);
  const net = useQuery({ queryKey: ["network", id, node], queryFn: () => api<NetworkInfo>(`/api/connections/${id}/nodes/${encodeURIComponent(node)}/network`), enabled: id !== null && !!node, staleTime: 15_000 });
  const dc = useQuery({ queryKey: ["fw-cluster", id], queryFn: () => api<FwCluster>(`/api/connections/${id}/firewall/cluster`), enabled: id !== null, staleTime: 15_000 });
  const fn = useQuery({ queryKey: ["fw-node", id, node], queryFn: () => api<FwNode>(`/api/connections/${id}/firewall/nodes/${encodeURIComponent(node)}`), enabled: id !== null && !!node, staleTime: 15_000 });

  const zones = useQuery({ queryKey: ["sdn", id, "zones"], queryFn: () => api<SdnZone[]>(`/api/connections/${id}/sdn/zones`), enabled: id !== null, staleTime: 15_000 });
  const extra = useQuery({ queryKey: ["sdn", id, "extra"], enabled: id !== null, staleTime: 15_000, queryFn: async () => {
    const g = <T,>(p: string) => api<T>(`/api/connections/${id}/sdn/${p}`).catch(() => [] as T);
    const [controllers, ipams, dns, fabrics] = await Promise.all([g<{ controller: string; type: string | null; state: string | null }[]>("controllers"), g<{ ipam: string; type: string | null }[]>("ipams"),
      g<{ dns: string; type: string | null }[]>("dns"), g<{ id: string; protocol: string | null; state: string | null }[]>("fabrics")]);
    return { controllers, ipams, dns, fabrics };
  } });
  const vnets = useQuery({ queryKey: ["sdn", id, "vnets"], queryFn: () => api<SdnVnet[]>(`/api/connections/${id}/sdn/vnets`), enabled: id !== null, staleTime: 15_000 });
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center"><div className="panel space-y-4 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1><Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button></div></div>
  );
  const named = (p: FwPart<{ name: string; comment: string | null }[]>) => isErr(p) ? <Notice kind="error">{p.error}</Notice>
    : p.length === 0 ? <Empty>{tr("Aucun.")}</Empty> : <p className="text-sm text-muted">{p.map((x) => x.name + (x.comment ? ` (${x.comment})` : "")).join(" · ")}</p>;
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-2xl font-semibold tracking-tight">{tr("Réseau et pare-feu")}</h1><p className="text-muted">{active.name}</p></div>
        {nodes.data && nodes.data.length > 1 && (
          <select aria-label={tr("Nœud")} className="field !w-auto !py-1.5 text-sm" value={node} onChange={(e) => setNode(e.target.value)}>{nodes.data.map((n) => <option key={n.node}>{n.node}</option>)}</select>)}
      </header>
      <Notice kind="ok">{tr("Une erreur de réseau ou de pare-feu peut couper l'accès à tout le cluster. Les interfaces se préparent en attente puis s'appliquent (verrou explicite) ; les alias, IPSets et groupes se modifient, avec un verrou explicite pour tout objet utilisé par un pare-feu actif.")}</Notice>

      <Section title={tr("Interfaces de {p}", { p: node || "…" })}>
        {net.isLoading ? <div className="panel h-24 animate-pulse" /> : net.error ? <Notice kind="error">{(net.error as Error).message}</Notice> : net.data && <>
          {net.data.pending && <Notice kind="error">{tr("Des modifications réseau sont")}{" "}<b>{tr("en attente")}</b>{" "}{tr("sur ce nœud (non appliquées). Elles ont été faites hors de Kaji ; vérifie le diff avant de les appliquer dans Proxmox.")}<pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs">{net.data.changes}</pre>
            <span className="mt-2 flex gap-2"><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setNetMode({ kind: "apply" })}>{tr("Appliquer…")}</Button><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setNetMode({ kind: "revert" })}>{tr("Annuler les modifications…")}</Button></span></Notice>}
          <div><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setNetMode({ kind: "create" })}>{tr("Ajouter une interface…")}</Button></div>
          {net.data.interfaces.length === 0 ? <Empty>{tr("Aucune interface lisible.")}</Empty> : <Table head={[tr("Interface"), tr("Type"), tr("Adresse"), tr("Liaisons"), tr("État"), ""]}>{net.data.interfaces.map((i) => <Iface key={i.iface} i={i} onEdit={() => setNetMode({ kind: "edit", iface: i })} onDelete={() => setNetMode({ kind: "delete", iface: i })} />)}</Table>}
        </>}
      </Section>

      <Section title={tr("Pare-feu du datacenter")} hint={tr("Un pare-feu non activé ne filtre rien, même s'il a des règles.")}>
        <div className="flex flex-wrap gap-2"><Button variant="ghost" onClick={() => setObjects(true)} className="!px-3 !py-1.5">{tr("Alias, IPSets et groupes…")}</Button>
          <Button variant="ghost" onClick={() => setOptions(true)} disabled={!node} className="!px-3 !py-1.5">{tr("Options du pare-feu…")}</Button>
          <Button variant="ghost" onClick={() => setRulesOpen(true)} disabled={!node} className="!px-3 !py-1.5">{tr("Règles…")}</Button></div>
        {dc.isLoading ? <div className="panel h-24 animate-pulse" /> : dc.error ? <Notice kind="error">{(dc.error as Error).message}</Notice> : dc.data && <>
          <Options o={dc.data.options} /><Rules rules={dc.data.rules} />
          <h3 className="text-sm font-semibold">{tr("Alias")}</h3>
          {isErr(dc.data.aliases) ? <Notice kind="error">{dc.data.aliases.error}</Notice> : dc.data.aliases.length === 0 ? <Empty>{tr("Aucun.")}</Empty> : <p className="text-sm text-muted">{dc.data.aliases.map((a) => `${a.name} = ${a.cidr ?? "?"}`).join(" · ")}</p>}
          <h3 className="text-sm font-semibold">{tr("IPSets")}</h3>{named(dc.data.ipsets)}<h3 className="text-sm font-semibold">{tr("Groupes de sécurité")}</h3>{named(dc.data.groups)}
        </>}
      </Section>

      {options && id !== null && <FwOptionsDialog connId={id} node={node} onClose={() => setOptions(false)} />}
      <Section title={tr("SDN")} hint={tr("Tout est écrit en attente ; « Appliquer » pousse la configuration sur tous les nœuds.")}>
        <div className="flex flex-wrap gap-2"><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setSdnMode({ kind: "zone" })}>{tr("Ajouter une zone…")}</Button>
          <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setSdnMode({ kind: "vnet" })}>{tr("Ajouter un VNet…")}</Button>
          <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setSdnMode({ kind: "apply" })}>{tr("Appliquer…")}</Button>
          <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setSdnMode({ kind: "rollback" })}>{tr("Annuler les modifications…")}</Button></div>
        {zones.error ? <Notice kind="error">{(zones.error as Error).message}</Notice> : (zones.data ?? []).length === 0 ? <Empty>{tr("Aucune zone SDN.")}</Empty> : (
          <Table head={[tr("Zone"), tr("Type"), tr("Détails"), tr("État"), ""]}>{(zones.data ?? []).map((z) => (
            <tr key={z.zone} className="border-b border-line/60 last:border-0"><td className="px-4 py-2 font-mono">{z.zone}</td><td className="px-4 py-2 text-muted">{z.type}</td>
              <td className="px-4 py-2 text-muted">{[z.bridge && `bridge ${z.bridge}`, z.tag && `tag ${z.tag}`, z.nodes.length > 0 && z.nodes.join(", ")].filter(Boolean).join(" · ") || "–"}</td>
              <td className="px-4 py-2 text-muted">{z.state ?? tr("appliquée")}</td><td className="px-4 py-2 text-right"><button type="button" className="rounded border border-danger/50 px-2 text-danger" onClick={() => setSdnMode({ kind: "delete", what: "zones", id: z.zone })}>{tr("Supprimer")}</button></td></tr>))}</Table>)}
        {vnets.error ? <Notice kind="error">{(vnets.error as Error).message}</Notice> : (vnets.data ?? []).length > 0 && (
          <Table head={["VNet", tr("Zone"), tr("Détails"), tr("État"), ""]}>{(vnets.data ?? []).map((v) => <VnetRow key={v.vnet} v={v} connId={id} onAddSubnet={() => setSdnMode({ kind: "subnet", vnet: v.vnet })} onDelete={() => setSdnMode({ kind: "delete", what: "vnets", id: v.vnet })} onDeleteSubnet={(s) => setSdnMode({ kind: "delete", what: "subnets", id: s, vnet: v.vnet })} />)}</Table>)}
        {extra.data && (extra.data.controllers.length + extra.data.dns.length + extra.data.fabrics.length + extra.data.ipams.filter((i) => i.ipam !== "pve").length) > 0 && (
          <Table head={[tr("Objet"), tr("Type"), tr("État"), ""]}>{[
            ...extra.data.controllers.map((c) => ({ k: "controllers" as const, id: c.controller, label: tr("Contrôleur {controller}", { controller: c.controller }), type: c.type, state: c.state })),
            ...extra.data.ipams.filter((i) => i.ipam !== "pve").map((i) => ({ k: "ipams" as const, id: i.ipam, label: `IPAM ${i.ipam}`, type: i.type, state: null })),
            ...extra.data.dns.map((d) => ({ k: "dns" as const, id: d.dns, label: `DNS ${d.dns}`, type: d.type, state: null })),
            ...extra.data.fabrics.map((f) => ({ k: "fabrics" as const, id: f.id, label: `Fabric ${f.id}`, type: f.protocol, state: f.state }))].map((o) => (
            <tr key={o.k + o.id} className="border-b border-line/60 last:border-0"><td className="px-4 py-2">{o.label}</td><td className="px-4 py-2 text-muted">{o.type}</td><td className="px-4 py-2 text-muted">{o.state ?? tr("appliqué")}</td>
              <td className="px-4 py-2 text-right"><button type="button" className="rounded border border-danger/50 px-2 text-danger" onClick={() => setSdnMode({ kind: "delete", what: o.k, id: o.id })}>{tr("Supprimer")}</button></td></tr>))}</Table>)}
      </Section>

      {sdnMode && id !== null && <SdnDialog connId={id} mode={sdnMode} onClose={() => setSdnMode(null)} />}
      {netMode && id !== null && <NetWriteDialog connId={id} node={node} mode={netMode} ifaces={net.data?.interfaces ?? []} pendingDiff={net.data?.changes ?? null} onClose={() => setNetMode(null)} />}
      {rulesOpen && id !== null && <FwRulesDialog connId={id} node={node} onClose={() => setRulesOpen(false)} />}
      {objects && id !== null && <FwObjectsDialog connId={id} onClose={() => setObjects(false)} />}
      <Section title={tr("Pare-feu de {p}", { p: node || "…" })}>
        {fn.isLoading ? <div className="panel h-24 animate-pulse" /> : fn.error ? <Notice kind="error">{(fn.error as Error).message}</Notice> : fn.data && <><Options o={fn.data.options} /><Rules rules={fn.data.rules} /></>}
      </Section>
    </div>
  );
}
