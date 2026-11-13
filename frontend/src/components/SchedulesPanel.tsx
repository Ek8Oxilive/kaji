import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest } from "../lib/api";
import { tr } from "../lib/i18n";
import { when } from "./TaskDrawer";
import { Button, Notice } from "./ui";

type Sched = { id: number; node: string; gtype: "qemu" | "lxc"; vmid: number; action: string; days: number[]; time: string; timezone: string; enabled: boolean;
  created_by: string; next_run: string | null; last_run_at: string | null; last_status: string | null; last_detail: string | null };
const ACTION: Record<string, () => string> = { start: () => tr("Démarrer"), shutdown: () => tr("Éteindre proprement"), reboot: () => tr("Redémarrer"), stop: () => tr("Arrêt forcé"), snapshot: () => tr("Créer un snapshot") };
const DAYS = [() => tr("lun"), () => tr("mar"), () => tr("mer"), () => tr("jeu"), () => tr("ven"), () => tr("sam"), () => tr("dim")];
const STATUS: Record<string, { label: () => string; cls: string }> = {
  ok: { label: () => tr("réussie"), cls: "text-ok" }, skipped: { label: () => tr("ignorée"), cls: "text-muted" },
  refused: { label: () => tr("refusée"), cls: "text-warn" }, error: { label: () => tr("en erreur"), cls: "text-danger" },
};
const HHMM = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

