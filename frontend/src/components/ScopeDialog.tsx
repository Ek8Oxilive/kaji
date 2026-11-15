import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type Connection, type Guest } from "../lib/api";
import { tr } from "../lib/i18n";
import type { ScopeState } from "../lib/types/perimetre";
import { Modal } from "./Modal";
import { Button, Notice } from "./ui";

/** Périmètre d'un compte : les machines (par connexion) qu'il voit et touche, et rien d'autre. Le serveur applique la restriction à chaque requête ; cette fenêtre ne fait que la décrire.
 *  « Ajouter un pool » ajoute d'un coup les machines que le pool contient MAINTENANT (le périmètre garde des machines, pas le pool : un pool modifié ensuite ne le change pas). */
export function ScopeDialog({ user, onClose }: { user: { id: number; username: string }; onClose: () => void }) {
  const qc = useQueryClient();
  const scope = useQuery({ queryKey: ["kaji-user-scope", user.id], queryFn: () => api<ScopeState>(`/api/kaji-users/${user.id}/scope`) });
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/api/connections") });
  const [connId, setConnId] = useState<number | null>(null);
  const [chosen, setChosen] = useState<Record<number, number[]>>({});      // connexion → machines
  const [loaded, setLoaded] = useState(false);
  const [pool, setPool] = useState("");
  const [askClear, setAskClear] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);

  useEffect(() => {
    if (scope.data && !loaded) { setChosen(Object.fromEntries(scope.data.entries.map((e) => [e.conn_id, e.vmids]))); setLoaded(true); }
  }, [scope.data, loaded]);
  useEffect(() => { if (connId === null && conns.data?.length) setConnId(conns.data[0].id); }, [conns.data, connId]);

  const guests = useQuery({ queryKey: ["guests", connId], enabled: connId !== null, queryFn: () => api<Guest[]>(`/api/connections/${connId}/guests`) });
  const here = useMemo(() => new Set(chosen[connId ?? -1] ?? []), [chosen, connId]);
  const known = useMemo(() => new Set((guests.data ?? []).map((g) => g.vmid)), [guests.data]);
  const unknown = [...here].filter((v) => !known.has(v)).sort((a, b) => a - b);          // dans le périmètre mais plus dans le cluster (machine supprimée)
  const pools = useMemo(() => [...new Set((guests.data ?? []).map((g) => g.pool).filter((p): p is string => !!p))].sort(), [guests.data]);
  const total = Object.values(chosen).reduce((n, v) => n + v.length, 0);

  const set = (vmids: number[]) => {
    if (connId === null) return;
    setChosen((c) => { const next = { ...c }; if (vmids.length) next[connId] = [...new Set(vmids)].sort((a, b) => a - b); else delete next[connId]; return next; });
    setOk(null);
  };
  const toggle = (v: number) => set(here.has(v) ? [...here].filter((x) => x !== v) : [...here, v]);
  const addPool = () => set([...here, ...(guests.data ?? []).filter((g) => g.pool === pool).map((g) => g.vmid)]);

  const save = async () => {
    setBusy(true); setErr(null); setOk(null);
    try {
      const entries = Object.entries(chosen).filter(([, v]) => v.length).map(([c, v]) => ({ conn_id: Number(c), vmids: v }));
      await api(`/api/kaji-users/${user.id}/scope`, { method: "PUT", body: { entries } });
      setOk(tr("Périmètre enregistré : il s'applique tout de suite."));
      await Promise.all([qc.invalidateQueries({ queryKey: ["kaji-user-scope", user.id] }), qc.invalidateQueries({ queryKey: ["kaji-users"] })]);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const clear = async () => {
    setBusy(true); setErr(null); setOk(null);
    try {
      await api(`/api/kaji-users/${user.id}/scope?confirm=true&name=${encodeURIComponent(typed)}`, { method: "DELETE" });
      setChosen({}); setAskClear(false); setTyped("");
      setOk(tr("Restriction retirée : le compte revient à la politique de son rôle sur tout le cluster."));
      await Promise.all([qc.invalidateQueries({ queryKey: ["kaji-user-scope", user.id] }), qc.invalidateQueries({ queryKey: ["kaji-users"] })]);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const restricted = scope.data?.restricted === true;
  return (
    <Modal title={tr("Périmètre de {name}", { name: user.username })}
      subtitle={tr("Les machines que ce compte voit et touche, et rien d'autre. Le serveur applique la restriction à chaque requête.")}
      onClose={busy ? () => {} : onClose} onSubmit={save} submitLabel={tr("Enregistrer le périmètre")} busy={busy} error={err} canSubmit={total > 0 && loaded} wide>
      {scope.error && <Notice kind="error">{(scope.error as Error).message}</Notice>}
      <Notice kind={restricted ? "ok" : "error"}>{restricted
        ? tr("Ce compte est restreint à ces machines : il ne voit ni les autres machines, ni le stockage, le réseau, les droits ou les tâches du cluster.")
        : tr("Ce compte n'est PAS restreint : il agit selon son rôle sur tout le cluster. Choisis des machines puis enregistre pour le restreindre.")}</Notice>
      {conns.data && conns.data.length > 1 && (
        <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Connexion")}</span>
          <select className="field" value={connId ?? ""} onChange={(e) => setConnId(Number(e.target.value))}>
            {conns.data.map((c) => <option key={c.id} value={c.id}>{c.name}{chosen[c.id]?.length ? ` (${chosen[c.id].length})` : ""}</option>)}
          </select></label>)}
      {guests.isLoading && <div className="h-16 animate-pulse rounded bg-surface2" />}
      {guests.error && <Notice kind="error">{(guests.error as Error).message}</Notice>}
      {guests.data && (
        <div className="space-y-2">
          {pools.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <select className="field !w-auto" aria-label={tr("Pool à ajouter")} value={pool} onChange={(e) => setPool(e.target.value)}>
                <option value="">{tr("Pool…")}</option>{pools.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
              <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={!pool} onClick={addPool}>{tr("Ajouter les machines du pool")}</Button>
              <span className="text-xs text-muted">{tr("Les machines qu'il contient maintenant : un pool modifié ensuite ne change pas le périmètre.")}</span>
            </div>)}
          <ul className="max-h-72 divide-y divide-line/60 overflow-y-auto rounded-xl border border-line text-sm" aria-label={tr("Machines")}>
            {guests.data.map((g) => (
              <li key={g.vmid}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-surface2">
                  <input type="checkbox" checked={here.has(g.vmid)} onChange={() => toggle(g.vmid)} />
                  <span className="font-mono text-xs text-muted">{g.vmid}</span>
                  <span className="font-medium">{g.name ?? "—"}</span>
                  <span className="ml-auto text-xs text-muted">{g.node}{g.pool ? ` · ${g.pool}` : ""}</span>
                </label>
              </li>))}
            {guests.data.length === 0 && <li className="px-3 py-2 text-muted">{tr("Aucune machine sur cette connexion.")}</li>}
          </ul>
          {unknown.length > 0 && <p className="text-xs text-muted">{tr("Dans le périmètre mais absentes du cluster : {ids}", { ids: unknown.join(", ") })}</p>}
          <p className="text-xs text-muted">{tr("{n} machine(s) au total.", { n: total })}{total === 0 ? ` ${tr("Choisis-en au moins une.")}` : ""}</p>
        </div>)}
      {ok && <Notice kind="ok">{ok}</Notice>}
      {restricted && (
        <div className="space-y-2 border-t border-line pt-3">
          {askClear ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted">{tr("Retape")} <code>{user.username}</code> {tr("pour confirmer")}</span>
              <input className="field !w-48" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} aria-label={tr("Retape le nom pour confirmer")} />
              <Button type="button" variant="danger" disabled={busy || typed !== user.username} onClick={clear}>{tr("Retirer la restriction")}</Button>
              <Button type="button" variant="ghost" onClick={() => { setAskClear(false); setTyped(""); }}>{tr("Annuler")}</Button>
            </div>
          ) : <Button type="button" variant="ghost" onClick={() => setAskClear(true)}>{tr("Retirer la restriction…")}</Button>}
        </div>)}
    </Modal>
  );
}
