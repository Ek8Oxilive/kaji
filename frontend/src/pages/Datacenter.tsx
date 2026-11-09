import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { MetricsServers } from "../components/MetricsServers";
import { Button, Field, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { CONSOLES, KEYBOARDS, LANGUAGES, type DatacenterOptions } from "../lib/types/datacenter";

const LABELS: Record<string, string> = { ha: "Haute disponibilité", fencing: "Mode de fencing", crs: "Ordonnancement des ressources", bwlimit: "Limites de débit", "next-id": "Plage des identifiants libres", "tag-style": "Style des étiquettes", replication: "Réplication" };

/** Datacenter → Options et notes. Liste blanche côté serveur ; HA, fencing, CRS, débits : affichés, jamais modifiés ici. */
export function Datacenter({ onGoConnections }: { onGoConnections: () => void }) {
  const { active, id } = useActiveConnection();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["datacenter", id], queryFn: () => api<DatacenterOptions>(`/api/connections/${id}/datacenter/options`), enabled: id !== null });
  const d = q.data;
  const [f, setF] = useState({ keyboard: "", language: "", console: "", email_from: "", mac_prefix: "", max_workers: "", http_proxy: "", mtype: "", mnet: "" });
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);
  useEffect(() => {
    if (!d) return;
    setF({ keyboard: d.keyboard ?? "", language: d.language ?? "", console: d.console ?? "", email_from: d.email_from ?? "", mac_prefix: d.mac_prefix ?? "", max_workers: d.max_workers?.toString() ?? "",
      http_proxy: d.http_proxy ?? "", mtype: d.migration.type ?? "", mnet: d.migration.network ?? "" });
    setNotes(d.description ?? "");
  }, [d]);
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center"><div className="panel space-y-4 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">Aucun cluster connecté</h1><Button onClick={onGoConnections}>Ajouter un cluster</Button></div></div>
  );
  const set = (k: keyof typeof f) => (v: string) => setF((cur) => ({ ...cur, [k]: v }));
  const insecureNew = f.mtype === "insecure" && d?.migration.type !== "insecure";

  /** Corps de la requête : seulement ce qui a changé ; un champ vidé qui avait une valeur est retiré (`clear`). */
  const diff = () => {
    if (!d) return {};
    const body: Record<string, unknown> = {}, clear: string[] = [];
    const text = (k: "keyboard" | "language" | "console" | "email_from" | "mac_prefix" | "http_proxy", cur: string | null) => { if (f[k] !== (cur ?? "")) { if (f[k]) body[k] = f[k]; else clear.push(k); } };
    text("keyboard", d.keyboard); text("language", d.language); text("console", d.console); text("email_from", d.email_from); text("mac_prefix", d.mac_prefix); text("http_proxy", d.http_proxy);
    if (f.max_workers !== (d.max_workers?.toString() ?? "")) { if (f.max_workers) body.max_workers = Number(f.max_workers); else clear.push("max_workers"); }
    if (f.mtype !== (d.migration.type ?? "") || f.mnet !== (d.migration.network ?? "")) {
      if (!f.mtype && !f.mnet) clear.push("migration");
      else body.migration = { ...(f.mtype !== (d.migration.type ?? "") && f.mtype ? { type: f.mtype } : {}), ...(f.mnet !== (d.migration.network ?? "") ? { network: f.mnet } : {}) };
    }
    return { ...body, ...(clear.length ? { clear } : {}) };
  };
  const save = async (what: string, body: Record<string, unknown>) => {
    setBusy(what); setErr(null); setOk(null);
    try {
      await api(`/api/connections/${id}/datacenter/options`, { method: "PUT", body: { ...body, digest: d?.digest, ...(insecureNew && what === "options" ? { confirm: true } : {}) } });
      await qc.invalidateQueries({ queryKey: ["datacenter", id] });
      setOk(what === "notes" ? "Notes enregistrées, relues chez Proxmox." : "Options enregistrées, relues chez Proxmox.");
    } catch (e) { setErr((e as Error).message); }
    setBusy(null);
  };
  const changes = diff(), changed = Object.keys(changes).length > 0;
  const notesChanged = d ? notes !== (d.description ?? "") : false;
  const sel = (label: string, k: keyof typeof f, opts: readonly string[]) => (
    <label className="block space-y-1.5 text-sm"><span className="text-muted">{label}</span>
      <select className="field" value={f[k]} onChange={(e) => set(k)(e.target.value)}><option value="">Défaut de Proxmox</option>{opts.map((o) => <option key={o} value={o}>{o}</option>)}</select></label>);

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header><h1 className="text-2xl font-semibold tracking-tight">Datacenter</h1><p className="text-muted">{active.name} · options et notes</p></header>
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}
      {err && <Notice kind="error">{err}</Notice>}
      {ok && <Notice kind="ok">{ok}</Notice>}
      {!d ? <p className="text-sm text-muted">Chargement…</p> : <>
        <section className="space-y-4"><h2 className="text-lg font-semibold">Options</h2>
          <div className="panel space-y-4 p-5">
            <div className="grid gap-4 sm:grid-cols-3">{sel("Clavier par défaut", "keyboard", KEYBOARDS)}{sel("Langue", "language", LANGUAGES)}{sel("Visionneuse de console", "console", CONSOLES)}</div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Adresse d'expédition des e-mails" value={f.email_from} maxLength={254} onChange={(e) => set("email_from")(e.target.value)} hint="Vide = défaut de Proxmox (root@nœud)" />
              <Field label="Préfixe des adresses MAC" value={f.mac_prefix} maxLength={8} placeholder="BC:24:11" onChange={(e) => set("mac_prefix")(e.target.value)} hint="Trois octets, premier octet pair" />
              <Field label="Tâches parallèles par nœud (max_workers)" type="number" min={1} max={64} value={f.max_workers} onChange={(e) => set("max_workers")(e.target.value)} hint="1 à 64" />
              <Field label="Proxy HTTP des nœuds" value={f.http_proxy} maxLength={300} placeholder="http://proxy.lan:3128" onChange={(e) => set("http_proxy")(e.target.value)} hint="http:// uniquement, sans identifiants ; adresses locales refusées" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block space-y-1.5 text-sm"><span className="text-muted">Migration : type</span>
                <select className="field" value={f.mtype} onChange={(e) => set("mtype")(e.target.value)}><option value="">Défaut de Proxmox (sécurisé)</option><option value="secure">secure : tunnel SSH chiffré</option><option value="insecure">insecure : non chiffré</option></select></label>
              <Field label="Migration : réseau dédié (CIDR)" value={f.mnet} maxLength={43} placeholder="10.0.0.0/24" onChange={(e) => set("mnet")(e.target.value)} hint="Vide = réseau par défaut" />
            </div>
            {insecureNew && <Notice kind="error">La migration non chiffrée envoie la mémoire des machines <b>en clair</b> sur le réseau. À réserver à un réseau privé de confiance.</Notice>}
            <div className="flex justify-end"><Button disabled={!changed || busy !== null} onClick={() => save("options", changes)}>{busy === "options" ? "…" : insecureNew ? "Appliquer (migration non chiffrée)" : "Appliquer"}</Button></div>
          </div>
        </section>
        <section className="space-y-3"><h2 className="text-lg font-semibold">Notes du datacenter</h2>
          <div className="panel space-y-3 p-5">
            <textarea className="field min-h-[10rem] font-mono text-sm" value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="Notes du datacenter" maxLength={65536} />
            <div className="flex justify-end"><Button disabled={!notesChanged || busy !== null} onClick={() => save("notes", notes.trim() ? { description: notes } : { clear: ["description"] })}>{busy === "notes" ? "…" : "Enregistrer les notes"}</Button></div>
          </div>
        </section>
        {id !== null && <MetricsServers connId={id} />}
        {Object.keys(d.readonly).length > 0 && (
          <section className="space-y-3"><h2 className="text-lg font-semibold">Non modifiable dans Kaji</h2>
            <dl className="panel p-4 text-sm">{Object.entries(d.readonly).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 border-b border-line/60 py-1.5 last:border-0"><dt className="text-muted">{LABELS[k] ?? k}</dt><dd className="max-w-[60%] break-all text-right font-mono text-xs">{v}</dd></div>))}</dl>
            <p className="text-xs text-muted">Ces réglages (HA, fencing, ordonnancement, débits) peuvent couper l'accès ou déplacer des machines : à modifier dans l'interface de Proxmox.</p>
          </section>)}
      </>}
    </div>
  );
}
