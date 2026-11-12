import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Button, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import type { ClusterConfig } from "../lib/types/cluster";

import { tr } from "../lib/i18n";
const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[32rem] text-sm">
    <thead><tr className="border-b border-line text-left text-xs text-muted">{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
);
const Row = ({ k, v }: { k: string; v: ReactNode }) => <div className="flex justify-between gap-4 border-b border-line/60 py-1.5 last:border-0"><dt className="text-muted">{k}</dt><dd className="text-right">{v}</dd></div>;

/** Commande à copier : Kaji ne crée, ne joint et ne retire aucun nœud (voir `docs/m10-cluster.md`). */
function Cmd({ label, cmd, where }: { label: string; cmd: string; where: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => { try { await navigator.clipboard.writeText(cmd); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* le texte reste sélectionnable */ } };
  return (
    <div className="space-y-1.5 rounded-xl border border-line bg-surface2 p-3 text-sm">
      <div className="flex items-center justify-between gap-3"><div><b>{label}</b> <span className="text-muted">· {where}</span></div><Button variant="ghost" onClick={copy}>{copied ? tr("Copié") : tr("Copier")}</Button></div>
      <code className="block overflow-x-auto whitespace-pre rounded-lg bg-black/30 px-3 py-2 font-mono text-xs">{cmd}</code>
    </div>
  );
}

/** Cluster : informations, nœuds corosync, QDevice. Lecture seule ; créer, joindre, retirer un nœud = commandes à copier. */
export function Cluster({ onGoConnections }: { onGoConnections: () => void }) {
  const { active, id } = useActiveConnection();
  const q = useQuery({ queryKey: ["cluster-config", id], queryFn: () => api<ClusterConfig>(`/api/connections/${id}/cluster/config`), enabled: id !== null, staleTime: 10_000 });
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center"><div className="panel space-y-4 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1><Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button></div></div>
  );
  const d = q.data;
  const join = d?.join;
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header><h1 className="text-2xl font-semibold tracking-tight">{tr("Cluster")}</h1><p className="text-muted">{tr("{name} · lecture seule", { name: active.name })}</p></header>
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}
      {d && Object.entries(d.errors).map(([k, m]) => <Notice key={k} kind="error">{tr("Lecture « {k} » impossible : {m}", { k, m })}</Notice>)}
      {d && !d.cluster.clustered && <Notice kind="ok">{tr("Ce nœud n'est pas dans un cluster (nœud isolé).")}</Notice>}

      <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("Informations")}</h2>
        {!d ? <p className="text-sm text-muted">{tr("Chargement…")}</p> : (
          <dl className="panel p-4 text-sm">
            <Row k="Nom du cluster" v={d.cluster.name ?? d.totem?.cluster_name ?? "–"} />
            <Row k="Quorum" v={d.cluster.quorate === null ? "–" : d.cluster.quorate ? <span className="text-ok">{tr("atteint")}</span> : <span className="text-danger">{tr("PERDU")}</span>} />
            <Row k="Nœuds" v={`${d.nodes.length}${d.cluster.nodes_total !== null && d.cluster.nodes_total !== d.nodes.length ? tr(" ({nodes_total} annoncés)", { nodes_total: d.cluster.nodes_total }) : ""}`} />
            <Row k="Version de la configuration" v={d.cluster.version ?? d.totem?.config_version ?? "–"} />
            {d.totem && <><Row k="Mode des liens" v={d.totem.link_mode ?? "–"} /><Row k="Version IP" v={d.totem.ip_version ?? "–"} /><Row k="Authentification corosync" v={d.totem.secauth ?? "–"} />
              <Row k="Liens configurés" v={d.totem.links.length ? d.totem.links.map((l) => `link${l}`).join(", ") : "–"} /></>}
          </dl>)}
      </section>

      <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("Nœuds")}</h2>
        {!d ? null : d.nodes.length === 0 ? <p className="text-sm text-muted">{tr("Aucun nœud.")}</p> : (
          <Table head={["ID", tr("Nœud"), tr("Votes"), tr("État"), tr("Adresse"), tr("Liens corosync"), tr("Empreinte du certificat")]}>{d.nodes.map((n) => (
            <tr key={n.name} className="border-b border-line/60 last:border-0 align-top">
              <td className="px-4 py-2 text-muted">{n.nodeid ?? "–"}</td>
              <td className="px-4 py-2 font-mono">{n.name}{n.local && <span className="ml-2 rounded bg-surface2 px-1.5 py-0.5 font-sans text-xs text-muted">{tr("nœud interrogé")}</span>}</td>
              <td className="px-4 py-2 text-muted">{n.votes ?? "–"}</td>
              <td className={`px-4 py-2 ${n.online === false ? "text-danger" : "text-muted"}`}>{n.online === null ? "–" : n.online ? tr("en ligne") : "hors ligne"}</td>
              <td className="px-4 py-2 font-mono text-muted">{n.ip ?? "–"}</td>
              <td className="px-4 py-2 font-mono text-xs text-muted">{n.links.length ? n.links.map((l) => <div key={l.link}>{tr("link{link} : {addr}", { link: l.link, addr: l.addr })}</div>) : "–"}</td>
              <td className="max-w-[14rem] px-4 py-2 font-mono text-xs text-muted"><span className="block truncate" title={n.fingerprint ?? undefined}>{n.fingerprint ?? "–"}</span></td>
            </tr>))}</Table>)}
      </section>

      <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("QDevice")}</h2>
        {!d ? null : !d.qdevice.configured ? <p className="text-sm text-muted">{tr("Aucun QDevice configuré. Avec deux nœuds, un QDevice (voix d'arbitrage externe) évite de perdre le quorum quand un nœud tombe.")}</p> : (
          <dl className="panel p-4 text-sm">{Object.entries(d.qdevice.info).map(([k, v]) => <Row key={k} k={k} v={v ?? "–"} />)}</dl>)}
      </section>

      <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("Créer, joindre, retirer un nœud")}</h2>
        <Notice kind="ok">{tr("Kaji ne modifie pas le cluster : une erreur peut casser le quorum, et joindre un nœud demande le mot de passe root d'un nœud, que Kaji ne manipule jamais. Lance ces commandes toi-même, dans le shell du nœud indiqué.")}</Notice>
        <div className="space-y-3">
          <Cmd label={tr("Créer un cluster")} where="sur un nœud isolé, une seule fois" cmd={`pvecm create ${d?.cluster.name ?? "NOM-DU-CLUSTER"}`} />
          <Cmd label={tr("Joindre ce cluster")} where="sur le NOUVEAU nœud (le mot de passe root du nœud contacté sera demandé)"
            cmd={join?.address && join.fingerprint ? `pvecm add ${join.address} --fingerprint ${join.fingerprint}` : tr("pvecm add ADRESSE-D-UN-NŒUD --fingerprint EMPREINTE")} />
          <Cmd label={tr("Retirer un nœud")} where="sur un nœud qui reste, après avoir ÉTEINT définitivement le nœud à retirer" cmd="pvecm delnode NOM-DU-NŒUD" />
        </div>
        <p className="text-xs text-muted">{tr("Information de jonction (équivalent de « Join Information » de Proxmox) : nœud à contacter")}{" "}<code>{join?.preferred_node ?? "–"}</code>{tr(", adresse")}{" "}<code>{join?.address ?? "–"}</code>.</p>
      </section>
    </div>
  );
}
