import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { FENCING_PHRASE, type DatacenterOptions, type DatacenterPreview } from "../lib/types/datacenter";
import { Button, Field, Notice } from "./ui";

const init = (d: DatacenterOptions) => ({ id: d.webauthn.id ?? "", origin: d.webauthn.origin ?? "", rp: d.webauthn.rp ?? "", sub: d.webauthn.allow_subdomains ?? true });

/** Datacenter → Options → WebAuthn (lot #381). « Appliquer » demande d'abord l'aperçu ; changer ou retirer une valeur déjà définie casse les credentials existants : le serveur exige alors la phrase. */
export function WebauthnSettings({ connId, d }: { connId: number; d: DatacenterOptions }) {
  const qc = useQueryClient();
  const [f, setF] = useState(init(d));
  useEffect(() => setF(init(d)), [d]);
  const [pending, setPending] = useState<{ body: Record<string, unknown>; preview: DatacenterPreview } | null>(null);
  const [confirm, setConfirm] = useState(false), [ack, setAck] = useState(false), [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);
  const url = `/api/connections/${connId}/datacenter/options`;
  const locked = "webauthn" in d.readonly;
  const isSet = d.webauthn.id !== null || d.webauthn.origin !== null || d.webauthn.rp !== null;

  /** Seulement ce qui a changé et n'est pas vide ; un champ vidé n'est pas une suppression (voir « Retirer WebAuthn »). */
  const diff = () => {
    const w: Record<string, unknown> = {};
    for (const k of ["id", "origin", "rp"] as const) if (f[k].trim() !== "" && f[k].trim() !== (d.webauthn[k] ?? "")) w[k] = f[k].trim();
    if (f.sub !== (d.webauthn.allow_subdomains ?? true)) w.allow_subdomains = f.sub;
    return Object.keys(w).length ? { webauthn: w } : {};
  };
  const body = diff(), changed = Object.keys(body).length > 0;

  const send = async (b: Record<string, unknown>, extra: Record<string, unknown>) => {
    await api(url, { method: "PUT", body: { ...b, digest: d.digest, ...extra } });
    await qc.invalidateQueries({ queryKey: ["datacenter", connId] });
    setPending(null);
    setOk(tr("Réglages WebAuthn enregistrés, relus chez Proxmox."));
  };
  const apply = async (b: Record<string, unknown>) => {
    setBusy(true); setErr(null); setOk(null); setPending(null);
    try {
      const preview = await api<DatacenterPreview>(url, { method: "PUT", body: { ...b, digest: d.digest, dry_run: true } });
      setPending({ body: b, preview }); setConfirm(false); setAck(false); setPhrase("");
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const confirmApply = async () => {
    if (!pending) return;
    setBusy(true); setErr(null);
    try { await send(pending.body, { confirm: true, ...(pending.preview.locks.webauthn_break ? { acknowledge_cut_access: true, type_name: phrase } : {}) }); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const set = (k: "id" | "origin" | "rp") => (v: string) => { setF((c) => ({ ...c, [k]: v })); setPending(null); };
  const brk = !!pending?.preview.locks.webauthn_break;
  const canConfirm = confirm && (!brk || (ack && phrase === FENCING_PHRASE));

  return (
    <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("WebAuthn")}</h2>
      <div className="panel space-y-4 p-5">
        {err && <Notice kind="error">{err}</Notice>}
        {ok && <Notice kind="ok">{ok}</Notice>}
        {locked && <Notice kind="error">{tr("Ce réglage contient des valeurs que Kaji ne sait pas lire ou ne gère pas : il se modifie dans l'interface de Proxmox.")}</Notice>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={tr("Identifiant de la partie de confiance (id)")} value={f.id} maxLength={253} placeholder="example.org" onChange={(e) => set("id")(e.target.value)} disabled={locked}
            hint={tr("Nom de domaine, sans protocole ni port. Le changer casse les credentials existants.")} />
          <Field label={tr("Origine du site (origin)")} value={f.origin} maxLength={300} placeholder="https://pve.example.org:8006" onChange={(e) => set("origin")(e.target.value)} disabled={locked}
            hint={tr("L'adresse que les utilisateurs tapent dans leur navigateur : https://, ou http://localhost")} />
          <Field label={tr("Nom affiché (rp)")} value={f.rp} maxLength={64} placeholder="Kaji" onChange={(e) => set("rp")(e.target.value)} disabled={locked} hint={tr("Sans virgule ni guillemet")} />
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={f.sub} disabled={locked} onChange={(e) => { setF((c) => ({ ...c, sub: e.target.checked })); setPending(null); }} />
            <span>{tr("Autoriser les sous-domaines")}</span></label>
        </div>
        {isSet && !locked && <div><Button variant="ghost" disabled={busy} onClick={() => apply({ clear: ["webauthn"] })} className="!px-3 !py-1.5">{tr("Retirer WebAuthn")}</Button></div>}
        {pending && (
          <div className="space-y-3 rounded-lg border border-line p-4">
            <Notice kind="error"><ul className="list-disc space-y-1 pl-5">
              <li>{tr("WebAuthn valide la double authentification dans le navigateur : un réglage faux peut empêcher des comptes de se connecter.")}</li>
              {brk && <li>{tr("Changer ou retirer une valeur déjà définie casse (ou peut casser) les credentials WebAuthn enregistrés : ces comptes ne pourront plus valider leur double authentification.")}</li>}
            </ul></Notice>
            <dl className="text-xs">{Object.entries(pending.preview.params).map(([k, v]) => <div key={k} className="flex justify-between gap-4 py-0.5"><dt className="text-muted">{k}</dt><dd className="break-all font-mono">{String(v)}</dd></div>)}
              {pending.preview.remove.map((k) => <div key={k} className="flex justify-between gap-4 py-0.5"><dt className="text-muted">{k}</dt><dd className="font-mono">{tr("retiré")}</dd></div>)}</dl>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /><span>{tr("Je comprends et je confirme")}</span></label>
            {brk && <>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{tr("J'ai compris que les credentials existants peuvent être cassés")}</span></label>
              <Field label={tr("Retape {phrase} pour confirmer", { phrase: FENCING_PHRASE })} value={phrase} maxLength={40} onChange={(e) => setPhrase(e.target.value)} />
            </>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" disabled={busy} onClick={() => setPending(null)}>{tr("Annuler")}</Button>
              <Button disabled={!canConfirm || busy} onClick={confirmApply}>{busy ? "…" : tr("Confirmer et appliquer")}</Button>
            </div>
          </div>
        )}
        {!pending && <div className="flex justify-end"><Button disabled={!changed || busy || locked} onClick={() => apply(body)}>{busy ? "…" : tr("Appliquer")}</Button></div>}
      </div>
    </section>
  );
}
