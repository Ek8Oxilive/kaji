import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { when } from "./TaskDrawer";
import { Button, Notice } from "./ui";

type Rule = { id: number; name: string; kind: string; threshold: number; minutes: number; enabled: boolean; has_webhook: boolean; created_by: string };
type Ev = { id: number; rule: string; subject: string; status: "pending" | "firing" | "resolved"; since: string | null; fired_at: string | null; resolved_at: string | null; value: number | null; detail: string | null };
const KIND: Record<string, () => string> = {
  cpu: () => tr("CPU d'un nœud"), mem: () => tr("RAM d'un nœud"), storage: () => tr("Remplissage d'un stockage"), node_offline: () => tr("Nœud hors ligne"), task_failed: () => tr("Tâche en échec"),
};
const WITH_THRESHOLD = ["cpu", "mem", "storage"];
const STATE: Record<string, { label: () => string; cls: string }> = {
  firing: { label: () => tr("en alerte"), cls: "text-danger" }, pending: { label: () => tr("seuil dépassé"), cls: "text-warn" }, resolved: { label: () => tr("résolue"), cls: "text-muted" },
};

/** Alertes : règles (seuil CPU / RAM / stockage, nœud hors ligne, tâche en échec), alertes en cours et historique. Lecture pour tous ; règles et test d'envoi : administrateurs. */
export function AlertsPanel({ connId }: { connId: number }) {
  const qc = useQueryClient();
  const base = `/api/connections/${connId}/alerts`;
  const rules = useQuery({ queryKey: ["alert-rules", connId], queryFn: () => api<Rule[]>(`${base}/rules`) });
  const events = useQuery({ queryKey: ["alert-events", connId], refetchInterval: 30_000, queryFn: () => api<Ev[]>(`${base}/events?limit=30`) });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(""), [kind, setKind] = useState("cpu"), [thr, setThr] = useState("80"), [minutes, setMinutes] = useState("5"), [hook, setHook] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [msg, setMsg] = useState<string | null>(null), [del, setDel] = useState<number | null>(null);
  const hasThr = WITH_THRESHOLD.includes(kind);
  const valid = name.trim().length >= 3 && (!hasThr || (/^[0-9]{1,3}$/.test(thr) && Number(thr) >= 1 && Number(thr) <= 100)) && /^[0-9]{1,3}$/.test(minutes) && Number(minutes) >= 1 && Number(minutes) <= 120;

  const call = async (what: () => Promise<unknown>, done?: string) => {
    setBusy(true); setErr(null); setMsg(null);
    try { await what(); if (done) setMsg(done); await qc.invalidateQueries({ queryKey: ["alert-rules", connId] }); await qc.invalidateQueries({ queryKey: ["alert-events", connId] }); return true; }
    catch (e) { setErr((e as Error).message); return false; } finally { setBusy(false); }
  };
  const create = async () => {
    if (await call(() => api(`${base}/rules`, { method: "POST", body: { name: name.trim(), kind, threshold: hasThr ? Number(thr) : 0, minutes: Number(minutes), ...(hook ? { webhook_url: hook } : {}) } }), tr("Règle créée"))) {
      setName(""); setHook(""); setOpen(false);                  // l'adresse du webhook ne reste pas dans l'état de l'interface
    }
  };
  const put = (r: Rule, enabled: boolean) => call(() => api(`${base}/rules/${r.id}`, { method: "PUT", body: { name: r.name, kind: r.kind, threshold: r.threshold, minutes: r.minutes, enabled } }));
  const test = async (r: Rule) => {
    setBusy(true); setErr(null); setMsg(null);
    try { const res = await api<{ sent: boolean }>(`${base}/rules/${r.id}/test?confirm=true`, { method: "POST" }); if (res.sent) setMsg(tr("Message de test envoyé")); else setErr(tr("L'envoi du message de test a échoué")); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const active = (events.data ?? []).filter((e) => e.status === "firing");

  return (
    <section className="space-y-3" aria-label={tr("Alertes")}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{tr("Alertes")}{active.length > 0 && <span className="ml-2 rounded-md bg-danger/15 px-2 py-0.5 text-sm font-normal text-danger">{active.length}</span>}</h2>
          <p className="text-sm text-muted">{tr("Kaji surveille le cluster toutes les minutes : une alerte se déclenche quand un seuil reste dépassé assez longtemps, et se résout toute seule. Notification facultative par webhook (adresse jamais affichée).")}</p>
        </div>
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => { setOpen(!open); setErr(null); }}>{open ? tr("Fermer") : tr("Nouvelle règle…")}</Button>
      </div>
      {err && <Notice kind="error">{err}</Notice>}
      {msg && <Notice kind="ok">{msg}</Notice>}
      {active.length > 0 && (
        <ul className="panel divide-y divide-line/60 border-danger/40">
          {active.map((e) => <li key={e.id} className="p-3 text-sm"><span className="font-medium text-danger">{e.rule}</span> · {e.subject}{e.value !== null && e.value > 0 ? ` · ${e.value} %` : ""} <span className="text-xs text-muted">{e.fired_at ? when(e.fired_at) : ""}</span></li>)}
        </ul>)}
      {open && (
        <form className="panel space-y-3 p-4 text-sm" onSubmit={(e) => { e.preventDefault(); if (valid && !busy) void create(); }}>
          <div className="grid gap-2 sm:grid-cols-4">
            <label className="block text-xs text-muted sm:col-span-2">{tr("Nom")}<input className="field mt-1" value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("CPU haut sur les nœuds")} autoComplete="off" /></label>
            <label className="block text-xs text-muted">{tr("Type")}<select className="field mt-1" value={kind} onChange={(e) => setKind(e.target.value)}>{Object.keys(KIND).map((k) => <option key={k} value={k}>{KIND[k]()}</option>)}</select></label>
            {hasThr && <label className="block text-xs text-muted">{tr("Seuil (%)")}<input className="field mt-1" inputMode="numeric" value={thr} onChange={(e) => setThr(e.target.value.trim())} autoComplete="off" /></label>}
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            {kind !== "task_failed" && <label className="block text-xs text-muted">{tr("Pendant (minutes)")}<input className="field mt-1" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value.trim())} autoComplete="off" /></label>}
            <label className="block text-xs text-muted sm:col-span-3">{tr("Adresse du webhook (facultatif, écriture seule)")}<input className="field mt-1" type="password" value={hook} onChange={(e) => setHook(e.target.value.trim())} placeholder="https://…" autoComplete="off" spellCheck={false} /></label>
          </div>
          <Button type="submit" disabled={busy || !valid}>{tr("Créer la règle")}</Button>
        </form>)}
      {rules.isLoading ? <div className="panel h-16 animate-pulse" /> : rules.error ? <Notice kind="error">{(rules.error as Error).message}</Notice>
        : (rules.data ?? []).length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{tr("Aucune règle d'alerte.")}</div> : (
          <ul className="panel divide-y divide-line/60">
            {rules.data!.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
                <div className={r.enabled ? "" : "text-muted"}>
                  <span className="font-medium">{r.name}</span>
                  <span className="text-muted">{" · "}{KIND[r.kind]?.() ?? r.kind}{WITH_THRESHOLD.includes(r.kind) ? ` ≥ ${r.threshold} %` : ""}{r.kind !== "task_failed" ? ` ${tr("pendant")} ${r.minutes} min` : ""}{r.has_webhook ? ` · ${tr("webhook")}` : ""}{r.enabled ? "" : ` · ${tr("désactivée")}`}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {r.has_webhook && <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={busy} onClick={() => test(r)}>{tr("Tester le webhook")}</Button>}
                  <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={busy} onClick={() => put(r, !r.enabled)}>{r.enabled ? tr("Désactiver") : tr("Activer")}</Button>
                  {del === r.id
                    ? <Button type="button" variant="danger" className="!px-3 !py-1" disabled={busy} onClick={async () => { if (await call(() => api(`${base}/rules/${r.id}?confirm=true`, { method: "DELETE" }))) setDel(null); }}>{tr("Confirmer la suppression")}</Button>
                    : <Button type="button" variant="danger" className="!px-3 !py-1" disabled={busy} onClick={() => setDel(r.id)}>{tr("Supprimer…")}</Button>}
                </div>
              </li>))}
          </ul>)}
      {(events.data ?? []).filter((e) => e.status !== "pending").length > 0 && (
        <details className="panel p-3 text-sm">
          <summary className="cursor-pointer text-muted">{tr("Historique des alertes")}</summary>
          <ul className="mt-2 space-y-1">
            {(events.data ?? []).filter((e) => e.status !== "pending").map((e) => (
              <li key={e.id}><span className={STATE[e.status].cls}>{STATE[e.status].label()}</span> · {e.rule} · {e.subject}{e.value !== null && e.value > 0 ? ` · ${e.value} %` : ""}
                <span className="text-xs text-muted"> · {when(e.fired_at ?? e.since)}{e.resolved_at ? ` → ${when(e.resolved_at)}` : ""}{e.detail ? ` · ${e.detail}` : ""}</span></li>))}
          </ul>
        </details>)}
    </section>
  );
}
