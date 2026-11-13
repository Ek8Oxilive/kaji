import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { uptime } from "../lib/format";
import { runTask } from "../lib/tasks";
import type { NodeSystem as Sys, Section, Service, ServiceAction, SyslogLines } from "../lib/types/systeme";
import { ConfirmDialog } from "./ConfirmDialog";
import { NodeAcme } from "./NodeAcme";
import { NodeCerts } from "./NodeCerts";
import { NodeConfig } from "./NodeConfig";
import { NodeRepos } from "./NodeRepos";
import { Button, Notice } from "./ui";

import { tr, T, locale } from "../lib/i18n";
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(locale()) : "–");
const daysLeft = (iso: string | null) => (iso ? Math.floor((new Date(iso).getTime() - Date.now()) / 86_400_000) : null);

/** Une rubrique : contenu si lisible, sinon la raison (droit manquant, erreur) sans bloquer les autres. */
function Block<T>({ title, section, hint, children }: { title: string; section: Section<T> | undefined; hint?: string; children: (d: T) => React.ReactNode }) {
  return (
    <div className="panel space-y-2 p-4">
      <h3 className="font-semibold">{title}</h3>
      {!section ? <div className="h-10 animate-pulse rounded bg-surface2" />
        : section.state === "forbidden" ? <p className="text-sm text-muted">{tr("Droit manquant pour le token de Kaji{p}. La page « Accès » donne la commande à copier.", { p: hint ? ` (${hint})` : "" })}</p>
        : section.state === "error" || !section.data ? <p className="text-sm text-danger">{tr("Lecture impossible.")}</p>
        : children(section.data)}
    </div>
  );
}

