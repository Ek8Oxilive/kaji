import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { ENTRY_ID, TFA_PHRASE, USERID, type TfaEntry, type TfaUser, type TotpSetup } from "../lib/types/tfa";
import { AccountSelect } from "./AccountSelect";
import { Modal } from "./Modal";
import { Button, Notice } from "./ui";

type Act = "totp" | "recovery" | "toggle" | "delete";
const ACT_LABEL: Record<Act, () => string> = {
  totp: () => tr("Ajouter un TOTP (application d'authentification)"), recovery: () => tr("Ajouter des codes de secours"),
  toggle: () => tr("Activer ou désactiver une entrée"), delete: () => tr("Supprimer une entrée"),
};
const TYPE_LABEL: Record<string, () => string> = { totp: () => tr("TOTP"), recovery: () => tr("Codes de secours"), webauthn: () => tr("WebAuthn"), u2f: () => tr("U2F"), yubico: () => tr("YubiKey") };

/** Double authentification : lister, ajouter un TOTP ou des codes de secours, activer / désactiver, supprimer. Écriture par la session administrateur ; le serveur refuse root, Kaji et la session administrateur.
 *  Activer la double authentification sur un compte dont le titulaire n'a pas le secret le verrouille : le serveur exige alors la phrase. Pas de mot de passe demandé. */
