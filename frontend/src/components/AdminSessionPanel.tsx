import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { MAX_HOURS, SESSION_MINUTES, type AdminSessionState } from "../lib/types/admin-session";
import { Modal } from "./Modal";
import { Button, Notice } from "./ui";

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
    <Modal title="Ouvrir une session administrateur" subtitle={`Un token d'administration que tu crées pour l'occasion. Session de ${SESSION_MINUTES} minutes, gardée en mémoire du serveur seulement.`}
      onClose={onClose} onSubmit={submit} submitLabel="Ouvrir la session" busy={busy} error={err} canSubmit={ok}>
      {insecure() && <Notice kind="error">Tu es connecté en <b>http</b> : le token collé ici circule en clair sur ton réseau local. Passe par https (proxy inverse) dès que possible.</Notice>}
      <label className="block space-y-1 text-sm"><span className="text-muted">Compte Proxmox</span>
        <input className="field" value={user} onChange={(e) => setUser(e.target.value.trim())} placeholder="admin@pve" autoComplete="off" /></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">Nom du token</span>
        <input className="field" value={tokenId} onChange={(e) => setTokenId(e.target.value.trim())} placeholder="kaji-admin" autoComplete="off" /></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">Secret du token</span>
        <input className="field font-mono" type="password" value={secret} onChange={(e) => setSecret(e.target.value.trim())} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" autoComplete="off" spellCheck={false} /></label>
      <p className="text-xs text-muted">Jamais enregistré en base ni dans un journal. Supprime le token dans Proxmox quand tu as fini. Il doit être distinct du token de Kaji.</p>
    </Modal>
  );
}

/** Session administrateur : le token permanent de Kaji ne peut pas écrire de droits ; celle-ci, temporaire, le pourra pour les lots d'écriture. */
export function AdminSessionPanel({ connId }: { connId: number }) {
  const qc = useQueryClient();
  const key = ["admin-session", connId];
  const q = useQuery({ queryKey: key, queryFn: () => api<AdminSessionState>(`/api/connections/${connId}/admin-session`), refetchInterval: 30_000 });
  const [open, setOpen] = useState(false);
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
    <section className="panel space-y-3 p-4" aria-label="Session administrateur">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Mode administrateur</h2>
          <p className="text-sm text-muted">
            {active && s && s.active
              ? <>Session ouverte avec <code>{s.user}!{s.token_id}</code> · il reste <b className={left < 120 ? "text-warn" : ""}>{clock(left)}</b></>
              : "Fermé. Le token permanent de Kaji ne peut pas modifier les droits : l'écriture des droits passera par une session temporaire."}
          </p>
        </div>
        <div className="flex gap-2">
          {active ? <>
            <Button variant="ghost" disabled={busy} onClick={() => act("POST", "/renew")} className="!px-3 !py-1.5">Prolonger de {SESSION_MINUTES} min</Button>
            <Button variant="danger" disabled={busy} onClick={() => act("DELETE", "")} className="!px-3 !py-1.5">Fermer</Button>
          </> : <Button onClick={() => setOpen(true)} className="!px-3 !py-1.5">Ouvrir une session</Button>}
        </div>
      </div>
      {active && s && s.active && s.renewals > 0 && <p className="text-xs text-muted">{s.renewals} prolongation(s) ; âge maximal {MAX_HOURS} h.</p>}
      {err && <Notice kind="error">{err}</Notice>}
      {open && <OpenDialog connId={connId} onClose={() => setOpen(false)} onOpened={() => { setOpen(false); qc.invalidateQueries({ queryKey: key }); }} />}
    </section>
  );
}