export function NodeSystem({ connId, node, online }: { connId: number; node: string; online: boolean }) {
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}`;
  const q = useQuery({ queryKey: ["node-system", connId, node], enabled: online, staleTime: 30_000, queryFn: () => api<Sys>(`${base}/system`) });
  const [logOn, setLogOn] = useState(false);
  // Message des actions sur les services : gardé ICI (et non dans `Services`) car la section peut se remplacer par « Lecture impossible » pendant qu'un service redémarre, et le composant disparaîtrait avec son message.
  const [svcMsg, setSvcMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const log = useQuery({ queryKey: ["node-syslog", connId, node], enabled: online && logOn, staleTime: 5_000, queryFn: () => api<SyslogLines>(`${base}/syslog?limit=200`) });
  if (!online) return <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{tr("Nœud hors ligne : système indisponible.")}</div>;
  if (q.error) return <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>{tr("réessayer")}</button></Notice>;
  const d = q.data;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">{tr("Les services se pilotent ici (droit Sys.Modify) ; mises à jour, disques et le reste se modifient pour l'instant dans Proxmox.")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Block title={tr("Version")} section={d?.status}>{(s) => (
          <dl className="space-y-1 text-sm"><div>{s.pveversion ?? "–"}</div><div className="text-muted">{tr("Noyau {p} · démarrage {p2}", { p: s.kernel ?? "–", p2: s.boot_mode ?? "–" })}</div><div className="text-muted">{tr("Actif depuis {p}", { p: s.uptime != null ? uptime(s.uptime) : "–" })}</div></dl>)}</Block>
        <Block title={tr("Heure et DNS")} section={d?.time}>{(t) => (
          <div className="space-y-1 text-sm"><div>{t.timezone ?? "–"} · {when(t.localtime)}</div>
            {d?.dns.state === "ok" && d.dns.data && <div className="text-muted">{tr("DNS {p} · domaine {p2}", { p: d.dns.data.servers.join(", ") || "–", p2: d.dns.data.search ?? "–" })}</div>}</div>)}</Block>
      </div>

      <NodeConfig key={`${d?.dns.data?.search}|${d?.time.data?.timezone}`} connId={connId} node={node} dns={d?.dns.data ?? null} timezone={d?.time.data?.timezone ?? null} />

      <Block title={tr("Mises à jour disponibles{p}", { p: d?.updates.data ? ` (${d.updates.data.length})` : "" })} section={d?.updates} hint={tr("Sys.Modify")}>{(u) => <Updates connId={connId} node={node} list={u} />}</Block>

      <Block title={tr("Dépôts de paquets")} section={d?.repositories}>{(r) => <NodeRepos connId={connId} node={node} repos={r} />}</Block>

      <div className="grid gap-3 sm:grid-cols-2">
        <Block title={tr("Certificats")} section={d?.certificates}>{(c) => (
          <div className="space-y-2 text-sm">{c.map((x) => { const left = daysLeft(x.not_after); return (
            <div key={x.file ?? x.fingerprint}><div className="font-medium">{x.file}</div><div className="truncate text-xs text-muted" title={x.subject ?? ""}>{x.subject}</div>
              <div className={`text-xs ${left != null && left < 30 ? "text-danger" : "text-muted"}`}>{tr("Expire le {p}{p2}", { p: when(x.not_after), p2: left != null && ` (${left} j)` })}</div></div>); })}
            <NodeCerts connId={connId} node={node} hasCustom={c.some((x) => x.file === "pveproxy-ssl.pem")} />
            <NodeAcme connId={connId} node={node} enabled={true} /></div>)}</Block>
      </div>

      {svcMsg && <Notice kind={svcMsg.kind}>{svcMsg.text}</Notice>}
      <Block title={tr("Services")} section={d?.services}>{(list) => <Services connId={connId} node={node} list={list} setMsg={setSvcMsg} />}</Block>

      <div className="panel space-y-2 p-4">
        <div className="flex items-center justify-between"><h3 className="font-semibold">{tr("Journal système")}</h3>
          <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => (logOn ? log.refetch() : setLogOn(true))}>{logOn ? tr("Actualiser") : tr("Afficher")}</Button></div>
        {log.isFetching && !log.data ? <div className="h-10 animate-pulse rounded bg-surface2" />
          : log.error ? <p className="text-sm text-muted">{tr("{message}. Le journal exige le droit", { message: (log.error as Error).message })}{" "}<code>{tr("Sys.Syslog")}</code>{" "}{tr("(page « Accès »).")}</p>
          : log.data ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-surface2 p-2 text-xs" tabIndex={0}>{log.data.lines.map((l) => l.text).join("\n") || tr("Journal vide.")}</pre> : null}
      </div>
    </div>
  );
}

const VERB: Record<ServiceAction, [string, string]> = { start: [T("Démarrer"), T("Démarrage")], stop: [T("Arrêter"), T("Arrêt")], restart: [T("Redémarrer"), T("Redémarrage")], reload: [T("Recharger"), T("Rechargement")] };
const WARN: Record<Service["risk"], string> = {
  normal: "",
  get sensitive() { return tr("Ce service est utilisé par Proxmox : l'API, les consoles, le pare-feu ou la haute disponibilité peuvent être coupés un court moment."); },
  get vital() { return tr("Service vital du cluster : un redémarrage peut faire perdre le quorum ou geler le cluster un moment."); },
};

function Services({ connId, node, list, setMsg }: { connId: number; node: string; list: Service[]; setMsg: (m: { kind: "ok" | "error"; text: string } | null) => void }) {
  const qc = useQueryClient();
  const [ask, setAsk] = useState<{ s: Service; action: ServiceAction } | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/services`;
  const run = async (s: Service, action: ServiceAction) => {
    setAsk(null); setBusy(s.name); setMsg(null);
    try {
      await runTask(connId, node, () => api(`${base}/${s.name}/${action}`, { method: "POST", body: { confirm: true, type_name: s.risk === "vital" ? typed : undefined } }), tr(VERB[action][1]));
      setMsg({ kind: "ok", text: tr("{p} de « {name} » terminé.", { p: tr(VERB[action][1]), name: s.name }) });
    } catch (e) {
      // `pvedaemon` exécute lui-même la tâche : en se redémarrant il l'interrompt, et Proxmox la marque « échec (received interrupt) » alors que le service est reparti.
      // On ne le dit réussi qu'après avoir RELU l'état du service (running), jamais sur le seul texte de l'erreur.
      let restarted = false;
      if (s.name === "pvedaemon" && (action === "restart" || action === "reload") && (e as Error).message.includes("received interrupt")) {
        try {
          await new Promise((r) => setTimeout(r, 2500));
          const fresh = await api<{ services?: { data?: Service[] } }>(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/system`);
          restarted = fresh.services?.data?.find((x) => x.name === s.name)?.state === "running";
        } catch { /* illisible : on garde l'erreur d'origine */ }
      }
      setMsg(restarted
        ? { kind: "ok", text: tr("{p} de « {name} » terminé : le service est reparti (Proxmox signale « interrompu », car ce démon exécute lui-même la tâche).", { p: tr(VERB[action][1]), name: s.name }) }
        : { kind: "error", text: (e as Error).message });
    }
    setBusy(null); setTyped("");
    qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
  };
  const actions = (s: Service): ServiceAction[] => {
    const run_ = s.state === "running";
    return [...(run_ ? [] : ["start" as const]), ...(run_ && s.stoppable ? ["stop" as const] : []), ...(run_ ? ["restart" as const, "reload" as const] : [])];
  };
  return (
    <div className="space-y-2">
      <div className="divide-y divide-line/60 text-sm">
        {list.map((x) => (
          <div key={x.name} className="flex flex-wrap items-center gap-2 py-1.5">
            <span className={`size-2 rounded-full ${x.state === "running" ? "bg-ok" : "bg-muted"}`} />
            <span className="font-medium">{x.name}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-muted">{x.description}</span>
            {x.manageable && actions(x).map((a) => (
              <Button key={a} variant="ghost" className="!px-2 !py-1 text-xs" disabled={busy !== null}
                onClick={() => { setTyped(""); a === "start" ? run(x, a) : setAsk({ s: x, action: a }); }}>{busy === x.name ? "…" : tr(VERB[a][0])}</Button>
            ))}
          </div>
        ))}
      </div>
      {ask && (
        <ConfirmDialog title={tr("{p} « {name} » sur {node} ?", { p: tr(VERB[ask.action][0]), name: ask.s.name, node })} confirmLabel={tr(VERB[ask.action][0])} danger={ask.s.risk !== "normal"}
          onCancel={() => setAsk(null)} onConfirm={() => { if (ask.s.risk === "vital" && typed !== ask.s.name) return; run(ask.s, ask.action); }}>
          <div className="space-y-3">
            <p>{WARN[ask.s.risk] || tr("Le service sera ") + (ask.action === "stop" ? tr("arrêté.") : ask.action === "reload" ? tr("rechargé.") : tr("redémarré."))}</p>
            {ask.s.risk === "vital" && (
              <label className="block text-xs">{tr("Retape")}{" "}<code>{ask.s.name}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg" />
              </label>
            )}
          </div>
        </ConfirmDialog>
      )}
    </div>
  );
}

const UPGRADE_CMD = "apt update && apt dist-upgrade";

function Updates({ connId, node, list }: { connId: number; node: string; list: NonNullable<Sys["updates"]["data"]> }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const refresh = async () => {
    setBusy(true); setMsg(null);
    try {
      await runTask(connId, node, () => api(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/apt/update`, { method: "POST" }), tr("Actualisation"));
      setMsg({ kind: "ok", text: tr("Liste des paquets actualisée.") });
    } catch (e) { setMsg({ kind: "error", text: (e as Error).message }); }
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
  };
  const copy = async () => { try { await navigator.clipboard.writeText(UPGRADE_CMD); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* presse-papiers indisponible */ } };
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className={`text-sm ${list.length === 0 ? "text-ok" : "text-muted"}`}>{list.length === 0 ? tr("Le nœud est à jour (selon la dernière actualisation).") : tr("{length} paquet(s) peuvent être mis à jour.", { length: list.length })}</p>
        <Button variant="ghost" className="!px-3 !py-1.5" disabled={busy} onClick={refresh}>{busy ? tr("Actualisation…") : tr("Actualiser la liste")}</Button>
      </div>
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      {list.length > 0 && <>
        <div className="max-h-64 overflow-auto"><table className="w-full text-sm"><tbody>{list.map((p) => (
          <tr key={p.package} className="border-b border-line/60 last:border-0"><td className="py-1 pr-3 font-medium">{p.package}</td><td className="py-1 pr-3 text-muted">{p.from ?? "–"} → {p.to ?? "–"}</td><td className="py-1 text-muted">{p.title}</td></tr>))}</tbody></table></div>
        <div className="rounded-xl border border-line bg-surface2 p-3 text-xs text-muted">
          <p>{tr("Proxmox n'installe pas les mises à jour par son API : elles se lancent dans un terminal. Kaji ne le fait pas à ta place. Ouvre la console du nœud (section plus haut) et lance :")}</p>
          <div className="mt-2 flex items-center gap-2"><code className="flex-1 rounded bg-surface px-2 py-1 text-fg">{UPGRADE_CMD}</code><Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={copy}>{copied ? tr("Copié") : tr("Copier")}</Button></div>
          <p className="mt-2">{tr("Après une mise à jour du noyau, redémarre le nœud (boutons en haut de la section Système).")}</p>
        </div>
      </>}
    </div>
  );
}
