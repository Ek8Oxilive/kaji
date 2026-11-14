import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Connection } from "../lib/api";
import { tr } from "../lib/i18n";
import type { ServiceTokenInfo } from "../lib/types/jeton-service";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

const TOKEN = /^([A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32})!([A-Za-z][A-Za-z0-9._-]{0,63})$/;

/** Jeton de SERVICE d'une connexion (administrateurs) : celui que le planificateur et les alertes utilisent quand personne n'est connecté. Kaji REFUSE un jeton qui détient un droit
 *  en trop (jamais Administrator) : il le vérifie auprès de Proxmox avec le jeton lui-même. Le secret n'est gardé que dans l'état du formulaire, vidé après l'envoi. */
export function ServiceTokenDialog({ conn, onClose }: { conn: Connection; onClose: () => void }) {
  const qc = useQueryClient();
  const key = ["service-token", conn.id];
  const q = useQuery({ queryKey: key, queryFn: () => api<ServiceTokenInfo>(`/api/connections/${conn.id}/service-token`) });
  const [account, setAccount] = useState(""), [secret, setSecret] = useState(""), [expires, setExpires] = useState(""), [privsep, setPrivsep] = useState(true);
  const [askRemove, setAskRemove] = useState(false);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);
  const d = q.data, t = d?.token;
  const parsed = TOKEN.exec(account.trim());
  const valid = !!d?.enabled && !!parsed && secret.length >= 8 && !/\s/.test(secret) && privsep;

  const save = async () => {
    if (!parsed) return;
    setBusy(true); setErr(null); setOk(null);
    try {
      const r = await api<ServiceTokenInfo["token"]>(`/api/connections/${conn.id}/service-token`, { method: "PUT", body: { pve_user: parsed[1], token_id: parsed[2], secret, privsep, ...(expires ? { expires_at: expires } : {}) } });
      setOk(r.lacks && r.lacks.length > 0 ? tr("Jeton enregistré, mais il lui manque : {rights}. Le planificateur et les alertes échoueront sans ces droits.", { rights: r.lacks.join(", ") }) : tr("Jeton de service enregistré : ses droits sont limités à ce qui est nécessaire."));
      setAccount(""); setExpires("");
      await qc.invalidateQueries({ queryKey: key });
    } catch (e) { setErr((e as Error).message); }
    finally { setSecret(""); setBusy(false); }
  };
  const remove = async () => {
    setBusy(true); setErr(null); setOk(null);
    try { await api(`/api/connections/${conn.id}/service-token`, { method: "DELETE" }); setAskRemove(false); setOk(tr("Jeton de service retiré de Kaji.")); await qc.invalidateQueries({ queryKey: key }); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <Modal title={tr("Jeton de service")} subtitle={tr("{name} : utilisé par le planificateur d'actions et les alertes, quand personne n'est connecté.", { name: conn.name })}
      onClose={busy ? () => {} : onClose} onSubmit={save} submitLabel={tr("Enregistrer le jeton de service")} busy={busy} error={err} canSubmit={valid} wide>
      {q.isLoading && <div className="h-16 animate-pulse rounded bg-surface2" />}
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}
      {d && !d.enabled && <Notice kind="error">{d.problem}</Notice>}
      {d?.enabled && (d.required
        ? <Notice kind="ok">{tr("Sans jeton de service, le planificateur et les alertes ne font rien pour cette connexion.")}</Notice>
        : <Notice kind="ok">{tr("Sans jeton de service, le planificateur et les alertes utilisent le jeton partagé de la connexion.")}</Notice>)}
      {ok && <Notice kind="ok">{ok}</Notice>}
      {d && t && (
        <div className="space-y-2 rounded-xl border border-line p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{t.pve_user ? <code>{t.pve_user}!{t.token_id}</code> : tr("Aucun jeton de service")}</span>
            <span className="rounded-full border border-line px-2 py-0.5 text-xs">{t.state === "none" ? tr("Aucun") : t.state === "ok" ? tr("Actif") : t.state === "expiring" ? tr("Expire bientôt") : t.state === "expired" ? tr("Expiré") : tr("Refusé par Proxmox")}</span>
          </div>
          {t.pve_user && <p className="text-xs text-muted">{tr("expire le {date}", { date: t.expires_at ? new Date(t.expires_at).toLocaleDateString() : "?" })}{t.days_left !== null && t.state !== "expired" ? ` (${tr("{n} jour(s)", { n: t.days_left })})` : ""} · {t.verified ? tr("contrôlé par Proxmox") : tr("déclaré, non contrôlé par Proxmox")} · {tr("enregistré par {name}", { name: t.created_by ?? "?" })}</p>}
          {t.state === "refused" && <p className="text-xs text-danger">{tr("Proxmox refuse ce jeton (révoqué, expiré ou supprimé chez lui) : enregistre-en un nouveau.")}</p>}
          {t.state !== "none" && (askRemove
            ? <div className="flex gap-2"><Button type="button" variant="danger" className="!px-3 !py-1" disabled={busy} onClick={remove}>{tr("Confirmer le retrait")}</Button><Button type="button" variant="ghost" className="!px-3 !py-1" onClick={() => setAskRemove(false)}>{tr("Annuler")}</Button></div>
            : <Button type="button" variant="ghost" className="!px-3 !py-1" disabled={busy} onClick={() => setAskRemove(true)}>{tr("Retirer")}</Button>)}
        </div>)}
      {d?.enabled && (
        <div className="space-y-3">
          <Notice kind="ok">{tr("Droits acceptés (et eux seuls) : {rights}. Un jeton qui en détient d'autres est refusé : jamais Administrator.", { rights: d.allowed_privileges.join(", ") })}</Notice>
          <Field label={tr("Compte et jeton Proxmox")} value={account} onChange={(e) => setAccount(e.target.value)} placeholder="kaji-service@pve!planificateur" autoComplete="off"
            hint={tr("sous la forme compte@realm!identifiant-du-jeton")} />
          <Field label={tr("Secret du jeton")} type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" hint={tr("affiché une seule fois par Proxmox à la création ; jamais renvoyé par Kaji")} />
          <Field label={tr("Expiration du jeton (facultatif si Proxmox la fournit)")} type="date" value={expires} onChange={(e) => setExpires(e.target.value)} hint={tr("au plus {n} jours", { n: d.max_days })} />
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1 size-4 accent-[var(--accent)]" checked={privsep} onChange={(e) => setPrivsep(e.target.checked)} />
            <span>{tr("Ce jeton a les privilèges séparés (« Privilege Separation » coché) : sans cela il aurait tous les droits de son compte.")}</span></label>
          {parsed === null && account.length > 0 && <p className="text-xs text-danger">{tr("Format attendu : compte@realm!identifiant-du-jeton")}</p>}
        </div>)}
    </Modal>
  );
}
