import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NodeCharts } from "../components/charts/MetricsPanels";
import { NodeConsole } from "../components/ConsoleTab";
import { NodePower } from "../components/NodePower";
import { NodeSystem } from "../components/NodeSystem";
import { Gauge } from "../components/Gauge";
import { Button, Notice } from "../components/ui";
import { api, type Bridge } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { bytes, pct, uptime } from "../lib/format";
import { guestHash } from "../lib/route";
import type { StorageRow } from "../lib/types/stockage";
import { useCluster } from "../lib/useCluster";

// Valeur venant de l'adresse : contrôlée, et elle ne sert qu'à retrouver le nœud dans la liste du cluster.
const NODE = /^[A-Za-z0-9]([A-Za-z0-9-]{0,62})$/;

const Section = ({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) => (
  <section className="space-y-3">
    <h2 className="text-lg font-semibold">{title}{count !== undefined && <span className="ml-2 text-sm font-normal text-muted">({count})</span>}</h2>
    {children}
  </section>
);

export function NodePage({ params, go, onGoConnections }: { params: string[]; go: (hash: string, o?: { replace?: boolean }) => void; onGoConnections: () => void }) {
  const node = params[0];
  const valid = !!node && NODE.test(node);
  const { active, id, conns } = useActiveConnection();
  const { status, nodes, guests, problem } = useCluster(id);
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t); }, []);

  const info = valid ? nodes.data?.find((n) => n.node === node) : undefined;
  const online = info?.status === "online";
  const storages = useQuery({
    queryKey: ["node-storages", id], enabled: !!id && !!info, staleTime: 15_000,
    queryFn: () => api<StorageRow[]>(`/api/connections/${id}/storages`),
  });
  const bridges = useQuery({
    queryKey: ["node-bridges", id, node], enabled: !!id && !!info && online, staleTime: 30_000,
    queryFn: () => api<Bridge[]>(`/api/connections/${id}/nodes/${encodeURIComponent(node)}/bridges`),
  });

  const back = <Button variant="ghost" onClick={() => go("#/")} className="!px-3 !py-1.5">← Dashboard</Button>;
  const wrap = (c: React.ReactNode) => <div className="mx-auto max-w-4xl space-y-4">{back}{c}</div>;
  if (!valid) return wrap(<Notice kind="error">Adresse de nœud invalide.</Notice>);
  if (conns.isLoading || (id && nodes.isLoading)) return wrap(<div className="panel h-40 animate-pulse" />);
  if (!active) return wrap(<Notice kind="error">Aucun cluster connecté. <button className="underline" onClick={onGoConnections}>Ajouter un cluster</button></Notice>);
  if (nodes.error && !nodes.data) return wrap(<Notice kind="error">{(nodes.error as Error).message} — <button className="underline" onClick={() => nodes.refetch()}>réessayer</button></Notice>);
  if (!info) return wrap(<Notice kind="error">Nœud « {node} » introuvable dans le cluster « {active.name} ».</Notice>);

  const ip = status.data?.nodes.find((s) => s.name === node)?.ip;
  const mine = (guests.data ?? []).filter((g) => g.node === node).sort((a, b) => a.vmid - b.vmid);
  const running = mine.filter((g) => !g.template && g.status === "running").length;
  const stores = (storages.data ?? []).filter((s) => s.node === node);

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      {back}
      {problem && <Notice kind="error">Proxmox ne répond pas ({problem}). Les dernières données connues restent affichées.</Notice>}

      <header className="panel space-y-5 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{info.node}</h1>
            <p className="text-sm text-muted">{ip ?? "—"} · {online ? `actif depuis ${uptime(info.uptime)}` : "hors ligne"}</p>
          </div>
          <span className={`flex items-center gap-1.5 text-sm ${online ? "text-ok" : "text-danger"}`}>
            <span className={`size-2 rounded-full ${online ? "bg-ok dot-live" : "bg-danger"}`} />{online ? "En ligne" : "Hors ligne"}
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Gauge label={`CPU · ${info.maxcpu ?? "?"} cœurs`} value={(info.cpu ?? 0) * 100} />
          <Gauge label="RAM" value={pct(info.mem, info.maxmem)} detail={`${bytes(info.mem)} / ${bytes(info.maxmem)}`} />
          <Gauge label="Disque" value={pct(info.disk, info.maxdisk)} detail={`${bytes(info.disk)} / ${bytes(info.maxdisk)}`} />
        </div>
      </header>

      <Section title="Historique">
        <NodeCharts connId={active.id} node={node} />
      </Section>

      <Section title="Console du nœud">
        <NodeConsole connId={active.id} node={node} online={online} />
      </Section>

      <Section title="Système">
        <NodePower connId={active.id} node={node} online={online} />
        <NodeSystem connId={active.id} node={node} online={online} />
      </Section>

      <Section title="Machines" count={mine.length}>
        {guests.isLoading ? <div className="panel h-24 animate-pulse" />
          : mine.length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Aucune machine sur ce nœud.</div>
          : <>
            <p className="text-xs text-muted">{running} en marche sur {mine.filter((g) => !g.template).length}</p>
            <div className="overflow-x-auto rounded-xl border border-line">
              <table className="w-full min-w-[32rem] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    <th scope="col" className="px-4 py-2 font-normal">Machine</th><th scope="col" className="px-4 py-2 font-normal">Type</th>
                    <th scope="col" className="px-4 py-2 font-normal">État</th><th scope="col" className="px-4 py-2 text-right font-normal">CPU</th>
                    <th scope="col" className="px-4 py-2 text-right font-normal">RAM</th>
                  </tr>
                </thead>
                <tbody>
                  {mine.map((g) => {
                    const run = g.status === "running";
                    return (
                      <tr key={g.vmid} className="cursor-pointer border-b border-line/60 transition last:border-0 hover:bg-surface2"
                        onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) go(guestHash(g)); }}>
                        <td className="px-4 py-2"><a href={guestHash(g)} className="font-medium hover:underline focus-visible:underline">{g.name ?? `#${g.vmid}`}</a><span className="ml-2 text-xs text-muted">#{g.vmid}</span></td>
                        <td className="px-4 py-2 text-muted">{g.template ? "Modèle" : g.type === "qemu" ? "VM" : "LXC"}</td>
                        <td className="px-4 py-2"><span className="flex items-center gap-1.5"><span className={`size-2 rounded-full ${run ? "bg-ok" : g.status === "stopped" ? "bg-muted" : "bg-warn"}`} />{run ? "En marche" : g.status === "stopped" ? "Arrêtée" : (g.status ?? "Inconnu")}</span></td>
                        <td className="px-4 py-2 text-right tabular-nums text-muted">{run ? `${(g.cpu * 100).toFixed(0)} %` : "–"}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-muted">{run ? bytes(g.mem) : "–"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>}
      </Section>

      <Section title="Stockages" count={storages.data ? stores.length : undefined}>
        {storages.isLoading ? <div className="panel h-24 animate-pulse" />
          : storages.error ? <Notice kind="error">{(storages.error as Error).message} — <button className="underline" onClick={() => storages.refetch()}>réessayer</button></Notice>
          : stores.length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Aucun stockage visible pour ce nœud.</div>
          : <div className="grid gap-3 sm:grid-cols-2">
            {stores.map((s) => (
              <div key={s.storage} className={`panel space-y-3 p-4 ${s.active ? "" : "opacity-60"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold">{s.storage}</h3>
                    <p className="truncate text-xs text-muted">{s.type ?? "type inconnu"} · {s.shared ? "partagé" : "local"}</p>
                  </div>
                  <span className={`text-xs ${s.active ? "text-ok" : "text-danger"}`}>{s.active ? "Actif" : "Inactif"}</span>
                </div>
                {s.used != null && s.total != null && s.total > 0
                  ? <Gauge label="Espace utilisé" value={pct(s.used, s.total)} detail={`${bytes(s.used)} / ${bytes(s.total)}`} />
                  : <p className="text-xs text-muted">Espace : information indisponible</p>}
              </div>
            ))}
          </div>}
        {stores.length > 0 && <p className="text-xs text-muted">Le contenu de chaque stockage est dans la page <button className="underline" onClick={() => go("#/storage")}>Stockage</button>.</p>}
      </Section>

      <Section title="Réseau" count={bridges.data?.length}>
        {!online ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Nœud hors ligne : réseau indisponible.</div>
          : bridges.isLoading ? <div className="panel h-16 animate-pulse" />
          : bridges.error ? <Notice kind="error">{(bridges.error as Error).message} — <button className="underline" onClick={() => bridges.refetch()}>réessayer</button></Notice>
          : (bridges.data ?? []).length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Aucun bridge ni VNet.</div>
          : <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[26rem] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th scope="col" className="px-4 py-2 font-normal">Nom</th><th scope="col" className="px-4 py-2 font-normal">Type</th>
                  <th scope="col" className="px-4 py-2 font-normal">Détail</th>
                </tr>
              </thead>
              <tbody>
                {bridges.data!.map((b) => (
                  <tr key={`${b.kind}-${b.name}`} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-medium">{b.name}</td>
                    <td className="px-4 py-2 text-muted">{b.kind === "vnet" ? `VNet${b.zone ? ` · zone ${b.zone}` : ""}` : `Bridge${b.vlan_aware ? " · VLAN" : ""}`}</td>
                    <td className="px-4 py-2 text-muted">{b.detail ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>}
      </Section>
    </div>
  );
}
