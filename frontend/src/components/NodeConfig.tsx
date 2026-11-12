import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { NtpForm } from "./NtpForm";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
type Msg = { kind: "ok" | "error"; text: string } | null;
const field = "mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg";
const zones = (): string[] => { try { return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone"); } catch { return []; } };

/** DNS, fuseau horaire et fichier hosts d'un nœud. Le serveur vérifie tout (digest, ligne du nœud, adresses) : ici, seulement la saisie. */
export function NodeConfig({ connId, node, dns, timezone }: { connId: number; node: string; dns: { search: string | null; servers: string[] } | null; timezone: string | null }) {
  const qc = useQueryClient();
  const base = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}`;
  const [open, setOpen] = useState<"dns" | "time" | "hosts" | "ntp" | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState(dns?.search ?? "");
  const [servers, setServers] = useState((dns?.servers ?? []).join("\n"));
  const [tz, setTz] = useState(timezone ?? "");
  const [hosts, setHosts] = useState("");
  const hostsQ = useQuery({ queryKey: ["node-hosts", connId, node], enabled: open === "hosts", staleTime: 0, gcTime: 0, queryFn: () => api<{ content: string; digest: string | null }>(`${base}/hosts`) });
  useEffect(() => { if (hostsQ.data) setHosts(hostsQ.data.content); }, [hostsQ.data]);

  const save = async (what: string, path: string, body: unknown) => {
    setBusy(true); setMsg(null);
    try {
      await api(`${base}/${path}`, { method: "PUT", body });
      setMsg({ kind: "ok", text: tr("{what} enregistré.", { what }) });
      setOpen(null);
      qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
    } catch (e) { setMsg({ kind: "error", text: (e as Error).message }); }
    setBusy(false);
  };
  const toggle = (k: "dns" | "time" | "hosts" | "ntp") => { setMsg(null); setOpen(open === k ? null : k); };

  return (
    <div className="panel space-y-3 p-4">
      <h3 className="font-semibold">{tr("Configuration du nœud")}</h3>
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => toggle("dns")}>{tr("DNS")}</Button>
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => toggle("time")}>{tr("Fuseau horaire")}</Button>
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => toggle("hosts")}>{tr("Fichier hosts")}</Button>
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => toggle("ntp")}>{tr("Serveurs NTP…")}</Button>
      </div>
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      {open === "dns" && (
        <form className="space-y-2 text-sm" onSubmit={(e) => { e.preventDefault(); save("DNS", "dns", { search, servers: servers.split(/\s+/).filter(Boolean), confirm: true }); }}>
          <label className="block text-xs text-muted">{tr("Domaine de recherche")}<input value={search} onChange={(e) => setSearch(e.target.value)} className={field} /></label>
          <label className="block text-xs text-muted">{tr("Serveurs DNS (un par ligne, 3 au plus)")}<textarea value={servers} onChange={(e) => setServers(e.target.value)} rows={3} className={field} /></label>
          <p className="text-xs text-muted">{tr("Une erreur ici coupe la résolution de noms du nœud (mises à jour, ACME, sauvegardes distantes).")}</p>
          <Button type="submit" disabled={busy}>{tr("Enregistrer le DNS")}</Button>
        </form>)}
      {open === "time" && (
        <form className="space-y-2 text-sm" onSubmit={(e) => { e.preventDefault(); save(tr("Fuseau horaire"), "time", { timezone: tz }); }}>
          <label className="block text-xs text-muted">{tr("Fuseau horaire")}<input list="kaji-zones" value={tz} onChange={(e) => setTz(e.target.value)} className={field} /></label>
          <datalist id="kaji-zones">{zones().map((z) => <option key={z} value={z} />)}</datalist>
          <Button type="submit" disabled={busy || !tz}>{tr("Enregistrer le fuseau")}</Button>
        </form>)}
      {open === "ntp" && <NtpForm base={base} />}
      {open === "hosts" && (
        hostsQ.isLoading ? <div className="h-24 animate-pulse rounded bg-surface2" />
          : hostsQ.error || !hostsQ.data?.digest ? <Notice kind="error">{tr("Lecture du fichier hosts impossible.")}</Notice>
          : <form className="space-y-2 text-sm" onSubmit={(e) => { e.preventDefault(); save(tr("Fichier hosts"), "hosts", { content: hosts, digest: hostsQ.data!.digest, confirm: true }); }}>
            <textarea value={hosts} onChange={(e) => setHosts(e.target.value)} rows={12} spellCheck={false} className={`${field} font-mono text-xs`} aria-label={tr("Contenu du fichier hosts")} />
            <p className="text-xs text-muted">{tr("Doit garder")}{" "}<code>{tr("localhost")}</code>{" "}{tr("et une ligne avec l'adresse du nœud « {node} » : sinon le cluster ne démarre plus. Refusé si le fichier a changé entre-temps.", { node })}</p>
            <Button type="submit" disabled={busy || hosts === hostsQ.data.content}>{tr("Enregistrer le fichier hosts")}</Button>
          </form>)}
    </div>
  );
}
