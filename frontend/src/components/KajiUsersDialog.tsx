import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { Modal } from "./Modal";
import { Button, Notice } from "./ui";

type Role = "admin" | "operator" | "viewer";
type KUser = { id: number; username: string; role: Role; created_at: string | null };
const ROLE_LABEL: Record<Role, () => string> = { admin: () => tr("Administrateur"), operator: () => tr("Opérateur"), viewer: () => tr("Lecture seule") };
const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$/;

/** Utilisateurs de Kaji et leurs rôles (administrateurs seulement ; le serveur revérifie tout). Aucun mot de passe n'est conservé hors du formulaire. */
export function KajiUsersDialog({ me, onClose }: { me: string; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["kaji-users"], queryFn: () => api<KUser[]>("/api/kaji-users") });
  const [name, setName] = useState(""), [pw, setPw] = useState(""), [role, setRole] = useState<Role>("viewer");
  const [reset, setReset] = useState<{ id: number; pw: string } | null>(null), [del, setDel] = useState<{ id: number; typed: string } | null>(null);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);

  const act = async (what: () => Promise<unknown>, done: string) => {
    setBusy(true); setErr(null); setOk(null);
    try { await what(); setOk(done); await qc.invalidateQueries({ queryKey: ["kaji-users"] }); return true; }
    catch (e) { setErr((e as Error).message); return false; }
    finally { setBusy(false); }
  };
  const create = async () => {
    if (await act(() => api("/api/kaji-users", { method: "POST", body: { username: name, password: pw, role } }), tr("Utilisateur créé : {name}", { name }))) { setName(""); setPw(""); }
  };
  const valid = NAME.test(name) && pw.length >= 12;

  return (
    <Modal title={tr("Utilisateurs de Kaji")} subtitle={tr("Qui peut se connecter à Kaji et ce qu'il a le droit de faire. Le serveur applique le rôle à chaque requête.")}
      onClose={busy ? () => {} : onClose} onSubmit={create} submitLabel={tr("Créer l'utilisateur")} busy={busy} error={err} canSubmit={valid} wide>
      <Notice kind="ok">{tr("Administrateur : tout. Opérateur : lire, démarrer / arrêter / redémarrer une machine, créer un snapshot. Lecture seule : lire seulement.")}</Notice>
      {q.isLoading ? <div className="h-16 animate-pulse rounded bg-surface2" /> : q.error ? <Notice kind="error">{(q.error as Error).message}</Notice> : (
        <ul className="divide-y divide-line/60 rounded-xl border border-line">
          {(q.data ?? []).map((u) => (
            <li key={u.id} className="space-y-2 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{u.username}{u.username === me && <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[0.7rem] font-normal text-muted">{tr("toi")}</span>}</span>
                <div className="flex flex-wrap items-center gap-2">
                  <select className="field !w-auto" aria-label={tr("Rôle de {name}", { name: u.username })} value={u.role} disabled={busy || u.username === me}
                    onChange={(e) => act(() => api(`/api/kaji-users/${u.id}`, { method: "PUT", body: { role: e.target.value } }), tr("Rôle de {name} changé", { name: u.username }))}>
                    {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]()}</option>)}
                  </select>
                  <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={busy} onClick={() => { setReset({ id: u.id, pw: "" }); setDel(null); }}>{tr("Mot de passe…")}</Button>
                  <Button type="button" variant="danger" className="!px-3 !py-1" disabled={busy || u.username === me} onClick={() => { setDel({ id: u.id, typed: "" }); setReset(null); }}>{tr("Supprimer…")}</Button>
                </div>
              </div>
              {reset?.id === u.id && (
                <div className="flex flex-wrap items-center gap-2">
                  <input className="field !w-64" type="password" autoComplete="new-password" placeholder={tr("Nouveau mot de passe (12 caractères au moins)")} value={reset.pw} onChange={(e) => setReset({ id: u.id, pw: e.target.value })} />
                  <Button type="button" disabled={busy || reset.pw.length < 12} onClick={async () => { if (await act(() => api(`/api/kaji-users/${u.id}`, { method: "PUT", body: { password: reset.pw } }), tr("Mot de passe de {name} réinitialisé, ses sessions sont fermées", { name: u.username }))) setReset(null); }}>{tr("Réinitialiser")}</Button>
                </div>)}
              {del?.id === u.id && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted">{tr("Retape")} <code>{u.username}</code> {tr("pour confirmer")}</span>
                  <input className="field !w-48" autoComplete="off" value={del.typed} onChange={(e) => setDel({ id: u.id, typed: e.target.value })} aria-label={tr("Retape le nom pour confirmer")} />
                  <Button type="button" variant="danger" disabled={busy || del.typed !== u.username} onClick={async () => { if (await act(() => api(`/api/kaji-users/${u.id}?confirm=true&name=${encodeURIComponent(del.typed)}`, { method: "DELETE" }), tr("Utilisateur supprimé : {name}", { name: u.username }))) setDel(null); }}>{tr("Supprimer")}</Button>
                </div>)}
            </li>))}
        </ul>)}
      {ok && <Notice kind="ok">{ok}</Notice>}
      <div className="space-y-2 border-t border-line pt-3">
        <h3 className="text-sm font-semibold">{tr("Nouvel utilisateur")}</h3>
        <div className="grid gap-2 sm:grid-cols-3">
          <label className="block text-xs text-muted">{tr("Nom d'utilisateur")}<input className="field mt-1" value={name} onChange={(e) => setName(e.target.value.trim())} autoComplete="off" /></label>
          <label className="block text-xs text-muted">{tr("Mot de passe (12 caractères au moins)")}<input className="field mt-1" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></label>
          <label className="block text-xs text-muted">{tr("Rôle")}<select className="field mt-1" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]()}</option>)}</select></label>
        </div>
      </div>
    </Modal>
  );
}
