import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { Button, Notice } from "./ui";

type Result = { file: string; content: string; commands: string[]; warnings: string[] };
const field = "mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg";

/** Serveurs NTP : l'API de Proxmox n'a pas de route NTP ; Kaji valide les champs et fabrique le fichier de sources `chrony` et les commandes à coller dans la console du nœud (rien n'est envoyé à Proxmox). */
export function NtpForm({ base }: { base: string }) {
  const [name, setName] = useState("serveurs-ntp"), [hosts, setHosts] = useState(""), [kind, setKind] = useState<"server" | "pool">("server");
  const [iburst, setIburst] = useState(true), [nts, setNts] = useState(false);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null), [copied, setCopied] = useState<number | null>(null);
  const list = hosts.split(/\s+/).filter(Boolean);

  const generate = async () => {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api<Result>(`${base}/ntp/commands`, { method: "POST", body: { name, sources: list.map((host) => ({ host, kind, iburst, nts })) } })); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const copy = async (i: number, text: string) => { try { await navigator.clipboard.writeText(text); setCopied(i); setTimeout(() => setCopied(null), 2000); } catch { /* presse-papiers indisponible */ } };

  return (
    <form className="space-y-2 text-sm" onSubmit={(e) => { e.preventDefault(); if (list.length) generate(); }}>
      <p className="text-xs text-muted">{tr("L'API de Proxmox n'a pas de réglage NTP : Kaji prépare le fichier de sources chrony et les commandes à coller dans la console du nœud. Rien n'est envoyé à Proxmox.")}</p>
      <label className="block text-xs text-muted">{tr("Nom du fichier")}<input value={name} onChange={(e) => setName(e.target.value)} className={field} /></label>
      <label className="block text-xs text-muted">{tr("Serveurs (un par ligne, 4 au plus)")}<textarea value={hosts} onChange={(e) => setHosts(e.target.value)} rows={3} className={field} placeholder="0.fr.pool.ntp.org" /></label>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <label className="flex items-center gap-1">{tr("Type")}
          <select value={kind} onChange={(e) => setKind(e.target.value as "server" | "pool")} className="rounded border border-line bg-surface2 px-1 py-0.5">
            <option value="server">{tr("Serveur")}</option><option value="pool">{tr("Pool (nom d'hôte)")}</option></select></label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={iburst} onChange={(e) => setIburst(e.target.checked)} />{tr("iburst (synchronisation rapide au démarrage)")}</label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={nts} onChange={(e) => setNts(e.target.checked)} />{tr("NTS (chiffré, si le serveur le propose)")}</label>
      </div>
      {err && <Notice kind="error">{err}</Notice>}
      <Button type="submit" disabled={busy || !list.length}>{busy ? "…" : tr("Générer les commandes")}</Button>
      {res && (
        <div className="space-y-2 border-t border-line/60 pt-2" aria-live="polite">
          {res.warnings.map((w) => <p key={w} className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">{tr("Attention : {w}", { w: tr(w) })}</p>)}
          <p className="text-xs text-muted">{tr("Colle ces commandes dans la console du nœud, l'une après l'autre :")}</p>
          {res.commands.map((c, i) => (
            <div key={i} className="flex items-start gap-2">
              <pre className="min-w-0 flex-1 overflow-x-auto rounded bg-surface px-2 py-1 text-xs text-fg">{c}</pre>
              <Button type="button" variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => copy(i, c)}>{copied === i ? tr("Copié") : tr("Copier")}</Button>
            </div>))}
        </div>)}
    </form>
  );
}