export function TfaDialog({ connId, onClose }: { connId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const base = `/api/connections/${connId}/access/tfa`;
  const list = useQuery({ queryKey: ["access", connId, "tfa"], staleTime: 10_000, queryFn: () => api<TfaUser[]>(base) });
  const [act, setAct] = useState<Act>("recovery");
  const [userid, setUserid] = useState(""), [entry, setEntry] = useState(""), [desc, setDesc] = useState(""), [enable, setEnable] = useState(true), [typed, setTyped] = useState("");
  const [setup, setSetup] = useState<TotpSetup | null>(null), [code, setCode] = useState("");
  const [cut, setCut] = useState(false), [ack, setAck] = useState(false), [phrase, setPhrase] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null), [noted, setNoted] = useState(false);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [done, setDone] = useState<string | null>(null);
  const userOk = USERID.test(userid);
  const needEntry = act === "toggle" || act === "delete";
  const entries = list.data?.find((u) => u.userid === userid)?.entries ?? [];
  const picked: TfaEntry | undefined = entries.find((e) => e.id === entry);

  useEffect(() => { setErr(null); setCut(false); setAck(false); setPhrase(""); setTyped(""); }, [act, userid, entry]);
  useEffect(() => { setSetup(null); setCode(""); }, [act, userid]);

  const valid = userOk && (!needEntry || ENTRY_ID.test(entry)) && (act !== "totp" || (setup !== null && /^[0-9]{6,8}$/.test(code)));
  const canSubmit = valid && typed === userid && (!cut || (ack && phrase === TFA_PHRASE));
  const lock = cut ? { acknowledge_cut_access: true, phrase } : {};

  const generate = async () => {
    setBusy(true); setErr(null);
    try { setSetup(await api<TotpSetup>(`${base}/totp-setup`, { method: "POST", body: { userid } })); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const run = async () => {
    setBusy(true); setErr(null);
    const ok = { confirm: true, type_name: typed, ...lock };
    try {
      if (act === "totp") await api(base, { method: "POST", body: { userid, type: "totp", totp: setup?.uri, value: code, ...(desc ? { description: desc } : {}), ...ok } });
      else if (act === "recovery") {
        const r = await api<{ recovery: string[] }>(base, { method: "POST", body: { userid, type: "recovery", ...(desc ? { description: desc } : {}), ...ok } });
        setCodes(r.recovery); setNoted(false);
      }
      else if (act === "toggle") await api(`${base}/${encodeURIComponent(userid)}/${encodeURIComponent(entry)}`, { method: "PUT", body: { enable, ...ok } });
      else await api(`${base}/${encodeURIComponent(userid)}/${encodeURIComponent(entry)}?confirm=true&name=${encodeURIComponent(typed)}`, { method: "DELETE" });
      await qc.invalidateQueries({ queryKey: ["access", connId] });
      setSetup(null); setCode("");
      setDone(ACT_LABEL[act]());
    } catch (e) {
      const m = (e as Error).message;
      setErr(m);
      if (m.startsWith("Coupure possible") || m.startsWith("Possible outage")) setCut(true);
    }
    setBusy(false);
  };

  if (codes) return (
    <Modal title={tr("Codes de secours créés")} onClose={() => {}} onSubmit={() => setCodes(null)} submitLabel={tr("Terminer")} canSubmit={noted}>
      <Notice kind="error">{tr("Note ces codes maintenant (gestionnaire de mots de passe). Ils ne seront")}{" "}<b>{tr("plus jamais affichés")}</b>{" "}{tr(": ni par Kaji, ni par Proxmox.")}</Notice>
      <textarea readOnly className="field font-mono text-sm" rows={Math.max(3, codes.length)} value={codes.join("\n")} onFocus={(e) => e.currentTarget.select()} aria-label={tr("Codes de secours")} />
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={noted} onChange={(e) => setNoted(e.target.checked)} /><span>{tr("J'ai noté les codes")}</span></label>
    </Modal>
  );
  if (done) return (
    <Modal title={tr("Fait")} onClose={onClose} onSubmit={onClose} submitLabel={tr("Fermer")} canSubmit>
      <Notice kind="ok">{done} : <code>{userid}</code>{tr(". Relu chez Proxmox, visible dans la liste.")}</Notice>
    </Modal>
  );
  return (
    <Modal title={tr("Double authentification")} subtitle={tr("Une écriture à la fois, avec l'identité de la session administrateur. Activer la double authentification sur un compte dont le titulaire n'a pas le secret le verrouille.")}
      onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel={tr("Appliquer")} danger={act === "delete"} busy={busy} error={err} canSubmit={canSubmit} wide>
      <div className="panel max-h-40 overflow-auto p-3 text-sm">
        {list.isLoading ? <p className="text-muted">{tr("Chargement…")}</p> : list.error ? <p className="text-danger">{(list.error as Error).message}</p>
          : (list.data?.length ?? 0) === 0 ? <p className="text-muted">{tr("Aucune entrée visible avec les droits de Kaji.")}</p>
          : <ul className="space-y-1">{list.data!.map((u) => (
            <li key={u.userid}><code>{u.userid}</code>{u.locked ? <span className="ml-2 text-xs text-warn">{tr("verrouillé")}</span> : null}
              <span className="ml-2 text-xs text-muted">{u.entries.map((e) => `${TYPE_LABEL[e.type]?.() ?? e.type}${e.enabled ? "" : tr(" (désactivé)")} · ${e.id}`).join(" ; ")}</span></li>))}</ul>}
      </div>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Action")}</span>
        <select className="field" value={act} onChange={(e) => { setAct(e.target.value as Act); setEntry(""); }}>{(Object.keys(ACT_LABEL) as Act[]).map((a) => <option key={a} value={a}>{ACT_LABEL[a]()}</option>)}</select></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Utilisateur")}</span>
        <AccountSelect connId={connId} kind="users" value={userid} onChange={setUserid} placeholder={tr("bob@pve")} /></label>
      {needEntry && <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Entrée")}</span>
        <select className="field" value={entry} onChange={(e) => setEntry(e.target.value)}><option value="">{tr("Choisir…")}</option>
          {entries.map((e) => <option key={e.id} value={e.id}>{TYPE_LABEL[e.type]?.() ?? e.type} · {e.id}{e.description ? ` · ${e.description}` : ""}{e.enabled ? "" : tr(" (désactivé)")}</option>)}</select>
        {userOk && entries.length === 0 && <span className="block text-xs text-muted">{tr("Aucune entrée connue pour cet utilisateur.")}</span>}</label>}
      {(act === "totp" || act === "recovery") && <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Description (facultatif)")}</span>
        <input className="field" value={desc} maxLength={255} onChange={(e) => setDesc(e.target.value)} autoComplete="off" /></label>}
      {act === "toggle" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={enable} onChange={(e) => setEnable(e.target.checked)} /><span>{tr("Entrée activée")}</span></label>}
      {act === "totp" && <div className="space-y-2 text-sm">
        <Button type="button" variant="ghost" disabled={!userOk || busy} onClick={generate} className="!px-3 !py-1.5">{setup ? tr("Générer un autre secret") : tr("Générer un secret")}</Button>
        {setup && <>
          <Notice kind="error">{tr("Entre ce secret dans l'application d'authentification du titulaire du compte, puis tape le code affiché. Kaji ne garde pas ce secret : il ne sera")}{" "}<b>{tr("plus jamais affiché")}</b>{tr(".")}</Notice>
          <input readOnly value={setup.secret} onFocus={(e) => e.currentTarget.select()} aria-label={tr("Secret TOTP")} className="field font-mono text-xs" />
          <input readOnly value={setup.uri} onFocus={(e) => e.currentTarget.select()} aria-label={tr("URI TOTP")} className="field font-mono text-xs" />
          <label className="block space-y-1"><span className="text-muted">{tr("Code affiché par l'application (6 à 8 chiffres)")}</span>
            <input className="field" inputMode="numeric" value={code} maxLength={8} onChange={(e) => setCode(e.target.value.trim())} autoComplete="off" /></label>
        </>}
      </div>}
      {act === "delete" && picked && <Notice kind="error">{tr("Suppression définitive de cette entrée. Retirer la dernière entrée active désactive la double authentification du compte.")}</Notice>}
      {cut && <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
        <Notice kind="error">{tr("Coupure possible : la double authentification va s'activer sur ce compte. Si son titulaire n'a pas le secret ou les codes, il ne pourra plus se connecter.")}</Notice>
        <label className="flex items-start gap-2"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{tr("Le titulaire a bien le secret ou les codes")}</span></label>
        <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{TFA_PHRASE}</code>{" "}{tr("pour confirmer")}<input value={phrase} onChange={(e) => setPhrase(e.target.value)} autoComplete="off" className="field mt-1" /></label>
      </div>}
      {valid && <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{userid}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>}
    </Modal>
  );
}
