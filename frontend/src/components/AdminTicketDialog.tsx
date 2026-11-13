import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { SESSION_MINUTES, type AdminSessionState } from "../lib/types/admin-session";
import { AccountSelect } from "./AccountSelect";
import { Modal } from "./Modal";
import { Notice } from "./ui";

const USER = /^[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}$/;

/** Ouvrir une session administrateur PAR MOT DE PASSE (ticket Proxmox) : la seule façon d'écrire la double authentification, que Proxmox interdit aux jetons d'API.
 *  Le mot de passe part une fois vers Proxmox pour obtenir un ticket ; Kaji ne le garde jamais, ne le journalise pas, ne le renvoie pas. */
export function AdminTicketDialog({ connId, onClose, onOpened }: { connId: number; onClose: () => void; onOpened: (s: AdminSessionState) => void }) {
  const [user, setUser] = useState(""), [password, setPassword] = useState(""), [code, setCode] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const ok = USER.test(user) && password.length > 0 && (code === "" || /^[0-9]{6,8}$/.test(code));

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const s = await api<AdminSessionState>(`/api/connections/${connId}/admin-session/ticket`, { method: "POST", body: { username: user, password, ...(code ? { code } : {}) } });
      setPassword(""); setCode("");                                   // ni le mot de passe ni le code ne restent dans l'état de l'interface
      onOpened(s);
    } catch (e) { setPassword(""); setErr((e as Error).message); setBusy(false); }
  };

  return (
    <Modal title={tr("Ouvrir une session par mot de passe")} subtitle={tr("Connexion à Proxmox avec un compte, pour les écritures que les jetons n'ont pas le droit de faire (double authentification). Session de {SESSION_MINUTES} minutes.", { SESSION_MINUTES })}
      onClose={onClose} onSubmit={submit} submitLabel={tr("Ouvrir la session")} busy={busy} error={err} canSubmit={ok}>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Compte Proxmox")}</span>
        <AccountSelect connId={connId} kind="users" value={user} onChange={setUser} placeholder={tr("root@pam")} /></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Mot de passe du compte")}</span>
        <input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" spellCheck={false} /></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Code de double authentification (si le compte en a une)")}</span>
        <input className="field font-mono" inputMode="numeric" value={code} maxLength={8} onChange={(e) => setCode(e.target.value.trim())} autoComplete="off" placeholder="123456" /></label>
      <Notice kind="ok">{tr("Le mot de passe n'est jamais enregistré par Kaji : il sert une seule fois à obtenir un ticket, gardé en mémoire du serveur seulement. Tu le tapes toi-même ici.")}</Notice>
    </Modal>
  );
}
