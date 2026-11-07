import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { uptime } from "../lib/format";
import { runTask } from "../lib/tasks";
import type { NodeSystem as Sys, Section, Service, ServiceAction, SyslogLines } from "../lib/types/systeme";
import { ConfirmDialog } from "./ConfirmDialog";
import { NodeCerts } from "./NodeCerts";
import { NodeConfig } from "./NodeConfig";
import { NodeRepos } from "./NodeRepos";
import { Button, Notice } from "./ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR") : "–");
const daysLeft = (iso: string | null) => (iso ? Math.floor((new Date(iso).getTime() - Date.now()) / 86_400_000) : null);

/** Une rubrique : contenu si lisible, sinon la raison (droit manquant, erreur) sans bloquer les autres. */
function Block<T>({ title, section, hint, children }: { title: string; section: Section<T> | undefined; hint?: string; children: (d: T) => React.ReactNode }) {
  return (
    <div className="panel space-y-2 p-4">
      <h3 className="font-semibold">{title}</h3>
      {!section ? <div className="h-10 animate-pulse rounded bg-surface2" />
        : section.state === "forbidden" ? <p className="text-sm text-muted">Droit manquant pour le token de Kaji{hint ? ` (${hint})` : ""}. La page « Accès » donne la commande à copier.</p>
        : section.state === "error" || !section.data ? <p className="text-sm text-danger">Lecture impossible.</p>
        : children(section.data)}
    </div>
  );
}

