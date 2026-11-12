import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type Guest } from "../lib/api";
import { confirmReasons } from "../lib/confirmRisk";
import type { Pool, PoolUpdateBody, PoolUpdateResult } from "../lib/types/pools";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

import { tr } from "../lib/i18n";
type Mode = { kind: "new" } | { kind: "manage"; pool: Pool } | { kind: "delete"; pool: Pool };
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;

/** Datacenter → Permissions → Pools. Le serveur relit tout, protège les machines de Kaji et ne supprime qu'un pool vide et sans droit (ACL). */
export function PoolsSection({ connId }: { connId: number }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const q = useQuery({ queryKey: ["pools-overview", connId], queryFn: () => api<Pool[]>(`/api/connections/${connId}/pools/overview`) });
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{tr("Pools de ressources")}</h2><Button variant="ghost" onClick={() => setMode({ kind: "new" })}>{tr("Créer un pool")}</Button></div>
      {q.error ? <Notice kind="error">{(q.error as Error).message}</Notice> : (q.data ?? []).length === 0 ? <p className="text-sm text-muted">{tr("Aucun pool : un pool regroupe des machines et des stockages pour leur donner des droits ensemble.")}</p> : (
        <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[32rem] text-sm">
          <thead><tr className="border-b border-line text-left text-xs text-muted">{[tr("Pool"), tr("Commentaire"), tr("Machines"), tr("Stockages"), ""].map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead>
          <tbody>{(q.data ?? []).map((p) => (
            <tr key={p.poolid} className="border-b border-line/60 last:border-0">
              <td className="px-4 py-2 font-mono">{p.poolid}</td><td className="px-4 py-2 text-muted">{p.comment ?? ""}</td>
              <td className="px-4 py-2 text-muted">{p.vms.length}</td><td className="px-4 py-2 text-muted">{p.storages.length}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMode({ kind: "manage", pool: p })}>{tr("Gérer")}</button><button className="text-danger underline" onClick={() => setMode({ kind: "delete", pool: p })}>{tr("Supprimer")}</button></td>
            </tr>))}</tbody></table></div>)}
      {mode?.kind === "new" && <CreateDialog connId={connId} onClose={() => setMode(null)} />}
      {mode?.kind === "manage" && <ManageDialog connId={connId} pool={mode.pool} all={q.data ?? []} onClose={() => setMode(null)} />}
      {mode?.kind === "delete" && <DeleteDialog connId={connId} pool={mode.pool} onClose={() => setMode(null)} />}
    </section>
  );
}

function useRefresh(connId: number) {
  const qc = useQueryClient();
  return () => { qc.invalidateQueries({ queryKey: ["pools-overview", connId] }); qc.invalidateQueries({ queryKey: ["pools", connId] }); };
}

