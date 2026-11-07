import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { runTask } from "../lib/tasks";
import type { AcmeInfo } from "../lib/types/acme";
import { ConfirmDialog } from "./ConfirmDialog";
import { Button, Notice } from "./ui";

const field = "mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg";
type Msg = { kind: "ok" | "error"; text: string } | null;

/** Certificats automatiques (ACME). Contacte une autorité extérieure : adresse de contact transmise, conditions à accepter. Plugins DNS : lecture seule. */
export function NodeAcme({ connId, node, enabled }: { connId: number; node: string; enabled: boolean }) {
  const qc = useQueryClient();
  const base = `/api/connections/${connId}`;
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["node-acme", connId, node], enabled: enabled && open, staleTime: 15_000, queryFn: () => api<AcmeInfo>(`${base}/nodes/${encodeURIComponent(node)}/acme`) });
  const d = q.data;
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"account" | "config" | null>(null);
  const [ask, setAsk] = useState<"order" | "renew" | { del: string } | null>(null);
  const [typed, setTyped] = useState("");
  const [replace, setReplace] = useState(false);
  // formulaire de compte
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [dir, setDir] = useState("");
  const [tos, setTos] = useState(false);
  // formulaire du nœud
  const [account, setAccount] = useState("");
  const [domains, setDomains] = useState("");

  const refresh = () => { qc.invalidateQueries({ queryKey: ["node-acme", connId, node] }); qc.invalidateQueries({ queryKey: ["node-system", connId, node] }); };
  const act = async (label: string, fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ kind: "ok", text: `${label} : fait.` }); after?.(); refresh(); } catch (e) { setMsg({ kind: "error", text: (e as Error).message }); }
    setBusy(false); setAsk(null);
  };
  const directories = d?.directories.data ?? [];
  const staging = directories.find((x) => x.url.includes("staging"));
  const accounts = d?.accounts.data ?? [];
  const cfg = d?.config.data;

  return (
    <div className="space-y-2">
      <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setOpen(!open)}>{open ? "Masquer les certificats automatiques (ACME)" : "Certificats automatiques (ACME)…"}</Button>
      {open && (q.isLoading ? <div className="h-16 animate-pulse rounded bg-surface2" /> : q.error || !d ? <Notice kind="error">Lecture ACME impossible.</Notice> : (
        <div className="space-y-3 rounded-lg border border-line p-3 text-sm">
          {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
          <div>
            <div className="font-medium">Comptes</div>
            {d.accounts.state === "forbidden" ? <p className="text-xs text-muted">Droit manquant (page « Accès »).</p> : accounts.length === 0 ? <p className="text-xs text-muted">Aucun compte.</p>
              : accounts.map((a) => (<div key={a.name} className="flex flex-wrap items-center justify-between gap-2 text-xs"><span><b>{a.name}</b> · {a.contact.join(", ") || "–"} · {a.directory?.includes("staging") ? "TEST (staging)" : "production"}</span>
                <Button variant="danger" className="!px-2 !py-1 text-xs" disabled={busy} onClick={() => { setTyped(""); setAsk({ del: a.name }); }}>Supprimer</Button></div>))}
            <Button variant="ghost" className="mt-1 !px-2 !py-1 text-xs" onClick={() => { setMode(mode === "account" ? null : "account"); setDir(staging?.url ?? directories[0]?.url ?? ""); setTos(false); }}>Créer un compte…</Button>
          </div>
          {mode === "account" && (
            <form className="space-y-2" autoComplete="off" onSubmit={(e) => { e.preventDefault(); act("Création du compte", () => runTask(connId, node, () => api(`${base}/acme/accounts`, { method: "POST", body: { name, contact, directory: dir, accept_tos: tos, confirm: true } }), "Création du compte", 120), () => setMode(null)); }}>
              <label className="block text-xs text-muted">Nom du compte<input value={name} onChange={(e) => setName(e.target.value)} className={field} /></label>
              <label className="block text-xs text-muted">Adresse de contact (transmise à l'autorité)<input type="email" value={contact} onChange={(e) => setContact(e.target.value)} className={field} /></label>
              <label className="block text-xs text-muted">Autorité<select value={dir} onChange={(e) => setDir(e.target.value)} className={field}>{directories.map((x) => <option key={x.url} value={x.url}>{x.name}{x.url.includes("staging") ? " — test, certificat non approuvé" : ""}</option>)}</select></label>
              <label className="flex gap-2 text-xs"><input type="checkbox" checked={tos} onChange={(e) => setTos(e.target.checked)} /><span>J'accepte les conditions d'utilisation de l'autorité{d.tos.data && <> (<a className="underline" href={d.tos.data} target="_blank" rel="noreferrer">lire</a>)</>}.</span></label>
              <Button type="submit" disabled={busy || !tos || !name || !contact || !dir}>Créer le compte</Button>
            </form>)}
          <div>
            <div className="font-medium">Domaines de ce nœud</div>
            <p className="text-xs text-muted">{cfg?.account ? <>Compte <b>{cfg.account}</b> · {cfg.domains.map((x) => x.domain + (x.plugin ? ` (${x.plugin})` : "")).join(", ") || "aucun domaine"}</> : "Pas de configuration ACME."}</p>
            <Button variant="ghost" className="mt-1 !px-2 !py-1 text-xs" onClick={() => { setMode(mode === "config" ? null : "config"); setAccount(cfg?.account ?? accounts[0]?.name ?? ""); setDomains((cfg?.domains ?? []).map((x) => x.domain + (x.plugin ? `,${x.plugin}` : "")).join("\n")); }}>Modifier…</Button>
          </div>
          {mode === "config" && (
            <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); act("Configuration ACME", () => api(`${base}/nodes/${encodeURIComponent(node)}/acme/config`, { method: "PUT", body: { account, confirm: true, digest: cfg?.digest ?? undefined,
              domains: domains.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [domain, plugin] = l.split(","); return { domain: domain.trim(), plugin: plugin?.trim() || null }; }) } }), () => setMode(null)); }}>
              <label className="block text-xs text-muted">Compte<select value={account} onChange={(e) => setAccount(e.target.value)} className={field}>{accounts.map((a) => <option key={a.name}>{a.name}</option>)}</select></label>
              <label className="block text-xs text-muted">Domaines (un par ligne : <code>domaine</code> ou <code>domaine,plugin</code> ; plugins : {(d.plugins.data ?? []).map((p) => p.id).join(", ") || "aucun"})
                <textarea value={domains} onChange={(e) => setDomains(e.target.value)} rows={3} className={`${field} font-mono text-xs`} /></label>
              <p className="text-xs text-muted">Le plugin « standalone » exige que le port 80 du nœud soit joignable depuis Internet ; un domaine générique (*.) exige un plugin DNS.</p>
              <Button type="submit" disabled={busy || !account || !domains.trim()}>Enregistrer</Button>
            </form>)}
          {cfg?.account && cfg.domains.length > 0 && (
            <div className="flex flex-wrap gap-2 border-t border-line/60 pt-2">
              <Button variant="danger" className="!px-3 !py-1.5" disabled={busy} onClick={() => { setReplace(false); setAsk("order"); }}>Commander le certificat</Button>
              <Button variant="ghost" className="!px-3 !py-1.5" disabled={busy} onClick={() => setAsk("renew")}>Renouveler</Button>
            </div>)}
        </div>))}
      {ask && typeof ask === "string" && (
        <ConfirmDialog title={ask === "order" ? `Commander un certificat pour ${node} ?` : `Renouveler le certificat de ${node} ?`} confirmLabel={ask === "order" ? "Commander" : "Renouveler"} danger onCancel={() => setAsk(null)}
          onConfirm={() => act(ask === "order" ? "Commande" : "Renouvellement", () => runTask(connId, node, () => api(`${base}/nodes/${encodeURIComponent(node)}/acme/${ask}`, { method: "POST", body: { confirm: true, replace_existing: replace } }), "ACME", 300))}>
          <div className="space-y-2"><p>L'autorité va valider tes domaines puis émettre un certificat ; pveproxy redémarre. Les commandes en production sont limitées en nombre par l'autorité.</p>
            {ask === "order" && <label className="flex gap-2"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /><span>Remplacer un certificat personnalisé déjà installé</span></label>}</div>
        </ConfirmDialog>)}
      {ask && typeof ask === "object" && (
        <ConfirmDialog title={`Supprimer le compte « ${ask.del} » ?`} confirmLabel="Supprimer" danger onCancel={() => setAsk(null)}
          onConfirm={() => { if (typed !== ask.del) return; const n = ask.del; act("Suppression du compte", () => runTask(connId, node, () => api(`${base}/acme/accounts/${encodeURIComponent(n)}/delete`, { method: "POST", body: { confirm: true, type_name: typed } }), "Suppression du compte", 120)); }}>
          <div className="space-y-2"><p>Le compte est désactivé auprès de l'autorité : c'est irréversible. Refusé tant qu'un nœud l'utilise.</p>
            <label className="block text-xs">Retape <code>{ask.del}</code> pour confirmer<input value={typed} onChange={(e) => setTyped(e.target.value)} className={field} autoComplete="off" /></label></div>
        </ConfirmDialog>)}
    </div>
  );
}
