import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { CephPoolDialog, UnvalidatedBanner } from "../components/CephPoolDialog";
import { CephWriteDialog, type CephWrite } from "../components/CephWriteDialog";
import { Gauge } from "../components/Gauge";
import { Button, Notice } from "../components/ui";
import { api, type NodeInfo } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { bytes } from "../lib/format";
import type { Ceph, CephFilesystems, CephHealth, CephManagers, CephMonitors, CephOsds, CephPool, CephPools, CephStatus } from "../lib/types/ceph";

import { tr, locale } from "../lib/i18n";
const num = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString(locale()));
const rate = (n: number | null | undefined) => (n == null ? "–" : `${bytes(n)}/s`);

/** Couleur ET mot : l'état ne repose jamais sur la couleur seule. */
const HEALTH: Record<CephHealth, { label: string; tone: string; dot: string }> = {
  HEALTH_OK: { get label() { return tr("En bonne santé"); }, tone: "text-ok", dot: "bg-ok" },
  HEALTH_WARN: { get label() { return tr("Avertissement"); }, tone: "text-warn", dot: "bg-warn" },
  HEALTH_ERR: { get label() { return tr("Erreur"); }, tone: "text-danger", dot: "bg-danger" },
  UNKNOWN: { get label() { return tr("État inconnu"); }, tone: "text-muted", dot: "bg-muted" },
};