function CreateDialog({ connId, onClose }: { connId: number; onClose: () => void }) {
  const refresh = useRefresh(connId);
  const [id, setId] = useState(""), [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try { await api(`/api/connections/${connId}/pools`, { method: "POST", body: { poolid: id, ...(comment.trim() ? { comment: comment.trim() } : {}) } }); refresh(); onClose(); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  return (
    <Modal title={tr("Créer un pool")} onClose={onClose} onSubmit={submit} submitLabel={tr("Créer")} busy={busy} error={err} canSubmit={ID.test(id) && comment.length <= 200}>
      <Field label={tr("Identifiant")} value={id} onChange={(e) => setId(e.target.value)} autoComplete="off" aria-invalid={id !== "" && !ID.test(id)} hint={tr("Lettres, chiffres, _ et -, 40 caractères au plus")} />
      <Field label={tr("Commentaire (facultatif)")} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={200} />
    </Modal>
  );
}

function ManageDialog({ connId, pool, all, onClose }: { connId: number; pool: Pool; all: Pool[]; onClose: () => void }) {
  const refresh = useRefresh(connId);
  const guests = useQuery({ queryKey: ["cluster", connId, "guests"], queryFn: () => api<Guest[]>(`/api/connections/${connId}/guests`) });
  const storages = useQuery({ queryKey: ["storage-names", connId], queryFn: () => api<{ storage: string }[]>(`/api/connections/${connId}/storages`) });
  const [comment, setComment] = useState(pool.comment ?? "");
  const [addVms, setAddVms] = useState<Set<number>>(new Set()), [addSto, setAddSto] = useState<Set<string>>(new Set());
  const [remVms, setRemVms] = useState<Set<number>>(new Set()), [remSto, setRemSto] = useState<Set<string>>(new Set());
  const [allowMove, setAllowMove] = useState(false), [risk, setRisk] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const holder = useMemo(() => new Map(all.filter((p) => p.poolid !== pool.poolid).flatMap((p) => p.vms.map((v) => [v, p.poolid] as const))), [all, pool.poolid]);
  const candidates = (guests.data ?? []).filter((g) => !pool.vms.includes(g.vmid)).sort((a, b) => a.vmid - b.vmid);
  const stoNames = [...new Set((storages.data ?? []).map((s) => s.storage))].filter((s) => !pool.storages.includes(s)).sort();
  const toggle = <T,>(set: Set<T>, v: T, on: boolean) => { const n = new Set(set); if (on) n.add(v); else n.delete(v); return n; };
  const moving = [...addVms].some((v) => holder.has(v));

  const body = (extra: Partial<PoolUpdateBody> = {}): PoolUpdateBody => ({
    ...(comment !== (pool.comment ?? "") ? { comment } : {}),
    ...(addVms.size ? { add_vms: [...addVms] } : {}), ...(remVms.size ? { remove_vms: [...remVms] } : {}),
    ...(addSto.size ? { add_storage: [...addSto] } : {}), ...(remSto.size ? { remove_storage: [...remSto] } : {}),
    ...(moving && allowMove ? { allow_move: true } : {}), ...extra,
  });
  const changed = Object.keys(body()).length > 0;
  useEffect(() => { setRisk(null); setErr(null); }, [comment, addVms, addSto, remVms, remSto, allowMove]);

  const apply = async (confirm: boolean) => {
    setBusy(true); setErr(null);
    try {
      await api<PoolUpdateResult>(`/api/connections/${connId}/pools/${encodeURIComponent(pool.poolid)}`, { method: "PUT", body: body(confirm ? { confirm: true } : {}) });
      refresh(); onClose();
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setRisk(reasons); else setErr((e as Error).message);
      setBusy(false);
    }
  };
  const box = "size-4 accent-[var(--accent)]";
  return (
    <Modal title={tr("Pool « {poolid} »", { poolid: pool.poolid })} subtitle={tr("Membres et commentaire")} onClose={onClose} onSubmit={() => apply(!!risk)} submitLabel={risk ? tr("Confirmer et appliquer") : tr("Appliquer")} danger={!!risk}
      busy={busy || guests.isLoading} error={err} canSubmit={changed && comment.length <= 200} wide>
      <Field label={tr("Commentaire")} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={200} />
      <fieldset className="space-y-1.5"><legend className="text-sm text-muted">{tr("Membres actuels (cocher pour retirer)")}</legend>
        {pool.members.length === 0 && <p className="text-sm text-muted">{tr("Pool vide.")}</p>}
        {pool.members.map((m) => m.type === "storage"
          ? <label key={`s-${m.storage}`} className="flex items-center gap-2 text-sm"><input type="checkbox" className={box} checked={remSto.has(m.storage)} onChange={(e) => setRemSto(toggle(remSto, m.storage, e.target.checked))} />{tr("Stockage")}{" "}<span className="font-mono">{m.storage}</span></label>
          : <label key={`v-${m.vmid}`} className="flex items-center gap-2 text-sm"><input type="checkbox" className={box} checked={remVms.has(m.vmid)} onChange={(e) => setRemVms(toggle(remVms, m.vmid, e.target.checked))} />{m.type === "qemu" ? "VM" : "LXC"} #{m.vmid} <span className="text-muted">{m.name ?? ""}</span></label>)}
      </fieldset>
      <fieldset className="max-h-40 space-y-1.5 overflow-y-auto"><legend className="text-sm text-muted">{tr("Ajouter des machines")}</legend>
        {candidates.map((g) => <label key={g.vmid} className="flex items-center gap-2 text-sm"><input type="checkbox" className={box} checked={addVms.has(g.vmid)} onChange={(e) => setAddVms(toggle(addVms, g.vmid, e.target.checked))} />{g.type === "qemu" ? "VM" : "LXC"} #{g.vmid} <span className="text-muted">{g.name ?? ""}</span>{holder.has(g.vmid) && <span className="text-xs text-warn">{tr("déjà dans « {p} »", { p: holder.get(g.vmid) })}</span>}</label>)}
      </fieldset>
      {stoNames.length > 0 && <fieldset className="space-y-1.5"><legend className="text-sm text-muted">{tr("Ajouter des stockages")}</legend>
        {stoNames.map((s) => <label key={s} className="flex items-center gap-2 text-sm"><input type="checkbox" className={box} checked={addSto.has(s)} onChange={(e) => setAddSto(toggle(addSto, s, e.target.checked))} /><span className="font-mono">{s}</span></label>)}</fieldset>}
      {moving && <label className="flex items-center gap-2 text-sm"><input type="checkbox" className={box} checked={allowMove} onChange={(e) => setAllowMove(e.target.checked)} />{tr("Déplacer les machines qui sont déjà dans un autre pool (elles en sortent)")}</label>}
      {risk && <div className="space-y-2 rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn" role="alert"><p className="font-medium">{tr("Confirmation requise")}</p><ul className="list-disc space-y-1 pl-5">{risk.map((r) => <li key={r}>{r}</li>)}</ul></div>}
    </Modal>
  );
}

function DeleteDialog({ connId, pool, onClose }: { connId: number; pool: Pool; onClose: () => void }) {
  const refresh = useRefresh(connId);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try { await api(`/api/connections/${connId}/pools/${encodeURIComponent(pool.poolid)}?confirm=true&name=${encodeURIComponent(typed)}`, { method: "DELETE" }); refresh(); onClose(); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  return (
    <Modal title={tr("Supprimer le pool « {poolid} » ?", { poolid: pool.poolid })} onClose={onClose} onSubmit={submit} submitLabel={tr("Supprimer")} danger busy={busy} error={err} canSubmit={typed === pool.poolid}>
      <Notice kind="error">{tr("Un pool ne se supprime que s'il est vide et sans droit (ACL) posé dessus : Kaji refuse sinon, pour ne pas faire disparaître des accès.")}</Notice>
      {pool.members.length > 0 && <p className="text-sm text-muted">{tr("Ce pool contient encore {length} membre(s) : retire-les d'abord.", { length: pool.members.length })}</p>}
      <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{pool.poolid}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg" /></label>
    </Modal>
  );
}