/** Actions planifiées (démarrer, éteindre, redémarrer, snapshot à heure fixe). Lecture pour tous ; créer et supprimer : administrateurs (le serveur refuse les autres). */
export function SchedulesPanel({ connId }: { connId: number }) {
  const qc = useQueryClient();
  const key = ["schedules", connId];
  const list = useQuery({ queryKey: key, refetchInterval: 30_000, queryFn: () => api<Sched[]>(`/api/connections/${connId}/schedules`) });
  const guests = useQuery({ queryKey: ["cluster", connId, "guests"], staleTime: 30_000, queryFn: () => api<Guest[]>(`/api/connections/${connId}/guests`) });
  const names = new Map((guests.data ?? []).map((g) => [`${g.type}/${g.vmid}`, g.name ?? ""]));
  const [open, setOpen] = useState(false);
  const [machine, setMachine] = useState(""), [action, setAction] = useState("start"), [days, setDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [time, setTime] = useState("07:30"), [tz, setTz] = useState("Europe/Paris"), [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const [del, setDel] = useState<number | null>(null);
  const picked = (guests.data ?? []).find((g) => `${g.node}|${g.type}|${g.vmid}` === machine);
  const valid = !!picked && days.length > 0 && HHMM.test(time) && tz.length > 0 && (action !== "stop" || ok);

  const call = async (what: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await what(); await qc.invalidateQueries({ queryKey: key }); return true; } catch (e) { setErr((e as Error).message); return false; } finally { setBusy(false); }
  };
  const create = async () => {
    if (!picked) return;
    if (await call(() => api(`/api/connections/${connId}/schedules`, { method: "POST", body: { node: picked.node, gtype: picked.type, vmid: picked.vmid, action, days, time, timezone: tz, confirm: action === "stop" && ok } }))) setOpen(false);
  };
  const toggle = (s: Sched) => call(() => api(`/api/connections/${connId}/schedules/${s.id}`, { method: "PUT", body: { node: s.node, gtype: s.gtype, vmid: s.vmid, action: s.action, days: s.days, time: s.time, timezone: s.timezone, enabled: !s.enabled, confirm: s.action === "stop" } }));

  return (
    <section className="space-y-3" aria-label={tr("Actions planifiées")}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{tr("Actions planifiées")}</h2>
          <p className="text-sm text-muted">{tr("Démarrer, éteindre, redémarrer ou faire un snapshot d'une machine à heure fixe. Un créneau manqué (Kaji arrêté) n'est jamais rattrapé ; les machines protégées sont exclues.")}</p>
        </div>
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => { setOpen(!open); setErr(null); }}>{open ? tr("Fermer") : tr("Planifier une action…")}</Button>
      </div>
      {err && <Notice kind="error">{err}</Notice>}
      {open && (
        <form className="panel space-y-3 p-4 text-sm" onSubmit={(e) => { e.preventDefault(); if (valid && !busy) void create(); }}>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="block text-xs text-muted">{tr("Machine")}<select className="field mt-1" value={machine} onChange={(e) => setMachine(e.target.value)}>
              <option value="">{tr("Choisir…")}</option>
              {(guests.data ?? []).filter((g) => !g.template).map((g) => <option key={`${g.node}|${g.type}|${g.vmid}`} value={`${g.node}|${g.type}|${g.vmid}`}>{g.vmid} · {g.name ?? g.type} · {g.node}</option>)}</select></label>
            <label className="block text-xs text-muted">{tr("Action")}<select className="field mt-1" value={action} onChange={(e) => { setAction(e.target.value); setOk(false); }}>
              {Object.keys(ACTION).map((a) => <option key={a} value={a}>{ACTION[a]()}</option>)}</select></label>
            <label className="block text-xs text-muted">{tr("Heure (HH:MM)")}<input className="field mt-1" value={time} onChange={(e) => setTime(e.target.value.trim())} placeholder="07:30" autoComplete="off" /></label>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {DAYS.map((d, i) => <label key={i} className="flex items-center gap-1.5"><input type="checkbox" checked={days.includes(i)} onChange={(e) => setDays(e.target.checked ? [...days, i].sort() : days.filter((x) => x !== i))} />{d()}</label>)}
            <label className="ml-auto block text-xs text-muted">{tr("Fuseau horaire")}<input className="field mt-1 !w-48" value={tz} onChange={(e) => setTz(e.target.value.trim())} autoComplete="off" /></label>
          </div>
          {action === "stop" && <label className="flex gap-2"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /><span>{tr("J'ai compris : l'arrêt forcé coupe la machine sans arrêt propre, à chaque exécution")}</span></label>}
          <Button type="submit" disabled={busy || !valid}>{tr("Planifier")}</Button>
        </form>)}
      {list.isLoading ? <div className="panel h-16 animate-pulse" /> : list.error ? <Notice kind="error">{(list.error as Error).message}</Notice>
        : (list.data ?? []).length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{tr("Aucune action planifiée.")}</div> : (
          <ul className="panel divide-y divide-line/60">
            {list.data!.map((s) => (
              <li key={s.id} className="space-y-1 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className={s.enabled ? "" : "text-muted"}>
                    <span className="font-medium">{ACTION[s.action]?.() ?? s.action}</span>{" · "}<code>{s.vmid}</code>{names.get(`${s.gtype}/${s.vmid}`) ? ` ${names.get(`${s.gtype}/${s.vmid}`)}` : ""}
                    <span className="text-muted">{" · "}{s.days.map((d) => DAYS[d]()).join(" ")} {tr("à")} {s.time} ({s.timezone}){s.enabled ? "" : ` · ${tr("désactivée")}`}</span>
                  </div>
                  <div className="flex gap-2">
                    <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={busy} onClick={() => toggle(s)}>{s.enabled ? tr("Désactiver") : tr("Activer")}</Button>
                    {del === s.id
                      ? <Button type="button" variant="danger" className="!px-3 !py-1" disabled={busy} onClick={async () => { if (await call(() => api(`/api/connections/${connId}/schedules/${s.id}?confirm=true`, { method: "DELETE" }))) setDel(null); }}>{tr("Confirmer la suppression")}</Button>
                      : <Button type="button" variant="danger" className="!px-3 !py-1" disabled={busy} onClick={() => setDel(s.id)}>{tr("Supprimer…")}</Button>}
                  </div>
                </div>
                <p className="text-xs text-muted">
                  {s.next_run ? <>{tr("Prochaine exécution")} : {when(s.next_run)}</> : null}
                  {s.last_run_at ? <>{s.next_run ? " · " : ""}{tr("Dernière")} : {when(s.last_run_at)} {s.last_status && STATUS[s.last_status] ? <span className={STATUS[s.last_status].cls}>{STATUS[s.last_status].label()}</span> : null}{s.last_detail ? ` (${s.last_detail})` : ""}</> : null}
                  {!s.next_run && !s.last_run_at ? tr("Jamais exécutée.") : null}
                </p>
              </li>))}
          </ul>)}
    </section>
  );
}