export function NodeSystem({ connId, node, online }: { connId: number; node: string; online: boolean }) {
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}`;
  const q = useQuery({ queryKey: ["node-system", connId, node], enabled: online, staleTime: 30_000, queryFn: () => api<Sys>(`${base}/system`) });
  const [logOn, setLogOn] = useState(false);
  const log = useQuery({ queryKey: ["node-syslog", connId, node], enabled: online && logOn, staleTime: 5_000, queryFn: () => api<SyslogLines>(`${base}/syslog?limit=200`) });
  if (!online) return <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">Nœud hors ligne : système indisponible.</div>;
  if (q.error) return <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>réessayer</button></Notice>;
  const d = q.data;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">Les services se pilotent ici (droit Sys.Modify) ; mises à jour, disques et le reste se modifient pour l'instant dans Proxmox.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Version" section={d?.status}>{(s) => (
          <dl className="space-y-1 text-sm"><div>{s.pveversion ?? "–"}</div><div className="text-muted">Noyau {s.kernel ?? "–"} · démarrage {s.boot_mode ?? "–"}</div><div className="text-muted">Actif depuis {s.uptime != null ? uptime(s.uptime) : "–"}</div></dl>)}</Block>
        <Block title="Heure et DNS" section={d?.time}>{(t) => (
          <div className="space-y-1 text-sm"><div>{t.timezone ?? "–"} · {when(t.localtime)}</div>
            {d?.dns.state === "ok" && d.dns.data && <div className="text-muted">DNS {d.dns.data.servers.join(", ") || "–"} · domaine {d.dns.data.search ?? "–"}</div>}</div>)}</Block>
      </div>

      <NodeConfig key={`${d?.dns.data?.search}|${d?.time.data?.timezone}`} connId={connId} node={node} dns={d?.dns.data ?? null} timezone={d?.time.data?.timezone ?? null} />

      <Block title={`Mises à jour disponibles${d?.updates.data ? ` (${d.updates.data.length})` : ""}`} section={d?.updates} hint="Sys.Modify">{(u) => <Updates connId={connId} node={node} list={u} />}</Block>

      <Block title="Dépôts de paquets" section={d?.repositories}>{(r) => <NodeRepos connId={connId} node={node} repos={r} />}</Block>

      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Certificats" section={d?.certificates}>{(c) => (
          <div className="space-y-2 text-sm">{c.map((x) => { const left = daysLeft(x.not_after); return (
            <div key={x.file ?? x.fingerprint}><div className="font-medium">{x.file}</div><div className="truncate text-xs text-muted" title={x.subject ?? ""}>{x.subject}</div>
              <div className={`text-xs ${left != null && left < 30 ? "text-danger" : "text-muted"}`}>Expire le {when(x.not_after)}{left != null && ` (${left} j)`}</div></div>); })}
            <NodeCerts connId={connId} node={node} hasCustom={c.some((x) => x.file === "pveproxy-ssl.pem")} /></div>)}</Block>
      </div>

      <Block title="Services" section={d?.services}>{(list) => <Services connId={connId} node={node} list={list} />}</Block>

      <div className="panel space-y-2 p-4">
        <div className="flex items-center justify-between"><h3 className="font-semibold">Journal système</h3>
          <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => (logOn ? log.refetch() : setLogOn(true))}>{logOn ? "Actualiser" : "Afficher"}</Button></div>
        {log.isFetching && !log.data ? <div className="h-10 animate-pulse rounded bg-surface2" />
          : log.error ? <p className="text-sm text-muted">{(log.error as Error).message}. Le journal exige le droit <code>Sys.Syslog</code> (page « Accès »).</p>
          : log.data ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-surface2 p-2 text-xs" tabIndex={0}>{log.data.lines.map((l) => l.text).join("\n") || "Journal vide."}</pre> : null}
      </div>
    </div>
  );
}

const VERB: Record<ServiceAction, [string, string]> = { start: ["Démarrer", "Démarrage"], stop: ["Arrêter", "Arrêt"], restart: ["Redémarrer", "Redémarrage"], reload: ["Recharger", "Rechargement"] };
const WARN: Record<Service["risk"], string> = {
  normal: "",
  sensitive: "Ce service est utilisé par Proxmox : l'API, les consoles, le pare-feu ou la haute disponibilité peuvent être coupés un court moment.",
  vital: "Service vital du cluster : un redémarrage peut faire perdre le quorum ou geler le cluster un moment.",
};

function Services({ connId, node, list }: { connId: number; node: string; list: Service[] }) {
  const qc = useQueryClient();
  const [ask, setAsk] = useState<{ s: Service; action: ServiceAction } | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/services`;
  const run = async (s: Service, action: ServiceAction) => {
    setAsk(null); setBusy(s.name); setMsg(null);
    try {
      await runTask(connId, node, () => api(`${base}/${s.name}/${action}`, { method: "POST", body: { confirm: true, type_name: s.risk === "vital" ? typed : undefined } }), VERB[action][1]);
      setMsg({ kind: "ok", text: `${VERB[action][1]} de « ${s.name} » terminé.` });
    } catch (e) { setMsg({ kind: "error", text: (e as Error).message }); }
    setBusy(null); setTyped("");
    qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
  };
  const actions = (s: Service): ServiceAction[] => {
    const run_ = s.state === "running";
    return [...(run_ ? [] : ["start" as const]), ...(run_ && s.stoppable ? ["stop" as const] : []), ...(run_ ? ["restart" as const, "reload" as const] : [])];
  };
  return (
    <div className="space-y-2">
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      <div className="divide-y divide-line/60 text-sm">
        {list.map((x) => (
          <div key={x.name} className="flex flex-wrap items-center gap-2 py-1.5">
            <span className={`size-2 rounded-full ${x.state === "running" ? "bg-ok" : "bg-muted"}`} />
            <span className="font-medium">{x.name}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-muted">{x.description}</span>
            {x.manageable && actions(x).map((a) => (
              <Button key={a} variant="ghost" className="!px-2 !py-1 text-xs" disabled={busy !== null}
                onClick={() => { setTyped(""); a === "start" ? run(x, a) : setAsk({ s: x, action: a }); }}>{busy === x.name ? "…" : VERB[a][0]}</Button>
            ))}
          </div>
        ))}
      </div>
      {ask && (
        <ConfirmDialog title={`${VERB[ask.action][0]} « ${ask.s.name} » sur ${node} ?`} confirmLabel={VERB[ask.action][0]} danger={ask.s.risk !== "normal"}
          onCancel={() => setAsk(null)} onConfirm={() => { if (ask.s.risk === "vital" && typed !== ask.s.name) return; run(ask.s, ask.action); }}>
          <div className="space-y-3">
            <p>{WARN[ask.s.risk] || "Le service sera " + (ask.action === "stop" ? "arrêté." : ask.action === "reload" ? "rechargé." : "redémarré.")}</p>
            {ask.s.risk === "vital" && (
              <label className="block text-xs">Retape <code>{ask.s.name}</code> pour confirmer
                <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg" />
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
      await runTask(connId, node, () => api(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/apt/update`, { method: "POST" }), "Actualisation");
      setMsg({ kind: "ok", text: "Liste des paquets actualisée." });
    } catch (e) { setMsg({ kind: "error", text: (e as Error).message }); }
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
  };
  const copy = async () => { try { await navigator.clipboard.writeText(UPGRADE_CMD); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* presse-papiers indisponible */ } };
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className={`text-sm ${list.length === 0 ? "text-ok" : "text-muted"}`}>{list.length === 0 ? "Le nœud est à jour (selon la dernière actualisation)." : `${list.length} paquet(s) peuvent être mis à jour.`}</p>
        <Button variant="ghost" className="!px-3 !py-1.5" disabled={busy} onClick={refresh}>{busy ? "Actualisation…" : "Actualiser la liste"}</Button>
      </div>
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      {list.length > 0 && <>
        <div className="max-h-64 overflow-auto"><table className="w-full text-sm"><tbody>{list.map((p) => (
          <tr key={p.package} className="border-b border-line/60 last:border-0"><td className="py-1 pr-3 font-medium">{p.package}</td><td className="py-1 pr-3 text-muted">{p.from ?? "–"} → {p.to ?? "–"}</td><td className="py-1 text-muted">{p.title}</td></tr>))}</tbody></table></div>
        <div className="rounded-xl border border-line bg-surface2 p-3 text-xs text-muted">
          <p>Proxmox n'installe pas les mises à jour par son API : elles se lancent dans un terminal. Kaji ne le fait pas à ta place. Ouvre la console du nœud (section plus haut) et lance :</p>
          <div className="mt-2 flex items-center gap-2"><code className="flex-1 rounded bg-surface px-2 py-1 text-fg">{UPGRADE_CMD}</code><Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={copy}>{copied ? "Copié" : "Copier"}</Button></div>
          <p className="mt-2">Après une mise à jour du noyau, redémarre le nœud (boutons en haut de la section Système).</p>
        </div>
      </>}
    </div>
  );
}
