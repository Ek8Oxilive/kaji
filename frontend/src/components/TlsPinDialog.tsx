import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./Modal";
import { Notice } from "./ui";

import { tr } from "../lib/i18n";
type Tls = { reachable: boolean; pinned: boolean; pinned_fingerprint: string | null; matches?: boolean | null; fingerprint?: string; subject?: string | null; issuer?: string | null; self_signed?: boolean; not_before?: string; not_after?: string };
const day = (iso?: string) => (iso ? iso.slice(0, 10) : "–");

/**
 * Épingler le certificat d'un serveur Proxmox : on montre ce que le serveur présente, l'utilisateur COMPARE l'empreinte à celle de son nœud et confirme ; ensuite Kaji n'accepte que ce certificat.
 * Le serveur relit le certificat au moment d'épingler : si ce n'est plus celui qu'on a vu, il refuse (`docs/securite.md`).
 */
export function TlsPinDialog({ connId, name, onClose }: { connId: number; name: string; onClose: () => void }) {
  const [tls, setTls] = useState<Tls | null>(null), [ack, setAck] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [confirmUnpin, setConfirmUnpin] = useState(false);
  const base = `/api/connections/${connId}/tls`;
  const load = () => api<Tls>(base).then((t) => { setTls(t); setAck(false); }).catch((e) => setError((e as Error).message));
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const changed = !!tls?.pinned && tls.matches === false;
  const same = !!tls?.pinned && tls.matches === true;
  async function pin() {
    if (!tls?.fingerprint) return;
    setBusy(true); setError(null);
    try { setTls(await api<Tls>(base, { method: "PUT", body: { fingerprint: tls.fingerprint, confirm: true } })); setAck(false); }
    catch (e) { setError((e as Error).message); await load(); } finally { setBusy(false); }
  }
  async function unpin() {
    setBusy(true); setError(null);
    try { await api(`${base}?confirm=true`, { method: "DELETE" }); setConfirmUnpin(false); await load(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <Modal title={tr("Certificat de {name}", { name })} subtitle={tr("Kaji n'acceptera que le certificat épinglé : un faux serveur sur le réseau ne pourra plus lire le jeton.")} onClose={busy ? () => {} : onClose}
      onSubmit={pin} submitLabel={changed ? tr("Épingler le nouveau certificat") : tr("Épingler ce certificat")} busy={busy} error={error} canSubmit={!!tls?.reachable && !!tls.fingerprint && ack && !same} danger={changed} wide>
      {!tls && !error && <p className="text-sm text-muted">{tr("Lecture du certificat…")}</p>}
      {tls && !tls.reachable && <Notice kind="error">{tr("Proxmox est injoignable : impossible de lire son certificat.")}</Notice>}
      {same && <Notice kind="ok">{tr("Le certificat est épinglé et le serveur présente bien celui-là.")}</Notice>}
      {changed && <Notice kind="error"><b>{tr("Le serveur présente un AUTRE certificat que celui épinglé.")}</b>{" "}{tr("Renouvellement légitime, ou quelqu'un se fait passer pour lui : vérifie l'empreinte sur ton nœud avant d'épingler le nouveau.")}</Notice>}
      {tls?.reachable && tls.fingerprint && <div className="space-y-2 rounded-xl border border-line bg-surface2 p-3 text-sm">
        <div><span className="text-muted">{tr("Empreinte SHA-256 présentée")}</span><code className="mt-1 block break-all font-mono text-xs">{tls.fingerprint}</code></div>
        <div className="grid gap-x-4 sm:grid-cols-2"><span><span className="text-muted">{tr("Sujet :")}</span> {tls.subject ?? "–"}</span><span><span className="text-muted">{tr("Émetteur :")}</span> {tls.self_signed ? tr("lui-même (auto-signé)") : tls.issuer ?? "–"}</span>
          <span><span className="text-muted">{tr("Valide du")}</span> {day(tls.not_before)} {tr("au")} {day(tls.not_after)}</span></div>
        {tls.pinned && <div><span className="text-muted">{tr("Empreinte épinglée")}</span><code className="mt-1 block break-all font-mono text-xs">{tls.pinned_fingerprint}</code></div>}
      </div>}
      {tls?.reachable && !same && <>
        <p className="text-sm text-muted">{tr("Compare cette empreinte à celle de ton nœud : page Cluster de Kaji (colonne « Empreinte du certificat »), ou sur le nœud :")}</p>
        <code className="block select-all overflow-x-auto rounded-lg bg-[var(--code-bg)] px-3 py-2 font-mono text-xs">{"openssl x509 -fingerprint -sha256 -noout -in /etc/pve/local/pve-ssl.pem"}</code>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>{tr("J'ai comparé l'empreinte avec celle de mon nœud : elle est identique.")}</span></label>
      </>}
      {tls?.pinned && (confirmUnpin
        ? <Notice kind="error">{tr("Sans épingle, le certificat de Proxmox n'est plus vérifié comme avant.")}{" "}<button type="button" className="underline" onClick={unpin} disabled={busy}>{tr("Retirer l'épingle")}</button>{" · "}<button type="button" className="underline" onClick={() => setConfirmUnpin(false)}>{tr("Annuler")}</button></Notice>
        : <button type="button" className="text-sm underline" onClick={() => setConfirmUnpin(true)}>{tr("Retirer l'épingle…")}</button>)}
    </Modal>
  );
}
