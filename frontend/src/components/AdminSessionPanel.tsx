import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { MAX_HOURS, SESSION_MINUTES, type AdminSessionState } from "../lib/types/admin-session";
import { AclWriteDialog } from "./AclWriteDialog";
import { UserWriteDialog } from "./UserWriteDialog";
import { TfaDialog } from "./TfaDialog";
import { Modal } from "./Modal";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const USER = /^[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}$/;
const TOKEN = /^[A-Za-z][A-Za-z0-9._-]{1,63}$/;
const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** Une connexion en clair expose le token collé à tout le réseau local : on le dit, sans l'interdire (réseau privé). */
const insecure = () => typeof location !== "undefined" && location.protocol === "http:" && !["localhost", "127.0.0.1"].includes(location.hostname);

function OpenDialog({ connId, onClose, onOpened }: { connId: number; onClose: () => void; onOpened: (s: AdminSessionState) => void }) {
  const [user, setUser] = useState(""), [tokenId, setTokenId] = useState(""), [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ok = USER.test(user) && TOKEN.test(tokenId) && UUID.test(secret);

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const s = await api<AdminSessionState>(`/api/connections/${connId}/admin-session`, { method: "POST", body: { user, token_id: tokenId, secret } });
      setSecret("");                                   // le secret ne reste pas dans l'état de l'interface
      onOpened(s);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  return (
    <Modal title={tr("Ouvrir une session administrateur")} subtitle={tr("Un token d'administration que tu crées pour l'occasion. Session de {SESSION_MINUTES} minutes, gardée en mémoire du serveur seulement.", { SESSION_MINUTES })}
      onClose={onClose} onSubmit={submit} submitLabel={tr("Ouvrir la session")} busy={busy} error={err} canSubmit={ok}>
      {insecure() && <Notice kind="error">{tr("Tu es connecté en")}{" "}<b>{tr("http")}</b>{" "}{tr(": le token collé ici circule en clair sur ton réseau local. Passe par https (proxy inverse) dès que possible.")}</Notice>}
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Compte Proxmox")}</span>
        <input className="field" value={user} onChange={(e) => setUser(e.target.value.trim())} placeholder={tr("admin@pve")} autoComplete="off" /></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Nom du token")}</span>
        <input className="field" value={tokenId} onChange={(e) => setTokenId(e.target.value.trim())} placeholder={tr("kaji-admin")} autoComplete="off" /></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Secret du token")}</span>
        <input className="field font-mono" type="password" value={secret} onChange={(e) => setSecret(e.target.value.trim())} placeholder={tr("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")} autoComplete="off" spellCheck={false} /></label>
      <p className="text-xs text-muted">{tr("Jamais enregistré en base ni dans un journal. Supprime le token dans Proxmox quand tu as fini. Il doit être distinct du token de Kaji.")}</p>
    </Modal>
  );
}

/** Session administrateur : le token permanent de Kaji ne peut pas écrire de droits ; celle-ci, temporaire, le pourra pour les lots d'écriture. */
export function AdminSessionPanel({ connId }: { connId: number }) {
  const qc = useQueryClient();
  const key = ["admin-session", connId];
  const q = useQuery({ queryKey: key, queryFn: () => api<AdminSessionState>(`/api/connections/${connId}/admin-session`), refetchInterval: 30_000 });
  const [open, setOpen] = useState(false);
  const [acl, setAcl] = useState(false);
  const [usr, setUsr] = useState(false);
  const [tfa, setTfa] = useState(false);
  const [left, setLeft] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const s = q.data;

  useEffect(() => {                                    // compte à rebours local, recalé à chaque réponse du serveur
    if (!s || !s.active) { setLeft(0); return; }
    setLeft(s.seconds_left);
    const t = setInterval(() => setLeft((v) => { if (v <= 1) { qc.invalidateQueries({ queryKey: key }); return 0; } return v - 1; }), 1000);
    return () => clearInterval(t);
  }, [s && s.active ? s.expires_at : null]);          // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (method: "POST" | "DELETE", tail: string) => {
    setBusy(true); setErr(null);
    try { await api(`/api/connections/${connId}/admin-session${tail}`, { method }); await qc.invalidateQueries({ queryKey: key }); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const active = !!s && s.active && left > 0;

  return (
    <section className="panel space-y-3 p-4" aria-label={tr("Session administrateur")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{tr("Mode administrateur")}</h2>
          <p className="text-sm text-muted">
            {active && s && s.active
              ? <>{tr("Session ouverte avec")}{" "}<code>{s.user}!{s.token_id}</code>{" "}{tr("· il reste")}{" "}<b className={left < 120 ? "text-warn" : ""}>{clock(left)}</b></>
              : tr("Fermé. Le token permanent de Kaji ne peut pas modifier les droits : l'écriture des droits passera par une session temporaire.")}
          </p>
        </div>
        <div className="flex gap-2">
          {active ? <>
            <Button disabled={busy} onClick={() => setAcl(true)} className="!px-3 !py-1.5">{tr("Modifier une ACL…")}</Button>
            <Button disabled={busy} onClick={() => setUsr(true)} className="!px-3 !py-1.5">{tr("Utilisateurs et groupes…")}</Button>
            <Button disabled={busy} onClick={() => setTfa(true)} className="!px-3 !py-1.5">{tr("Double authentification…")}</Button>
            <Button variant="ghost" disabled={busy} onClick={() => act("POST", "/renew")} className="!px-3 !py-1.5">{tr("Prolonger de {SESSION_MINUTES} min", { SESSION_MINUTES })}</Button>
            <Button variant="danger" disabled={busy} onClick={() => act("DELETE", "")} className="!px-3 !py-1.5">{tr("Fermer")}</Button>
          </> : <Button onClick={() => setOpen(true)} className="!px-3 !py-1.5">{tr("Ouvrir une session")}</Button>}
        </div>
      </div>
      {active && s && s.active && s.renewals > 0 && <p className="text-xs text-muted">{tr("{renewals} prolongation(s) ; âge maximal {MAX_HOURS} h.", { renewals: s.renewals, MAX_HOURS })}</p>}
      {err && <Notice kind="error">{err}</Notice>}
      {usr && active && <UserWriteDialog connId={connId} onClose={() => setUsr(false)} />}
      {tfa && active && <TfaDialog connId={connId} onClose={() => setTfa(false)} />}
      {acl && active && <AclWriteDialog connId={connId} onClose={() => setAcl(false)} />}
      {open && <OpenDialog connId={connId} onClose={() => setOpen(false)} onOpened={() => { setOpen(false); qc.invalidateQueries({ queryKey: key }); }} />}
    </section>
  );
}
