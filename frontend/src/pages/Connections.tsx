import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ServiceTokenDialog } from "../components/ServiceTokenDialog";
import { TlsPinDialog } from "../components/TlsPinDialog";
import { Button, Field, Notice } from "../components/ui";
import { api, type Connection, type ProbeResult } from "../lib/api";

import { tr } from "../lib/i18n";
const EMPTY = { name: "", host: "", port: 8006, user: "", token_id: "", token_secret: "", verify_ssl: false };
type Form = typeof EMPTY;

function ProbeBadge({ r }: { r: ProbeResult }) {
  return r.ok ? <Notice kind="ok">{tr("Connexion réussie : Proxmox VE {version}", { version: r.version })}</Notice> : <Notice kind="error">{r.error ?? tr("Échec")}</Notice>;
}

export function Connections() {
  const [items, setItems] = useState<Connection[] | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [formProbe, setFormProbe] = useState<ProbeResult | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [probes, setProbes] = useState<Record<number, ProbeResult>>({});
  const [confirmDel, setConfirmDel] = useState<number | null>(null);
  const [pinFor, setPinFor] = useState<Connection | null>(null);
  const [svcFor, setSvcFor] = useState<Connection | null>(null);
  const who = useQuery({ queryKey: ["me"], staleTime: 60_000, queryFn: () => api<{ username: string; role: string }>("/api/auth/me") });

  const load = useCallback(() => api<Connection[]>("/api/connections").then(setItems).catch((e) => setFormError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => { setForm((f) => ({ ...f, [k]: v })); setFormProbe(null); };

  async function test() {
    setBusy(true); setFormError(null);
    try { setFormProbe(await api<ProbeResult>("/api/connections/test", { method: "POST", body: form })); }
    catch (e) { setFormError((e as Error).message); } finally { setBusy(false); }
  }
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true); setFormError(null);
    try { await api("/api/connections", { method: "POST", body: form }); setForm(EMPTY); setFormProbe(null); await load(); }
    catch (err) { setFormError((err as Error).message); } finally { setBusy(false); }
  }
  async function probe(id: number) {
    try { const r = await api<ProbeResult>(`/api/connections/${id}/test`, { method: "POST" }); setProbes((p) => ({ ...p, [id]: r })); }
    catch (e) { setProbes((p) => ({ ...p, [id]: { ok: false, error: (e as Error).message } })); }
  }
  async function remove(id: number) {
    await api(`/api/connections/${id}`, { method: "DELETE" }).catch((e) => setFormError(e.message));
    setConfirmDel(null); await load();
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{tr("Connexions")}</h1>
        <p className="text-muted">{tr("Les clusters Proxmox pilotés par Kaji. Les tokens sont chiffrés et ne sont jamais ré-affichés.")}</p>
      </header>

      <section className="grid gap-4 md:grid-cols-2">
        {items === null && <div className="panel h-28 animate-pulse" />}
        {items?.length === 0 && <div className="panel p-6 text-muted md:col-span-2">{tr("Aucune connexion pour le moment. Ajoute ton premier cluster ci-dessous.")}</div>}
        {items?.map((c) => (
          <article key={c.id} className="panel space-y-3 p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate font-medium">{c.name}</h2>
                <p className="truncate text-sm text-muted">{c.host}:{c.port} · {c.user}!{c.token_id}</p>
              </div>
              {c.tls_pinned ? <span className="shrink-0 rounded-full border border-ok/40 bg-ok/10 px-2 py-0.5 text-xs text-ok">{tr("Certificat épinglé")}</span>
                : !c.verify_ssl && <span className="shrink-0 rounded-full border border-warn/40 bg-warn/10 px-2 py-0.5 text-xs text-warn">{tr("SSL non vérifié")}</span>}
            </div>
            {probes[c.id] && <ProbeBadge r={probes[c.id]} />}
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => probe(c.id)}>{tr("Tester")}</Button>
              <Button variant="ghost" onClick={() => setPinFor(c)}>{c.tls_pinned ? tr("Certificat…") : tr("Épingler le certificat…")}</Button>
              {who.data?.role === "admin" && <Button variant="ghost" onClick={() => setSvcFor(c)}>{tr("Jeton de service…")}</Button>}
              {confirmDel === c.id
                ? <><Button variant="danger" onClick={() => remove(c.id)}>{tr("Confirmer la suppression")}</Button><Button variant="ghost" onClick={() => setConfirmDel(null)}>{tr("Annuler")}</Button></>
                : <Button variant="danger" onClick={() => setConfirmDel(c.id)}>{tr("Supprimer")}</Button>}
            </div>
          </article>
        ))}
      </section>

      <form onSubmit={save} className="panel space-y-5 p-6">
        <h2 className="text-lg font-semibold">{tr("Ajouter un cluster")}</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={tr("Nom")} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder={tr("homelab")} required />
          <Field label={tr("Hôte")} value={form.host} onChange={(e) => set("host", e.target.value)} placeholder={tr("100.x.y.z ou pve.local")} hint={tr("IP ou nom d'hôte, sans https://")} required />
          <Field label={tr("Port")} type="number" value={form.port} onChange={(e) => set("port", Number(e.target.value))} min={1} max={65535} required />
          <Field label={tr("Utilisateur")} value={form.user} onChange={(e) => set("user", e.target.value)} placeholder={tr("kaji@pve")} required />
          <Field label={tr("ID du token")} value={form.token_id} onChange={(e) => set("token_id", e.target.value)} placeholder={tr("kaji")} required />
          <Field label={tr("Secret du token")} type="password" value={form.token_secret} onChange={(e) => set("token_secret", e.target.value)} autoComplete="off" required />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.verify_ssl} onChange={(e) => set("verify_ssl", e.target.checked)} className="size-4 accent-[var(--accent)]" />{tr("Vérifier le certificat SSL")}{" "}<span className="text-muted">{tr("(à décocher pour un certificat auto-signé)")}</span>
        </label>
        {formProbe && <ProbeBadge r={formProbe} />}
        {formError && <Notice kind="error">{formError}</Notice>}
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="ghost" onClick={test} disabled={busy || !form.host || !form.user || !form.token_id || !form.token_secret}>{tr("Tester la connexion")}</Button>
          <Button type="submit" disabled={busy}>{tr("Enregistrer")}</Button>
        </div>
      </form>
      {pinFor && <TlsPinDialog connId={pinFor.id} name={pinFor.name} onClose={() => { setPinFor(null); load(); }} />}
      {svcFor && <ServiceTokenDialog conn={svcFor} onClose={() => setSvcFor(null)} />}
    </div>
  );
}
