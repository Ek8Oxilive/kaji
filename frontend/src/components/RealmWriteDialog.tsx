import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { CLEARABLE, FIELDS, KIND_LABEL, PHRASE, REALM_KINDS, REQUIRED, TYPE_FIELDS, type RealmDetail, type RealmKind } from "../lib/types/realms";
import type { AccessRealm } from "../lib/types/acces";
import { Modal } from "./Modal";
import { Notice } from "./ui";

type Act = "create" | "edit" | "delete" | "sync";
type Vals = Record<string, string | boolean>;
const ACT_LABEL: Record<Act, () => string> = { create: () => tr("Créer un realm"), edit: () => tr("Modifier un realm"), delete: () => tr("Supprimer un realm"), sync: () => tr("Synchroniser un realm") };
const REALM_ID = /^[A-Za-z][A-Za-z0-9._-]{1,31}$/;
const BUILTIN = ["pam", "pve"];
const VANISHED = ["acl", "properties", "entry"] as const;

/** Realms d'authentification : créer, modifier, supprimer, synchroniser (LDAP, Active Directory, OpenID). Écriture par la session administrateur ; le serveur revérifie tout et annonce les coupures possibles. */
export function RealmWriteDialog({ connId, onClose }: { connId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const realms = useQuery({ queryKey: ["access", connId, "realms"], staleTime: 15_000, queryFn: () => api<AccessRealm[]>(`/api/connections/${connId}/access/realms`) }).data ?? [];
  const [act, setAct] = useState<Act>("create");
  const [kind, setKind] = useState<RealmKind>("ldap");
  const [realm, setRealm] = useState(""), [typed, setTyped] = useState("");
  const [vals, setVals] = useState<Vals>({}), [orig, setOrig] = useState<RealmDetail | null>(null);
  const [cut, setCut] = useState(false), [ack, setAck] = useState(false), [phrase, setPhrase] = useState("");
  const [dry, setDry] = useState(true), [scope, setScope] = useState(""), [enableNew, setEnableNew] = useState(true), [vanished, setVanished] = useState<string[]>([]);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [done, setDone] = useState<string | null>(null);
  const base = `/api/connections/${connId}/access/realms`;
  const known = realms.find((r) => r.realm === realm);
  const typ = act === "create" ? kind : known?.type ?? "";
  const fields = TYPE_FIELDS[typ] ?? [];
  const pickable = realms.filter((r) => act === "sync" ? r.type === "ldap" || r.type === "ad" : act === "delete" ? !BUILTIN.includes(r.realm) : true);

  useEffect(() => { setErr(null); setCut(false); setAck(false); setPhrase(""); setTyped(""); }, [act, realm, kind]);
  useEffect(() => {
    setVals({}); setOrig(null);
    if (act !== "edit" || !known) return;
    let live = true;
    api<RealmDetail>(`${base}/${encodeURIComponent(realm)}`).then((d) => {
      if (!live) return;
      setOrig(d);
      setVals(Object.fromEntries((TYPE_FIELDS[d.type] ?? []).filter((k) => FIELDS[k]?.kind !== "secret").map((k) => [k, FIELDS[k].kind === "bool" ? d[k] === true : d[k] == null ? "" : String(d[k])])));
    }).catch((e) => live && setErr((e as Error).message));
    return () => { live = false; };
  }, [act, realm]);                                                    // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k: string, v: string | boolean) => setVals((c) => ({ ...c, [k]: v }));
  const conv = (k: string, v: string | boolean) => (FIELDS[k].kind === "number" ? Number(v) : v);

  /** Corps de création ou de modification : seulement ce qui est rempli (création) ou ce qui a changé (modification). */
  const body = () => {
    const b: Record<string, unknown> = {}, clear: string[] = [];
    for (const k of fields) {
      const def = FIELDS[k], v = vals[k];
      if (act === "create") { if (def.kind === "bool" ? v === true : typeof v === "string" && v.trim() !== "") b[k] = conv(k, typeof v === "string" ? v.trim() : v); continue; }
      if (def.kind === "secret") { if (typeof v === "string" && v !== "") b[k] = v; continue; }
      const was = def.kind === "bool" ? orig?.[k] === true : orig?.[k] == null ? "" : String(orig[k]);
      if (v === was || v === undefined) continue;
      if (def.kind === "bool") b[k] = v === true;
      else if (typeof v === "string" && v.trim() !== "") b[k] = conv(k, v.trim());
      else if (CLEARABLE.has(k)) clear.push(k);
    }
    return { ...b, ...(clear.length ? { clear } : {}) };
  };
  const payload = body();
  const missing = act === "create" ? REQUIRED[kind].filter((k) => !(k in payload)) : [];
  const idOk = act === "create" ? REALM_ID.test(realm) && !BUILTIN.includes(realm) && !realms.some((r) => r.realm === realm) : realm !== "";
  const valid = act === "create" ? idOk && missing.length === 0 : act === "edit" ? idOk && Object.keys(payload).length > 0 : idOk;
  const needTyped = !(act === "sync" && dry);
  const canSubmit = valid && (!needTyped || typed === realm) && (!cut || (ack && phrase === PHRASE));
  const lock = cut ? { acknowledge_cut_access: true, phrase } : {};

  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const ok = { confirm: true, type_name: typed, ...lock };
      if (act === "create") await api(base, { method: "POST", body: { realm, type: kind, ...payload, confirm: true, type_name: typed } });
      else if (act === "edit") await api(`${base}/${encodeURIComponent(realm)}`, { method: "PUT", body: { ...payload, digest: orig?.digest, ...ok } });
      else if (act === "delete") await api(`${base}/${encodeURIComponent(realm)}?confirm=true&name=${encodeURIComponent(typed)}${cut ? `&acknowledge_cut_access=true&phrase=${encodeURIComponent(phrase)}` : ""}`, { method: "DELETE" });
      else {
        const r = await api<{ upid: string | null }>(`${base}/${encodeURIComponent(realm)}/sync`, { method: "POST", body: { dry_run: dry, ...(scope ? { scope } : {}), ...(enableNew ? {} : { enable_new: false }),
          remove_vanished: vanished, ...(dry ? {} : ok) } });
        setDone(`${dry ? tr("Simulation lancée") : tr("Synchronisation lancée")}${r.upid ? ` (${r.upid})` : ""}`);
        await qc.invalidateQueries({ queryKey: ["access", connId] }); setBusy(false); return;
      }
      await qc.invalidateQueries({ queryKey: ["access", connId] });
      setDone(ACT_LABEL[act]()); setBusy(false);
    } catch (e) {
      const m = (e as Error).message;
      setErr(m); setBusy(false);
      if (m.startsWith("Coupure possible") || m.startsWith("Possible outage")) setCut(true);
    }
  };

  if (done) return (
    <Modal title={tr("Fait")} onClose={onClose} onSubmit={onClose} submitLabel={tr("Fermer")} canSubmit>
      <Notice kind="ok">{done} : <code>{realm}</code>{tr(". Relu chez Proxmox, visible dans la liste des realms.")}</Notice>
    </Modal>
  );
  const destructive = act === "delete" || (act === "sync" && !dry && vanished.length > 0);
  return (
    <Modal title={tr("Realms d'authentification")} subtitle={tr("Une écriture à la fois, avec l'identité de la session administrateur. Un realm mal réglé peut empêcher des comptes de se connecter.")}
      onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel={act === "sync" && dry ? tr("Simuler") : tr("Appliquer")} danger={destructive} busy={busy} error={err} canSubmit={canSubmit} wide>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Action")}</span>
        <select className="field" value={act} onChange={(e) => { setAct(e.target.value as Act); setRealm(""); }}>{(Object.keys(ACT_LABEL) as Act[]).map((a) => <option key={a} value={a}>{ACT_LABEL[a]()}</option>)}</select></label>
      {act === "create" ? <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Type")}</span>
          <select className="field" value={kind} onChange={(e) => { setKind(e.target.value as RealmKind); setVals({}); }}>{REALM_KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]()}</option>)}</select></label>
        <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Identifiant du realm")}</span>
          <input className="field" value={realm} maxLength={32} onChange={(e) => setRealm(e.target.value.trim())} placeholder={tr("entreprise")} autoComplete="off" />
          <span className="block text-xs text-muted">{tr("Lettre, puis lettres, chiffres, . _ - ; pam et pve sont réservés")}</span></label>
      </div> : <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Realm")}</span>
        <select className="field" value={realm} onChange={(e) => setRealm(e.target.value)}><option value="">{tr("Choisir…")}</option>{pickable.map((r) => <option key={r.realm} value={r.realm}>{r.realm} ({r.type})</option>)}</select></label>}

      {(act === "create" || act === "edit") && typ !== "" && <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((k) => {
          const def = FIELDS[k], v = vals[k];
          if (def.kind === "bool") return <label key={k} className="flex items-start gap-2 pt-5 text-sm"><input type="checkbox" checked={v === true} onChange={(e) => set(k, e.target.checked)} /><span>{def.label()}</span></label>;
          return (
            <label key={k} className="block space-y-1 text-sm"><span className="text-muted">{def.label()}{act === "create" && REQUIRED[kind].includes(k) ? " *" : ""}</span>
              {def.kind === "select"
                ? <select className="field" value={typeof v === "string" ? v : ""} onChange={(e) => set(k, e.target.value)}><option value="">{tr("Défaut de Proxmox")}</option>{def.options?.map((o) => <option key={o} value={o}>{o}</option>)}</select>
                : <input className="field" type={def.kind === "secret" ? "password" : def.kind === "number" ? "number" : "text"} value={typeof v === "string" ? v : ""} onChange={(e) => set(k, e.target.value)}
                    autoComplete={def.kind === "secret" ? "new-password" : "off"} />}
              {def.hint && <span className="block text-xs text-muted">{def.hint()}</span>}</label>);
        })}
      </div>}

      {act === "sync" && realm !== "" && <div className="space-y-3 text-sm">
        <label className="flex items-start gap-2"><input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} /><span>{tr("Simuler seulement : Proxmox n'écrit rien")}</span></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-1"><span className="text-muted">{tr("Ce qu'on synchronise")}</span>
            <select className="field" value={scope} onChange={(e) => setScope(e.target.value)}><option value="">{tr("Défaut du realm")}</option><option value="users">{tr("Utilisateurs")}</option><option value="groups">{tr("Groupes")}</option><option value="both">{tr("Les deux")}</option></select></label>
          <label className="flex items-start gap-2 pt-5"><input type="checkbox" checked={enableNew} onChange={(e) => setEnableNew(e.target.checked)} /><span>{tr("Activer tout de suite les nouveaux comptes")}</span></label>
        </div>
        <fieldset className="space-y-1"><legend className="text-muted">{tr("Retirer ce qui a disparu de l'annuaire")}</legend>
          {VANISHED.map((x) => <label key={x} className="mr-4 inline-flex items-center gap-1.5"><input type="checkbox" checked={vanished.includes(x)}
            onChange={(e) => setVanished((c) => e.target.checked ? [...c, x] : c.filter((y) => y !== x))} />{x === "acl" ? tr("droits (ACL)") : x === "properties" ? tr("propriétés") : tr("comptes")}</label>)}
        </fieldset>
      </div>}

      {act === "delete" && realm !== "" && <Notice kind="error">{tr("Suppression définitive du realm. Les comptes de ce realm ne pourront plus se connecter ; le serveur refuse pam, pve et le realm du compte de Kaji.")}</Notice>}
      {act === "create" && missing.length > 0 && <p className="text-xs text-muted">{tr("Champs obligatoires : {p}", { p: missing.map((k) => FIELDS[k].label()).join(", ") })}</p>}
      {cut && <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
        <Notice kind="error">{tr("Coupure possible : des comptes de ce realm peuvent ne plus pouvoir se connecter. Confirme explicitement.")}</Notice>
        <label className="flex items-start gap-2"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{tr("J'accepte ce risque")}</span></label>
        <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{PHRASE}</code>{" "}{tr("pour confirmer")}<input value={phrase} onChange={(e) => setPhrase(e.target.value)} autoComplete="off" className="field mt-1" /></label>
      </div>}
      {needTyped && valid && <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{realm}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>}
    </Modal>
  );
}
