import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./Modal";
import { Notice } from "./ui";

type Act = "create-user" | "toggle-user" | "delete-user" | "member" | "create-group" | "delete-group";
const LABEL: Record<Act, string> = {
  "create-user": "Créer un utilisateur", "toggle-user": "Activer ou désactiver un utilisateur", "delete-user": "Supprimer un utilisateur",
  member: "Ajouter ou retirer d'un groupe", "create-group": "Créer un groupe", "delete-group": "Supprimer un groupe",
};
const USER = /^[A-Za-z0-9._-]{1,64}@pve$/;
const GROUP = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
type Impact = { protected: boolean; groups: string[]; acl_entries: number; tokens: string[] };

/** Écrire des utilisateurs (realm pve), des groupes et des appartenances. Une écriture à la fois ; le serveur revérifie tout et refuse les identités protégées. */
export function UserWriteDialog({ connId, onClose }: { connId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [act, setAct] = useState<Act>("create-user");
  const [id, setId] = useState(""), [group, setGroup] = useState(""), [comment, setComment] = useState(""), [password, setPassword] = useState("");
  const [enable, setEnable] = useState(true), [add, setAdd] = useState(true), [typed, setTyped] = useState("");
  const [impact, setImpact] = useState<Impact | null>(null);
  const [busy, setBusy] = useState(false), [done, setDone] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  const base = `/api/connections/${connId}/access`;
  const isGroup = act === "create-group" || act === "delete-group";
  const idOk = isGroup ? GROUP.test(id) : USER.test(id);
  const valid = idOk && (act !== "member" || GROUP.test(group)) && (act !== "create-user" || password === "" || password.length >= 12);

  useEffect(() => { setImpact(null); setTyped(""); setErr(null); }, [act, id]);
  const reset = (a: Act) => { setAct(a); setId(""); setGroup(""); setPassword(""); setComment(""); };

  const look = async () => {
    setErr(null);
    try { setImpact(await api<Impact>(`${base}/users/${encodeURIComponent(id)}/impact`)); } catch (e) { setErr((e as Error).message); }
  };
  const run = async () => {
    setBusy(true); setErr(null);
    const ok = { confirm: true, type_name: typed };
    try {
      if (act === "create-user") await api(`${base}/users`, { method: "POST", body: { userid: id, enable, ...(comment ? { comment } : {}), ...(password ? { password } : {}), ...ok } });
      else if (act === "toggle-user") await api(`${base}/users/${encodeURIComponent(id)}`, { method: "PUT", body: { enable, ...ok } });
      else if (act === "delete-user") await api(`${base}/users/${encodeURIComponent(id)}?confirm=true&name=${encodeURIComponent(typed)}`, { method: "DELETE" });
      else if (act === "member") await api(`${base}/users/${encodeURIComponent(id)}/groups`, { method: "PUT", body: { group, action: add ? "add" : "remove", ...ok } });
      else if (act === "create-group") await api(`${base}/groups`, { method: "POST", body: { groupid: id, ...(comment ? { comment } : {}), ...ok } });
      else await api(`${base}/groups/${encodeURIComponent(id)}?confirm=true&name=${encodeURIComponent(typed)}`, { method: "DELETE" });
      setPassword("");
      await qc.invalidateQueries({ queryKey: ["access", connId] });
      setDone(LABEL[act]); setBusy(false);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  if (done) return (
    <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit>
      <Notice kind="ok">{done} : <code>{id}</code>. Relu chez Proxmox, visible dans les listes ci-dessous.</Notice>
    </Modal>
  );
  const destructive = act === "delete-user" || act === "delete-group";
  return (
    <Modal title="Utilisateurs et groupes" subtitle="Une écriture à la fois, avec l'identité de la session administrateur. Realm pve seulement." onClose={busy ? () => {} : onClose}
      onSubmit={run} submitLabel="Appliquer" danger={destructive} busy={busy} error={err} canSubmit={valid && typed === id}>
      <label className="block space-y-1 text-sm"><span className="text-muted">Action</span>
        <select className="field" value={act} onChange={(e) => reset(e.target.value as Act)}>{(Object.keys(LABEL) as Act[]).map((a) => <option key={a} value={a}>{LABEL[a]}</option>)}</select></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{isGroup ? "Identifiant du groupe" : "Utilisateur"}</span>
        <input className="field" value={id} onChange={(e) => setId(e.target.value.trim())} placeholder={isGroup ? "staff" : "bob@pve"} autoComplete="off" /></label>
      {act === "member" && <>
        <label className="block space-y-1 text-sm"><span className="text-muted">Groupe</span>
          <input className="field" value={group} onChange={(e) => setGroup(e.target.value.trim())} placeholder="staff" autoComplete="off" /></label>
        <label className="flex gap-4 text-sm"><label className="flex gap-1.5"><input type="radio" checked={add} onChange={() => setAdd(true)} />Ajouter</label><label className="flex gap-1.5"><input type="radio" checked={!add} onChange={() => setAdd(false)} />Retirer</label></label>
        <p className="text-xs text-muted">Ajouter à un groupe donne ses droits à l'utilisateur : un groupe qui permet de modifier les droits est refusé par le serveur.</p>
      </>}
      {(act === "create-user" || act === "create-group") && <label className="block space-y-1 text-sm"><span className="text-muted">Commentaire (facultatif)</span>
        <input className="field" value={comment} maxLength={100} onChange={(e) => setComment(e.target.value)} autoComplete="off" /></label>}
      {act === "create-user" && <label className="block space-y-1 text-sm"><span className="text-muted">Mot de passe (facultatif, 12 caractères au moins)</span>
        <input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        <span className="block text-xs text-muted">Sans mot de passe, l'utilisateur ne se connecte que par token. Il n'a aucun droit tant que tu ne lui en donnes pas.</span></label>}
      {(act === "create-user" || act === "toggle-user") && <label className="flex gap-2 text-sm"><input type="checkbox" checked={enable} onChange={(e) => setEnable(e.target.checked)} /><span>Compte activé</span></label>}
      {act === "delete-user" && <>
        <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!idOk} onClick={look}>Voir l'impact</button>
        {impact && (impact.protected ? <Notice kind="error">Identité protégée (Kaji, session administrateur ou root) : la suppression sera refusée.</Notice>
          : <p className="text-sm text-muted">Groupes : {impact.groups.join(", ") || "aucun"} · entrées d'ACL : {impact.acl_entries} · tokens supprimés avec lui : {impact.tokens.join(", ") || "aucun"}</p>)}
      </>}
      {destructive && <Notice kind="error">{act === "delete-user" ? "Suppression définitive de l'utilisateur et de ses tokens." : "Un groupe n'est supprimé que s'il est vide et sans ACL."}</Notice>}
      {valid && <label className="block text-xs text-muted">Retape <code>{id}</code> pour confirmer
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>}
    </Modal>
  );
}
