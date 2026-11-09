import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { FwObjectsDialog } from "../components/FwObjectsDialog";
import { FwOptionsDialog } from "../components/FwOptionsDialog";
import { NetWriteDialog, type NetMode } from "../components/NetWriteDialog";
import { FwRulesDialog } from "../components/FwRulesDialog";
import { Button, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { isErr, type FwCluster, type FwNode, type FwOptions, type FwPart, type FwRule, type NetIface, type NetworkInfo } from "../lib/types/reseau";

const TYPE_LABEL: Record<string, string> = { bridge: "Bridge", bond: "Bond", eth: "Carte", vlan: "VLAN", alias: "Alias", OVSBridge: "Bridge OVS", unknown: "Autre" };
const yn = (v: boolean | null | undefined) => (v === null || v === undefined ? "–" : v ? "oui" : "non");

function Section({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) {
  return <section className="space-y-3"><h2 className="text-lg font-semibold">{title}</h2>{children}{hint && <p className="text-xs text-muted">{hint}</p>}</section>;
}
const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[36rem] text-sm">
    <thead><tr className="border-b border-line text-left text-xs text-muted">{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
);
const Empty = ({ children }: { children: ReactNode }) => <div className="rounded-xl border border-line bg-surface2 p-4 text-sm text-muted">{children}</div>;

function Iface({ i, onEdit, onDelete }: { i: NetIface; onEdit: () => void; onDelete: () => void }) {
  const managed = ["bridge", "bond", "vlan", "eth"].includes(i.type);
  const addr = i.cidr ?? i.address ?? i.cidr6 ?? i.address6 ?? "–";
  const links = [...i.bridge_ports, ...i.slaves, ...(i.vlan_id !== null ? [`VLAN ${i.vlan_id} sur ${i.vlan_raw_device ?? "?"}`] : [])].join(", ") || "–";
  return (
    <tr className="border-b border-line/60 last:border-0">
      <td className="px-4 py-2 font-mono">{i.iface}{i.has_gateway && <span className="ml-2 rounded-full border border-warn/50 px-2 py-0.5 font-sans text-xs text-warn" title="Porte la passerelle par défaut : probablement le réseau d'administration">administration</span>}</td>
      <td className="px-4 py-2 text-muted">{TYPE_LABEL[i.type] ?? i.type}</td>
      <td className="px-4 py-2 tabular-nums">{addr}{i.gateway ? <span className="block text-xs text-muted">via {i.gateway}</span> : null}</td>
      <td className="px-4 py-2 text-muted">{links}{i.bridge_vlan_aware ? <span className="block text-xs">VLAN aware {i.bridge_vids ?? ""}</span> : null}</td>
      <td className="px-4 py-2 text-muted">{i.active === false ? "inactif" : "actif"} · démarrage {yn(i.autostart)}</td>
      <td className="px-4 py-2 text-right">{managed && <span className="flex justify-end gap-1"><button type="button" className="rounded border border-line px-2" onClick={onEdit}>Modifier</button>{i.type !== "eth" && <button type="button" className="rounded border border-danger/50 px-2 text-danger" onClick={onDelete}>Supprimer</button>}</span>}</td>
    </tr>
  );
}

function Rules({ rules }: { rules: FwPart<FwRule[]> }) {
  if (isErr(rules)) return <Notice kind="error">{rules.error}</Notice>;
  if (rules.length === 0) return <Empty>Aucune règle.</Empty>;
  return (
    <Table head={["#", "Sens", "Action", "Source", "Destination", "Protocole", "Commentaire"]}>
      {rules.map((r) => (
        <tr key={r.pos} className={`border-b border-line/60 last:border-0 ${r.enable === false ? "opacity-50" : ""}`}>
          <td className="px-4 py-2 tabular-nums text-muted">{r.pos}</td><td className="px-4 py-2">{r.type ?? "–"}</td>
          <td className={`px-4 py-2 font-medium ${r.action === "ACCEPT" ? "text-ok" : r.action === "DROP" || r.action === "REJECT" ? "text-danger" : ""}`}>{r.action ?? "–"}</td>
          <td className="px-4 py-2 text-muted">{r.source ?? "tous"}</td><td className="px-4 py-2 text-muted">{r.dest ?? "tous"}{r.dport ? `:${r.dport}` : ""}</td>
          <td className="px-4 py-2 text-muted">{r.macro ?? r.proto ?? "–"}</td><td className="px-4 py-2 text-muted">{r.comment ?? ""}{r.enable === false ? " (désactivée)" : ""}</td>
        </tr>))}
    </Table>
  );
}
const Options = ({ o }: { o: FwPart<FwOptions> }) => isErr(o) ? <Notice kind="error">{o.error}</Notice> : (
  <p className="text-sm text-muted">{Object.entries(o).filter(([k]) => k !== "digest").map(([k, v]) => `${k} : ${v === null ? "–" : typeof v === "boolean" ? yn(v) : v}`).join(" · ") || "Aucune option définie."}</p>);

export function Reseau({ onGoConnections }: { onGoConnections: () => void }) {
  const { active, id } = useActiveConnection();
  const nodes = useQuery({ queryKey: ["nodes", id], queryFn: () => api<{ node: string }[]>(`/api/connections/${id}/nodes`), enabled: id !== null });
  const [node, setNode] = useState("");
  const [objects, setObjects] = useState(false);
  const [options, setOptions] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [netMode, setNetMode] = useState<NetMode | null>(null);
  useEffect(() => { if (!node && nodes.data?.length) setNode(nodes.data[0].node); }, [nodes.data, node]);
  const net = useQuery({ queryKey: ["network", id, node], queryFn: () => api<NetworkInfo>(`/api/connections/${id}/nodes/${encodeURIComponent(node)}/network`), enabled: id !== null && !!node, staleTime: 15_000 });
  const dc = useQuery({ queryKey: ["fw-cluster", id], queryFn: () => api<FwCluster>(`/api/connections/${id}/firewall/cluster`), enabled: id !== null, staleTime: 15_000 });
  const fn = useQuery({ queryKey: ["fw-node", id, node], queryFn: () => api<FwNode>(`/api/connections/${id}/firewall/nodes/${encodeURIComponent(node)}`), enabled: id !== null && !!node, staleTime: 15_000 });

  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center"><div className="panel space-y-4 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">Aucun cluster connecté</h1><Button onClick={onGoConnections}>Ajouter un cluster</Button></div></div>
  );
  const named = (p: FwPart<{ name: string; comment: string | null }[]>) => isErr(p) ? <Notice kind="error">{p.error}</Notice>
    : p.length === 0 ? <Empty>Aucun.</Empty> : <p className="text-sm text-muted">{p.map((x) => x.name + (x.comment ? ` (${x.comment})` : "")).join(" · ")}</p>;
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-2xl font-semibold tracking-tight">Réseau et pare-feu</h1><p className="text-muted">{active.name}</p></div>
        {nodes.data && nodes.data.length > 1 && (
          <select aria-label="Nœud" className="field !w-auto !py-1.5 text-sm" value={node} onChange={(e) => setNode(e.target.value)}>{nodes.data.map((n) => <option key={n.node}>{n.node}</option>)}</select>)}
      </header>
      <Notice kind="ok">Une erreur de réseau ou de pare-feu peut couper l'accès à tout le cluster. Les interfaces se préparent en attente puis s'appliquent (verrou explicite) ; les alias, IPSets et groupes se modifient, avec un verrou explicite pour tout objet utilisé par un pare-feu actif.</Notice>

      <Section title={`Interfaces de ${node || "…"}`}>
        {net.isLoading ? <div className="panel h-24 animate-pulse" /> : net.error ? <Notice kind="error">{(net.error as Error).message}</Notice> : net.data && <>
          {net.data.pending && <Notice kind="error">Des modifications réseau sont <b>en attente</b> sur ce nœud (non appliquées). Elles ont été faites hors de Kaji ; vérifie le diff avant de les appliquer dans Proxmox.<pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs">{net.data.changes}</pre>
            <span className="mt-2 flex gap-2"><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setNetMode({ kind: "apply" })}>Appliquer…</Button><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setNetMode({ kind: "revert" })}>Annuler les modifications…</Button></span></Notice>}
          <div><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setNetMode({ kind: "create" })}>Ajouter une interface…</Button></div>
          {net.data.interfaces.length === 0 ? <Empty>Aucune interface lisible.</Empty> : <Table head={["Interface", "Type", "Adresse", "Liaisons", "État", ""]}>{net.data.interfaces.map((i) => <Iface key={i.iface} i={i} onEdit={() => setNetMode({ kind: "edit", iface: i })} onDelete={() => setNetMode({ kind: "delete", iface: i })} />)}</Table>}
        </>}
      </Section>

      <Section title="Pare-feu du datacenter" hint="Un pare-feu non activé ne filtre rien, même s'il a des règles.">
        <div className="flex flex-wrap gap-2"><Button variant="ghost" onClick={() => setObjects(true)} className="!px-3 !py-1.5">Alias, IPSets et groupes…</Button>
          <Button variant="ghost" onClick={() => setOptions(true)} disabled={!node} className="!px-3 !py-1.5">Options du pare-feu…</Button>
          <Button variant="ghost" onClick={() => setRulesOpen(true)} disabled={!node} className="!px-3 !py-1.5">Règles…</Button></div>
        {dc.isLoading ? <div className="panel h-24 animate-pulse" /> : dc.error ? <Notice kind="error">{(dc.error as Error).message}</Notice> : dc.data && <>
          <Options o={dc.data.options} /><Rules rules={dc.data.rules} />
          <h3 className="text-sm font-semibold">Alias</h3>
          {isErr(dc.data.aliases) ? <Notice kind="error">{dc.data.aliases.error}</Notice> : dc.data.aliases.length === 0 ? <Empty>Aucun.</Empty> : <p className="text-sm text-muted">{dc.data.aliases.map((a) => `${a.name} = ${a.cidr ?? "?"}`).join(" · ")}</p>}
          <h3 className="text-sm font-semibold">IPSets</h3>{named(dc.data.ipsets)}<h3 className="text-sm font-semibold">Groupes de sécurité</h3>{named(dc.data.groups)}
        </>}
      </Section>

      {options && id !== null && <FwOptionsDialog connId={id} node={node} onClose={() => setOptions(false)} />}
      {netMode && id !== null && <NetWriteDialog connId={id} node={node} mode={netMode} ifaces={net.data?.interfaces ?? []} pendingDiff={net.data?.changes ?? null} onClose={() => setNetMode(null)} />}
      {rulesOpen && id !== null && <FwRulesDialog connId={id} node={node} onClose={() => setRulesOpen(false)} />}
      {objects && id !== null && <FwObjectsDialog connId={id} onClose={() => setObjects(false)} />}
      <Section title={`Pare-feu de ${node || "…"}`}>
        {fn.isLoading ? <div className="panel h-24 animate-pulse" /> : fn.error ? <Notice kind="error">{(fn.error as Error).message}</Notice> : fn.data && <><Options o={fn.data.options} /><Rules rules={fn.data.rules} /></>}
      </Section>
    </div>
  );
}
