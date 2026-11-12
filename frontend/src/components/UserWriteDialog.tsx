import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./Modal";
import { SecretOnceDialog } from "./SecretOnceDialog";
import { Notice } from "./ui";

import { tr } from "../lib/i18n";
type Act = "create-user" | "toggle-user" | "delete-user" | "member" | "create-group" | "delete-group" | "create-token" | "revoke-token";
const LABEL: Record<Act, string> = {
  get "create-user"() { return tr("Créer un utilisateur"); }, get "toggle-user"() { return tr("Activer ou désactiver un utilisateur"); }, get "delete-user"() { return tr("Supprimer un utilisateur"); },
  get member() { return tr("Ajouter ou retirer d'un groupe"); }, get "create-group"() { return tr("Créer un groupe"); }, get "delete-group"() { return tr("Supprimer un groupe"); },
  get "create-token"() { return tr("Créer un token d'API"); }, get "revoke-token"() { return tr("Révoquer un token d'API"); },
};
const TOKEN = /^[A-Za-z][A-Za-z0-9._-]{1,63}$/;
const USER = /^[A-Za-z0-9._-]{1,64}@pve$/;
const GROUP = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
type Impact = { protected: boolean; groups: string[]; acl_entries: number; tokens: string[] };
type TokenRow = { tokenid: string; privsep: boolean; expire: number | null; comment: string | null };

