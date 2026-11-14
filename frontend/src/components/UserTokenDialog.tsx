import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import type { UserTokenBody, UserTokenConnection, UserTokenState, UserTokens } from "../lib/types/jeton-utilisateur";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

const STATE: Record<UserTokenState, { label: () => string; cls: string }> = {
  none: { label: () => tr("Aucun jeton personnel"), cls: "text-muted border-line" },
  ok: { label: () => tr("Actif"), cls: "text-ok border-ok/40" },
  expiring: { label: () => tr("Expire bientôt"), cls: "text-warn border-warn/40" },
  expired: { label: () => tr("Expiré"), cls: "text-danger border-danger/40" },
  refused: { label: () => tr("Refusé par Proxmox"), cls: "text-danger border-danger/40" },
};
const TOKEN = /^([A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32})!([A-Za-z][A-Za-z0-9._-]{0,63})$/;

/** « Mon jeton Proxmox » : chaque utilisateur enregistre SON jeton par connexion (privilèges séparés, expiration). Le secret n'est gardé que dans l'état du formulaire, vidé après l'envoi ;
 *  le serveur ne le renvoie jamais et le contrôle auprès de Proxmox avant de l'enregistrer. */
export function UserTokenDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["user-tokens"], queryFn: () => api<UserTokens>("/api/me/proxmox-tokens") });
  const [editing, setEditing] = useState<number | null>(null);
  const [account, setAccount] = useState(""), [secret, setSecret] = useState(""), [expires, setExpires] = useState(""), [privsep, setPrivsep] = useState(true);
  const [askRemove, setAskRemove] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);

  const parsed = TOKEN.exec(account.trim());
  const valid = editing !== null && !!parsed && secret.length >= 8 && !/\s/.test(secret) && privsep;
  const reset = () => { setEditing(null); setAccount(""); setSecret(""); setExpires(""); setPrivsep(true); };
  const open = (c: UserTokenConnection) => { reset(); setEditing(c.conn_id); setAskRemove(null); setErr(null); setOk(null); if (c.pve_user && c.token_id) setAccount(`${c.pve_user}!${c.token_id}`); };

  const save = async () => {
    if (editing === null || !parsed) return;
    setBusy(true); setErr(null); setOk(null);
    const body: UserTokenBody = { pve_user: parsed[1], token_id: parsed[2], secret, privsep, ...(expires ? { expires_at: expires } : {}) };
    try {
      await api(`/api/me/proxmox-tokens/${editing}`, { method: "PUT", body });
      setOk(tr("Jeton enregistré : Proxmox l'a accepté."));
      reset();
      await qc.invalidateQueries({ queryKey: ["user-tokens"] });
    } catch (e) { setErr((e as Error).message); }
    finally { setSecret(""); setBusy(false); }
  };
  const remove = async (id: number) => {
    setBusy(true); setErr(null); setOk(null);
    try { await api(`/api/me/proxmox-tokens/${id}`, { method: "DELETE" }); setAskRemove(null); setOk(tr("Jeton retiré de Kaji (il reste valable chez Proxmox : supprime-le là-bas si besoin).")); await qc.invalidateQueries({ queryKey: ["user-tokens"] }); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  const d = q.data;

  return (
    <Modal title={tr("Mon jeton Proxmox")} subtitle={tr("Kaji agit chez Proxmox avec TON jeton : Proxmox applique tes droits et son journal te nomme.")}
      onClose={busy ? () => {} : onClose} onSubmit={save} submitLabel={tr("Enregistrer le jeton")} busy={busy} error={err} canSubmit={valid} wide>
      {q.isLoading && <div className="h-16 animate-pulse rounded bg-surface2" />}
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}
      {d && !d.enabled && <Notice kind="error">{d.problem}</Notice>}
      {d?.enabled && d.required && <Notice kind="ok">{tr("Sans jeton personnel, tu n'as aucun accès à Proxmox par Kaji : enregistre le tien pour chaque connexion.")}</Notice>}
      {d?.enabled && !d.required && <Notice kind="ok">{tr("Sans jeton personnel, Kaji utilise le jeton partagé de la connexion : les actions apparaissent alors sous le même nom chez Proxmox.")}</Notice>}
      {ok && <Notice kind="ok">{ok}</Notice>}
      {d?.enabled && (
        <ul className="divide-y divide-line/60 rounded-xl border border-line">
          {d.connections.map((c) => (
            <li key={c.conn_id} className="space-y-2 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{c.name}</span>
                <span className={`rounded-full border px-2 py-0.5 text-xs ${STATE[c.state].cls}`}>{STATE[c.state].label()}</span>
              </div>
              {c.pve_user && (
                <p className="text-xs text-muted">
                  <code>{c.pve_user}!{c.token_id}</code> · {tr("expire le {date}", { date: c.expires_at ? new Date(c.expires_at).toLocaleDateString() : "?" })}
                  {c.days_left !== null && c.state !== "expired" ? ` (${tr("{n} jour(s)", { n: c.days_left })})` : ""} ·{" "}
                  {c.verified ? tr("contrôlé par Proxmox") : tr("déclaré, non contrôlé par Proxmox")}
                </p>)}
              {c.state === "refused" && <p className="text-xs text-danger">{tr("Proxmox refuse ce jeton (révoqué, expiré ou supprimé chez lui) : enregistre-en un nouveau.")}</p>}
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={busy} onClick={() => open(c)}>{c.state === "none" ? tr("Enregistrer mon jeton…") : tr("Remplacer…")}</Button>
                {c.state !== "none" && (askRemove === c.conn_id
                  ? <><Button type="button" variant="danger" className="!px-3 !py-1" disabled={busy} onClick={() => remove(c.conn_id)}>{tr("Confirmer le retrait")}</Button>
                      <Button type="button" variant="ghost" className="!px-3 !py-1" onClick={() => setAskRemove(null)}>{tr("Annuler")}</Button></>
                  : <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={busy} onClick={() => { setAskRemove(c.conn_id); reset(); }}>{tr("Retirer")}</Button>)}
              </div>
              {editing === c.conn_id && (
                <div className="space-y-3 rounded-lg border border-line p-3">
                  <Field label={tr("Compte et jeton Proxmox")} value={account} onChange={(e) => setAccount(e.target.value)} placeholder="alice@pve!kaji" autoComplete="off" autoFocus
                    hint={tr("sous la forme compte@realm!identifiant-du-jeton")} />
                  <Field label={tr("Secret du jeton")} type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off"
                    hint={tr("affiché une seule fois par Proxmox à la création ; jamais renvoyé par Kaji")} />
                  <Field label={tr("Expiration du jeton (facultatif si Proxmox la fournit)")} type="date" value={expires} onChange={(e) => setExpires(e.target.value)}
                    hint={tr("au plus {n} jours", { n: d.max_days })} />
                  <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1 size-4 accent-[var(--accent)]" checked={privsep} onChange={(e) => setPrivsep(e.target.checked)} />
                    <span>{tr("Ce jeton a les privilèges séparés (« Privilege Separation » coché) : sans cela il aurait tous les droits de mon compte.")}</span></label>
                  {parsed === null && account.length > 0 && <p className="text-xs text-danger">{tr("Format attendu : compte@realm!identifiant-du-jeton")}</p>}
                  <p className="text-xs text-muted">{tr("Créer le jeton dans Proxmox : Datacenter → Permissions → API Tokens, avec « Privilege Separation » et une date d'expiration, puis lui donner les rôles voulus.")}</p>
                </div>)}
            </li>))}
        </ul>)}
    </Modal>
  );
}