const Section = ({ title, count, action, children }: { title: string; count?: number; action?: ReactNode; children: ReactNode }) => (
  <section className="space-y-3" aria-label={title}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">{title}{count !== undefined && <span className="ml-2 text-sm font-normal text-muted">({count})</span>}</h2>
      {action}
    </div>
    {children}
  </section>
);
const Tile = ({ label, value, sub }: { label: string; value: string; sub?: string }) => (
  <div className="panel rise p-4"><p className="text-xs text-muted">{label}</p><p className="text-2xl font-semibold tabular-nums tracking-tight">{value}</p>{sub && <p className="text-xs text-muted">{sub}</p>}</div>
);
const Table = ({ min, head, children }: { min: string; head: string[]; children: ReactNode }) => (
  <div className="panel overflow-x-auto">
    <table className={`w-full ${min} text-sm`}>
      <thead><tr className="border-b border-line text-left text-xs text-muted">{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead>
      <tbody>{children}</tbody>
    </table>
  </div>
);
const Skeleton = ({ n, h }: { n: number; h: string }) => <>{Array.from({ length: n }, (_, i) => <div key={i} className={`panel animate-pulse ${h}`} />)}</>;
const Flag = ({ ok, yes, no }: { ok: boolean | null; yes: string; no: string }) =>
  ok === null ? <span className="text-muted">?</span> : <span className={ok ? "text-ok" : "text-danger"}>{ok ? yes : no}</span>;

/** Lecture, plus l'écriture des lots C2 (pools), C3 (moniteurs, gestionnaires, MDS, OSD) et C5 (initialisation) : NON validée en réel. Aucune suppression (lot C4). */
export function CephPage({ onGoConnections }: { onGoConnections: () => void }) {
  const { conns, active, id } = useActiveConnection();
  const [poolDialog, setPoolDialog] = useState<CephPool | "new" | null>(null);
  const [write, setWrite] = useState<CephWrite | null>(null);
  const base = `/api/connections/${id}/ceph`;
  const status = useQuery({ queryKey: ["ceph", id, "status"], queryFn: () => api<Ceph<CephStatus>>(`${base}/status`), enabled: id !== null, staleTime: 15_000 });
  const present = status.data?.installed === true;       // inutile d'interroger le reste si Ceph n'est pas installé
  const q = <T,>(what: string) => ({ queryKey: ["ceph", id, what], queryFn: () => api<Ceph<T>>(`${base}/${what}`), enabled: present, staleTime: 15_000 });
  const osds = useQuery(q<CephOsds>("osds"));
  const pools = useQuery(q<CephPools>("pools"));
  const fs = useQuery(q<CephFilesystems>("filesystems"));
  const mons = useQuery(q<CephMonitors>("monitors"));
  const mgrs = useQuery(q<CephManagers>("managers"));
  const nodeList = useQuery({ queryKey: ["cluster", id, "nodes"], enabled: id !== null, staleTime: 30_000, queryFn: () => api<NodeInfo[]>(`/api/connections/${id}/nodes`) });

  if (conns.isLoading) return <div className="mx-auto grid max-w-6xl gap-4 sm:grid-cols-2 lg:grid-cols-4"><Skeleton n={4} h="h-24" /></div>;
  if (!active || id === null) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1>
        <p className="text-muted">{tr("Ajoute ton cluster Proxmox pour voir son Ceph.")}</p>
        <Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button>
      </div>
    </div>
  );

  const online = (nodeList.data ?? []).filter((n) => n.status === "online").map((n) => n.node).sort();
  const create = (title: string, tail: string, done: string, extra?: "mds" | "osd") => () =>
    setWrite({ title, submitLabel: tr("Créer"), done, tail, nodes: online, extra, subtitle: tr("Choisis le nœud sur lequel créer.") });
  /** Démarrer, arrêter, dedans, dehors : sur le nœud qui héberge le service. Le serveur décide des confirmations. */
  const act = (label: string, host: string | null, tail: string, done: string, what: string) => (
    <Button variant="ghost" className="!px-2 !py-1 text-xs" disabled={!host} title={host ? undefined : tr("Hôte inconnu")} aria-label={`${label} ${what}`}
      onClick={() => host && setWrite({ title: `${label} ${what}`, submitLabel: label, done, tail, node: host })}>{label}</Button>
  );
  const svc = (kind: string, name: string, host: string | null) => <>
    {act(tr("Démarrer"), host, `services/${kind}/${name}/start`, tr("{kind}.{name} démarré", { kind, name }), `${kind}.${name}`)}
    {act(tr("Arrêter"), host, `services/${kind}/${name}/stop`, tr("{kind}.{name} arrêté", { kind, name }), `${kind}.${name}`)}
  </>;

  const refresh = () => { status.refetch(); if (present) { osds.refetch(); pools.refetch(); fs.refetch(); mons.refetch(); mgrs.refetch(); } };
  const fetching = status.isFetching || osds.isFetching || pools.isFetching;
  const s = status.data?.installed ? status.data : null;
  const h = s ? HEALTH[s.health.status] : null;
  const part = <T,>(r: { data?: Ceph<T>; isLoading: boolean; error: unknown; refetch: () => unknown }, name: string, view: (d: Extract<Ceph<T>, { installed: true }>) => ReactNode, rows: 2 | 3 = 3) =>
    r.isLoading ? <div className="space-y-2"><Skeleton n={rows} h="h-10" /></div>
      : r.error ? <Notice kind="error">{name} : {(r.error as Error).message} — <button className="underline" onClick={() => r.refetch()}>{tr("réessayer")}</button></Notice>
      : r.data?.installed ? view(r.data) : null;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{tr("Ceph")}</h1>
          <p className="text-muted">{tr("{name} · {host} · lecture seule", { name: active.name, host: active.host })}</p>
        </div>
        <Button variant="ghost" onClick={refresh} disabled={fetching} className="!px-3 !py-1.5">
          <span className={fetching ? "inline-block animate-spin" : ""}>↻</span>{" "}{tr("Actualiser")}</Button>
      </header>

      {status.isLoading && <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Skeleton n={4} h="h-24" /></div>}
      {status.error && <Notice kind="error">{(status.error as Error).message} — <button className="underline" onClick={() => status.refetch()}>{tr("réessayer")}</button></Notice>}

      {status.data && !status.data.installed && (
        <div className="mx-auto grid max-w-3xl place-items-center py-16 text-center">
          <div className="panel space-y-3 p-10" role="status">
            <h2 className="text-xl font-semibold">{tr("Ceph n'est pas installé sur ce cluster")}</h2>
            <p className="text-muted">{tr("Il n'y a rien à afficher ici. Cette page se remplira dès que Ceph sera installé et initialisé sur le cluster.")}</p>
            <UnvalidatedBanner />
            <p className="text-sm">{tr("Pour le mettre en place depuis Kaji : installer les paquets (shell du nœud), initialiser, puis créer un moniteur, un gestionnaire, des OSD et un pool.")}</p>
            <div className="flex flex-wrap justify-center gap-2">
              <Button onClick={() => setWrite({ title: tr("Installer et initialiser Ceph"), subtitle: tr("Choisis le nœud depuis lequel initialiser."), submitLabel: tr("Initialiser"), done: tr("Ceph initialisé"), tail: "init", nodes: online, extra: "init" })}
                disabled={online.length === 0}>{tr("Installer / initialiser Ceph")}</Button>
              <Button variant="ghost" onClick={create(tr("Créer un moniteur"), "monitors", tr("Moniteur créé"))} disabled={online.length === 0}>{tr("Créer un moniteur")}</Button>
              <Button variant="ghost" onClick={create(tr("Créer un gestionnaire"), "managers", tr("Gestionnaire créé"))} disabled={online.length === 0}>{tr("Créer un gestionnaire")}</Button>
            </div>
            <p className="text-xs text-muted">{tr("Les boutons « moniteur » et « gestionnaire » ne servent qu'une fois Ceph initialisé. Si Kaji ne peut pas encore lire Ceph, utilise « pveceph mon create » dans le shell.")}</p>
          </div>
        </div>
      )}

      {s && h && <>
        <Section title={tr("Santé")}>
          <div className="panel space-y-4 p-5">
            <p className={`flex items-center gap-2 text-xl font-semibold ${h.tone}`}><span className={`size-3 rounded-full ${h.dot}`} aria-hidden="true" />{h.label}
              <span className="text-xs font-normal text-muted">{s.health.status}</span></p>
            {s.health.checks.length === 0
              ? <p className="text-sm text-muted">{s.health.status === "HEALTH_OK" ? tr("Aucun message de santé.") : tr("Aucun détail fourni par Ceph.")}</p>
              : <ul className="space-y-2">
                  {s.health.checks.map((c) => {
                    const ch = HEALTH[c.severity];
                    return (
                      <li key={c.code} className="rounded-xl border border-line bg-surface2 p-3 text-sm">
                        <p className="flex flex-wrap items-center gap-2"><span className={`size-2 rounded-full ${ch.dot}`} aria-hidden="true" /><span className={`font-medium ${ch.tone}`}>{ch.label}</span>
                          <code className="text-xs text-muted">{c.code}</code>{c.muted && <span className="rounded-full border border-line px-2 text-xs text-muted">{tr("en sourdine")}</span>}</p>
                        <p className="mt-1">{c.message}{c.count != null && c.count > 1 ? ` (${c.count})` : ""}</p>
                        {c.details.length > 0 && <details className="mt-1 text-xs text-muted"><summary className="cursor-pointer">{tr("Détails ({length})", { length: c.details.length })}</summary>
                          <ul className="mt-1 list-disc space-y-0.5 pl-5">{c.details.map((d, i) => <li key={i}>{d}</li>)}</ul></details>}
                      </li>
                    );
                  })}
                </ul>}
          </div>
        </Section>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label={tr("Résumé")}>
          <Tile label={tr("OSD actifs")} value={`${num(s.osds.up)} / ${num(s.osds.total)}`} sub={tr("{p} dans le cluster", { p: num(s.osds.in) })} />
          <Tile label={tr("Moniteurs en quorum")} value={`${s.mons.quorum.length} / ${num(s.mons.total)}`} sub={s.mons.quorum.join(", ") || undefined} />
          <Tile label={tr("Gestionnaire")} value={s.mgr.active ?? "–"} sub={tr("{standbys} en attente", { standbys: s.mgr.standbys })} />
          <Tile label={tr("Groupes de placement")} value={num(s.pgs.total)} sub={s.pgs.all_clean ? tr("Tous actifs et propres") : s.pgs.states.map((p) => `${p.count} ${p.state}`).join(" · ") || undefined} />
        </section>

        <Section title={tr("Usage et débit")}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="panel space-y-3 p-5">
              {s.usage.percent != null
                ? <Gauge label={tr("Espace utilisé")} value={s.usage.percent} detail={`${bytes(s.usage.used)} / ${bytes(s.usage.total)}`} />
                : <p className="text-sm text-muted">{tr("Usage : information indisponible")}</p>}
              {s.usage.avail != null && <p className="text-xs text-muted">{tr("Libre : {p}", { p: bytes(s.usage.avail) })}</p>}
            </div>
            <div className="panel grid grid-cols-1 sm:grid-cols-2 gap-3 p-5 text-sm">
              <div><p className="text-xs text-muted">{tr("Lecture")}</p><p className="tabular-nums">{rate(s.io.read_bytes_sec)}</p><p className="text-xs text-muted">{tr("{p} op/s", { p: num(s.io.read_ops) })}</p></div>
              <div><p className="text-xs text-muted">{tr("Écriture")}</p><p className="tabular-nums">{rate(s.io.write_bytes_sec)}</p><p className="text-xs text-muted">{tr("{p} op/s", { p: num(s.io.write_ops) })}</p></div>
            </div>
          </div>
        </Section>

        <Section title={tr("OSD")} count={osds.data?.installed ? osds.data.osds.length : undefined}
          action={<Button onClick={create(tr("Créer un OSD"), "osds", tr("OSD créé"), "osd")} disabled={online.length === 0} className="!px-3 !py-1.5">{tr("Créer un OSD")}</Button>}>
          <UnvalidatedBanner />
          {part(osds, "OSD", (d) => <>
            {d.flags.length > 0 && <p className="flex flex-wrap items-center gap-2 text-xs text-muted">{tr("Drapeaux du cluster :")}{d.flags.map((f) => <span key={f} className="rounded-full border border-warn/40 bg-warn/10 px-2 py-0.5 text-warn">{f}</span>)}</p>}
            {d.osds.length === 0 ? <div className="panel p-6 text-muted">{tr("Aucun OSD.")}</div> : (
              <Table min="min-w-[60rem]" head={["OSD", tr("Hôte"), tr("État"), tr("Classe"), tr("Usage"), tr("Taille"), "PG", tr("Version"), ""]}>
                {d.osds.map((o) => (
                  <tr key={o.name} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-medium">{o.name}</td><td className="px-4 py-2 text-muted">{o.host ?? "–"}</td>
                    <td className="px-4 py-2"><Flag ok={o.up} yes="Actif" no="Arrêté" /> · <Flag ok={o.in} yes="Dans" no="Dehors" /></td>
                    <td className="px-4 py-2 text-muted">{o.device_class ?? "–"}</td>
                    <td className="min-w-32 px-4 py-2">{o.percent_used != null ? <Gauge label={o.name} value={o.percent_used} detail={`${o.percent_used.toFixed(0)} %`} /> : "–"}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{bytes(o.total)}</td><td className="px-4 py-2 tabular-nums text-muted">{num(o.pgs)}</td>
                    <td className="px-4 py-2 text-muted">{o.version ?? "–"}</td>
                    <td className="space-x-1 whitespace-nowrap px-4 py-2 text-right">
                      {o.id !== null && <>
                        {o.up === false ? act(tr("Démarrer"), o.host, `services/osd/${o.id}/start`, tr("{name} démarré", { name: o.name }), o.name) : act(tr("Arrêter"), o.host, `services/osd/${o.id}/stop`, tr("{name} arrêté", { name: o.name }), o.name)}
                        {o.in === false ? act(tr("Dedans"), o.host, `osds/${o.id}/in`, `${o.name} remis dedans`, o.name) : act(tr("Dehors"), o.host, `osds/${o.id}/out`, `${o.name} mis dehors`, o.name)}
                      </>}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </>)}
        </Section>

        <Section title={tr("Pools")} count={pools.data?.installed ? pools.data.pools.length : undefined}
          action={<Button onClick={() => setPoolDialog("new")} className="!px-3 !py-1.5">{tr("Nouveau pool")}</Button>}>
          <UnvalidatedBanner />
          {part(pools, tr("Pools"), (d) => d.pools.length === 0 ? <div className="panel p-6 text-muted">{tr("Aucun pool.")}</div> : (
            <Table min="min-w-[48rem]" head={[tr("Pool"), tr("Type"), tr("Copies"), "PG", tr("Règle CRUSH"), tr("Usage"), tr("Applications"), ""]}>
              {d.pools.map((p) => (
                <tr key={p.name} className="border-b border-line/60 align-top last:border-0">
                  <td className="px-4 py-2 font-medium">{p.name}{p.warnings.map((w) => <span key={w} className="mt-1 block text-xs font-normal text-warn">⚠ {w}</span>)}</td>
                  <td className="px-4 py-2 text-muted">{p.type ?? "–"}</td>
                  <td className="px-4 py-2 tabular-nums">{p.size ?? "–"} <span className="text-xs text-muted">{tr("(min {p})", { p: p.min_size ?? "–" })}</span></td>
                  <td className="px-4 py-2 tabular-nums text-muted">{num(p.pg_num)}</td><td className="px-4 py-2 text-muted">{p.crush_rule ?? "–"}</td>
                  <td className="px-4 py-2 tabular-nums">{bytes(p.used)}</td>
                  <td className="px-4 py-2 text-muted">{p.applications.join(", ") || "–"}</td>
                  <td className="px-4 py-2 text-right"><Button variant="ghost" className="!px-3 !py-1 text-xs" onClick={() => setPoolDialog(p)} aria-label={tr("Modifier le pool {name}", { name: p.name })}
                    disabled={p.name.startsWith(".")} title={p.name.startsWith(".") ? tr("Pool interne de Ceph : non modifiable ici") : undefined}>{tr("Modifier")}</Button></td>
                </tr>
              ))}
            </Table>
          ), 2)}
        </Section>

        <Section title={tr("CephFS")} count={fs.data?.installed ? fs.data.filesystems.length : undefined}
          action={<Button onClick={create(tr("Créer un MDS"), "mds", tr("MDS créé"), "mds")} disabled={online.length === 0} className="!px-3 !py-1.5">{tr("Nouveau MDS")}</Button>}>
          {part(fs, "CephFS", (d) => <>
            {d.filesystems.length === 0 ? <div className="panel p-6 text-muted">{tr("Aucun système de fichiers CephFS.")}</div> : (
              <Table min="min-w-[34rem]" head={[tr("Système de fichiers"), tr("Pool de métadonnées"), tr("Pools de données")]}>
                {d.filesystems.map((f) => <tr key={f.name} className="border-b border-line/60 last:border-0"><td className="px-4 py-2 font-medium">{f.name}</td>
                  <td className="px-4 py-2 text-muted">{f.metadata_pool ?? "–"}</td><td className="px-4 py-2 text-muted">{f.data_pools.join(", ") || "–"}</td></tr>)}
              </Table>
            )}
            {d.mds.length > 0 && <Table min="min-w-[34rem]" head={[tr("Serveur de métadonnées (MDS)"), tr("Hôte"), tr("Rang"), tr("État"), ""]}>
              {d.mds.map((m) => <tr key={m.name} className="border-b border-line/60 last:border-0"><td className="px-4 py-2 font-medium">{m.name}</td>
                <td className="px-4 py-2 text-muted">{m.host ?? "–"}</td><td className="px-4 py-2 tabular-nums text-muted">{m.rank ?? "–"}</td><td className="px-4 py-2 text-muted">{m.state ?? "–"}</td>
                <td className="space-x-1 whitespace-nowrap px-4 py-2 text-right">{svc("mds", m.name, m.host)}</td></tr>)}
            </Table>}
          </>, 2)}
        </Section>

        <Section title={tr("Moniteurs et gestionnaires")}
          action={<div className="flex gap-2">
            <Button onClick={create(tr("Créer un moniteur"), "monitors", tr("Moniteur créé"))} disabled={online.length === 0} className="!px-3 !py-1.5">{tr("Nouveau moniteur")}</Button>
            <Button onClick={create(tr("Créer un gestionnaire"), "managers", tr("Gestionnaire créé"))} disabled={online.length === 0} className="!px-3 !py-1.5">{tr("Nouveau gestionnaire")}</Button></div>}>
          <UnvalidatedBanner />
          <div className="grid gap-4 lg:grid-cols-2">
            {part(mons, tr("Moniteurs"), (d) => d.monitors.length === 0 ? <div className="panel p-6 text-muted">{tr("Aucun moniteur.")}</div> : (
              <Table min="min-w-[22rem]" head={[tr("Moniteur"), tr("Quorum"), tr("Version"), ""]}>
                {d.monitors.map((m) => <tr key={m.name} className="border-b border-line/60 last:border-0"><td className="px-4 py-2 font-medium">{m.name}</td>
                  <td className="px-4 py-2"><Flag ok={m.in_quorum} yes="Dans le quorum" no="Hors quorum" /></td><td className="px-4 py-2 text-muted">{m.version ?? "–"}</td>
                  <td className="space-x-1 whitespace-nowrap px-4 py-2 text-right">{svc("mon", m.name, m.host)}</td></tr>)}
              </Table>
            ), 2)}
            {part(mgrs, tr("Gestionnaires"), (d) => d.managers.length === 0 ? <div className="panel p-6 text-muted">{tr("Aucun gestionnaire.")}</div> : (
              <Table min="min-w-[22rem]" head={[tr("Gestionnaire"), tr("État"), tr("Version"), ""]}>
                {d.managers.map((m) => <tr key={m.name} className="border-b border-line/60 last:border-0"><td className="px-4 py-2 font-medium">{m.name}</td>
                  <td className="px-4 py-2 text-muted">{m.state ?? "–"}</td><td className="px-4 py-2 text-muted">{m.version ?? "–"}</td>
                  <td className="space-x-1 whitespace-nowrap px-4 py-2 text-right">{svc("mgr", m.name, m.host)}</td></tr>)}
              </Table>
            ), 2)}
          </div>
        </Section>
      </>}
      {write && <CephWriteDialog connId={id} spec={write} onClose={() => setWrite(null)} />}
      {poolDialog && <CephPoolDialog connId={id} pool={poolDialog === "new" ? null : poolDialog} onClose={() => setPoolDialog(null)} />}
    </div>
  );
}