/** Écrire des utilisateurs (realm pve), des groupes et des appartenances. Une écriture à la fois ; le serveur revérifie tout et refuse les identités protégées. */
export function UserWriteDialog({ connId, onClose }: { connId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [act, setAct] = useState<Act>("create-user");
  const [id, setId] = useState(""), [group, setGroup] = useState(""), [comment, setComment] = useState(""), [password, setPassword] = useState("");
  const [enable, setEnable] = useState(true), [add, setAdd] = useState(true), [typed, setTyped] = useState("");
  const [impact, setImpact] = useState<Impact | null>(null);
  const [tokens, setTokens] = useState<TokenRow[] | null>(null), [days, setDays] = useState(""), [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [done, setDone] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  const base = `/api/connections/${connId}/access`;
  const isGroup = act === "create-group" || act === "delete-group";
  const idOk = isGroup ? GROUP.test(id) : USER.test(id);
  const isToken = act === "create-token" || act === "revoke-token";
  const full = `${id}!${group}`;                                   // pour un token, « group » porte le nom du token
  const need = isToken ? full : id;
  const valid = idOk && (act !== "member" || GROUP.test(group)) && (!isToken || TOKEN.test(group)) && (act !== "create-user" || password === "" || password.length >= 12)
    && (act !== "create-token" || days === "" || (/^[0-9]{1,4}$/.test(days) && Number(days) >= 1));

  useEffect(() => { setImpact(null); setTokens(null); setTyped(""); setErr(null); }, [act, id, group]);
  const reset = (a: Act) => { setAct(a); setId(""); setGroup(""); setPassword(""); setComment(""); setDays(""); };

  const look = async () => {
    setErr(null);
    try { setImpact(await api<Impact>(`${base}/users/${encodeURIComponent(id)}/impact`)); } catch (e) { setErr((e as Error).message); }
  };
  const listTokens = async () => {
    setErr(null);
    try { setTokens(await api<TokenRow[]>(`${base}/users/${encodeURIComponent(id)}/tokens`)); } catch (e) { setErr((e as Error).message); }
  };
  const run = async () => {
    setBusy(true); setErr(null);
    const ok = { confirm: true, type_name: typed };
    try {
      if (act === "create-token") {
        const r = await api<{ secret: string }>(`${base}/users/${encodeURIComponent(id)}/tokens`, { method: "POST", body: { userid: id, tokenid: group, privsep: true,
          ...(comment ? { comment } : {}), ...(days ? { expire: Math.floor(Date.now() / 1000) + Number(days) * 86400 } : {}), ...ok } });
        setSecret(r.secret); await qc.invalidateQueries({ queryKey: ["access", connId] }); setBusy(false); return;
      }
      if (act === "revoke-token") await api(`${base}/users/${encodeURIComponent(id)}/tokens/${encodeURIComponent(group)}?confirm=true&name=${encodeURIComponent(typed)}`, { method: "DELETE" });
      else
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

  if (secret) return <SecretOnceDialog title={tr("Token créé")} subject={full} secret={secret} onDone={() => { setSecret(null); setDone(LABEL[act]); }} />;
  if (done) return (
    <Modal title={tr("Fait")} onClose={onClose} onSubmit={onClose} submitLabel={tr("Fermer")} canSubmit>
      <Notice kind="ok">{done} : <code>{id}</code>{tr(". Relu chez Proxmox, visible dans les listes ci-dessous.")}</Notice>
    </Modal>
  );
  const destructive = act === "delete-user" || act === "delete-group" || act === "revoke-token";
  return (
    <Modal title={tr("Utilisateurs et groupes")} subtitle={tr("Une écriture à la fois, avec l'identité de la session administrateur. Realm pve seulement.")} onClose={busy ? () => {} : onClose}
      onSubmit={run} submitLabel={tr("Appliquer")} danger={destructive} busy={busy} error={err} canSubmit={valid && typed === need}>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Action")}</span>
        <select className="field" value={act} onChange={(e) => reset(e.target.value as Act)}>{(Object.keys(LABEL) as Act[]).map((a) => <option key={a} value={a}>{LABEL[a]}</option>)}</select></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{isGroup ? tr("Identifiant du groupe") : tr("Utilisateur")}</span>
        <input className="field" value={id} onChange={(e) => setId(e.target.value.trim())} placeholder={isGroup ? tr("staff") : tr("bob@pve")} autoComplete="off" /></label>
      {isToken && <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Nom du token")}</span>
        <input className="field" value={group} onChange={(e) => setGroup(e.target.value.trim())} placeholder={tr("ci")} autoComplete="off" /></label>}
      {act === "revoke-token" && <>
        <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!idOk} onClick={listTokens}>{tr("Voir les tokens de cet utilisateur")}</button>
        {tokens && <p className="text-sm text-muted">{tokens.length === 0 ? tr("Aucun token.") : tokens.map((t) => `${t.tokenid}${t.privsep ? "" : tr(" (sans séparation de privilèges)")}`).join(", ")}</p>}
      </>}
      {act === "create-token" && <>
        <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Expire dans (jours, facultatif)")}</span>
          <input className="field" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.trim())} placeholder="90" autoComplete="off" /></label>
        <p className="text-xs text-muted">{tr("Token à privilèges séparés : il n'a aucun droit tant qu'une ACL ne lui en donne pas. Son secret ne s'affiche qu'une fois.")}</p>
      </>}
      {act === "member" && <>
        <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Groupe")}</span>
          <input className="field" value={group} onChange={(e) => setGroup(e.target.value.trim())} placeholder={tr("staff")} autoComplete="off" /></label>
        <label className="flex gap-4 text-sm"><label className="flex gap-1.5"><input type="radio" checked={add} onChange={() => setAdd(true)} />{tr("Ajouter")}</label><label className="flex gap-1.5"><input type="radio" checked={!add} onChange={() => setAdd(false)} />{tr("Retirer")}</label></label>
        <p className="text-xs text-muted">{tr("Ajouter à un groupe donne ses droits à l'utilisateur : un groupe qui permet de modifier les droits est refusé par le serveur.")}</p>
      </>}
      {(act === "create-user" || act === "create-group" || act === "create-token") && <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Commentaire (facultatif)")}</span>
        <input className="field" value={comment} maxLength={100} onChange={(e) => setComment(e.target.value)} autoComplete="off" /></label>}
      {act === "create-user" && <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Mot de passe (facultatif, 12 caractères au moins)")}</span>
        <input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        <span className="block text-xs text-muted">{tr("Sans mot de passe, l'utilisateur ne se connecte que par token. Il n'a aucun droit tant que tu ne lui en donnes pas.")}</span></label>}
      {(act === "create-user" || act === "toggle-user") && <label className="flex gap-2 text-sm"><input type="checkbox" checked={enable} onChange={(e) => setEnable(e.target.checked)} /><span>{tr("Compte activé")}</span></label>}
      {act === "delete-user" && <>
        <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!idOk} onClick={look}>{tr("Voir l'impact")}</button>
        {impact && (impact.protected ? <Notice kind="error">{tr("Identité protégée (Kaji, session administrateur ou root) : la suppression sera refusée.")}</Notice>
          : <p className="text-sm text-muted">{tr("Groupes : {p} · entrées d'ACL : {acl_entries} · tokens supprimés avec lui : {p2}", { p: impact.groups.join(", ") || tr("aucun"), acl_entries: impact.acl_entries, p2: impact.tokens.join(", ") || tr("aucun") })}</p>)}
      </>}
      {destructive && <Notice kind="error">{act === "delete-user" ? tr("Suppression définitive de l'utilisateur et de ses tokens.") : tr("Un groupe n'est supprimé que s'il est vide et sans ACL.")}</Notice>}
      {valid && <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{need}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>}
    </Modal>
  );
}
