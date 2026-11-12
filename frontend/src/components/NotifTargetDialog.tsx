import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { TYPE_LABEL, type NotifDetail, type NotifPreview, type NotifTarget, type NotifType } from "../lib/types/notifications";
import { Modal } from "./Modal";
import { Field, Notice } from "./ui";

import { tr } from "../lib/i18n";
export type TargetMode = { kind: "new" } | { kind: "edit" | "delete" | "test"; target: NotifTarget };
type Pair = { name: string; value: string };
const list = (s: string) => s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);

/** Cibles de notification : ajouter, modifier, supprimer, TESTER (envoie un vrai message). Secrets en écriture seule : champ vide = inchangé. */
export function NotifTargetDialog({ connId, mode, onClose }: { connId: number; mode: TargetMode; onClose: () => void }) {
  const qc = useQueryClient();
  const k = mode.kind, tg = mode.kind === "new" ? null : mode.target;
  const [type, setType] = useState<NotifType>(tg?.type ?? "smtp");
  const t = tg?.type ?? type;
  const detail = useQuery({ queryKey: ["notif-target", connId, tg?.name], queryFn: () => api<NotifDetail>(`/api/connections/${connId}/notifications/targets/${tg!.type}/${tg!.name}`), enabled: k === "edit" });
  const d = detail.data;
  const [f, setF] = useState<Record<string, string>>({});
  const [disable, setDisable] = useState(false), [headers, setHeaders] = useState<Pair[]>([]), [secrets, setSecrets] = useState<Pair[]>([]), [clearSecret, setClearSecret] = useState(false);
  const [typed, setTyped] = useState(""), [preview, setPreview] = useState<NotifPreview | null>(null);
  const [busy, setBusy] = useState(false), [done, setDone] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!d) return;
    setF({ server: d.server ?? "", port: d.port?.toString() ?? "", mode: d.mode ?? "", username: d.username ?? "", from_address: d.from_address ?? "", author: d.author ?? "", mailto: (d.mailto ?? []).join(", "),
      mailto_user: (d.mailto_user ?? []).join(", "), comment: d.comment ?? "", url: d.url ?? "", method: d.method ?? "" });
    setDisable(d.disable);
  }, [d]);
  useEffect(() => { setPreview(null); setErr(null); }, [f, disable, headers, secrets, clearSecret, type]);
  const set = (key: string) => (v: string) => setF((c) => ({ ...c, [key]: v }));
  const cur = (key: string): string => (d ? (d as unknown as Record<string, unknown>)[key]?.toString() ?? "" : "");

  const body = (extra: Record<string, unknown>) => {
    const b: Record<string, unknown> = {}, clear: string[] = [];
    const text = (key: string, asNum = false) => { const v = f[key] ?? ""; if (k === "edit" && v === cur(key)) return; if (v !== "") b[key] = asNum ? Number(v) : v; else if (k === "edit" && cur(key) !== "" && !["server", "from_address", "url", "method"].includes(key)) clear.push(key); };
    const arr = (key: "mailto" | "mailto_user") => { const v = list(f[key] ?? ""); if (k === "edit" && v.join(",") === (d?.[key] ?? []).join(",")) return; if (v.length) b[key] = v; else if (k === "edit" && (d?.[key] ?? []).length) clear.push(key); };
    if (t === "sendmail" || t === "smtp") { arr("mailto"); arr("mailto_user"); text("from_address"); text("author"); }
    if (t === "smtp") { text("server"); text("port", true); text("mode"); text("username"); if (f.password) b.password = f.password; else if (clearSecret) clear.push("password"); }
    if (t === "gotify") { text("server"); if (f.token) b.token = f.token; }
    if (t === "webhook") { text("url"); text("method"); if (headers.length) b.headers = headers.filter((x) => x.name && x.value); if (secrets.length) b.secrets = secrets.filter((x) => x.name && x.value); if (f.body) b.body = f.body; else if (clearSecret) clear.push("body"); }
    text("comment");
    if (k === "new" || disable !== d?.disable) b.disable = disable;
    return { ...b, ...(clear.length ? { clear } : {}), ...(k === "new" ? { name: f.name } : {}), ...(k === "edit" ? { digest: d?.digest } : {}), ...extra };
  };
  const base = `/api/connections/${connId}/notifications`;
  const request = (extra: Record<string, unknown>) => {
    if (k === "new") return { path: `${base}/targets/${type}`, init: { method: "POST", body: body(extra) } };
    if (k === "edit") return { path: `${base}/targets/${t}/${tg!.name}`, init: { method: "PUT", body: body(extra) } };
    if (k === "test") return { path: `${base}/targets/${tg!.name}/test`, init: { method: "POST", body: { ...extra, ...(extra.dry_run ? {} : { type_name: typed }) } } };
    return { path: `${base}/targets/${t}/${tg!.name}?${new URLSearchParams({ ...(extra.dry_run ? { dry_run: "true" } : { confirm: "true", type_name: typed }) })}`, init: { method: "DELETE" } };
  };
  const look = async () => { setErr(null); try { const r = request({ dry_run: true }); setPreview(await api<NotifPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try { const r = request({ confirm: true }); await api(r.path, r.init); await qc.invalidateQueries({ queryKey: ["notifications", connId] }); setDone(k === "test" ? tr("Message de test envoyé. Vérifie sa réception.") : k === "delete" ? tr("Cible supprimée.") : tr("Enregistré, relu chez Proxmox.")); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const ready = !!preview && ((k !== "delete" && k !== "test") || typed === tg?.name);
  const readyToLook = k === "new" ? !!f.name : k === "edit" ? !!d : true;
  const txt = (label: string, key: string, hint?: string, kind: "text" | "number" | "password" = "text") => <Field label={label} type={kind} value={f[key] ?? ""} onChange={(e) => set(key)(e.target.value)} hint={hint} autoComplete="off" />;
  const sel = (label: string, key: string, opts: string[]) => (
    <label className="block space-y-1.5 text-sm"><span className="text-muted">{label}</span><select className="field" value={f[key] ?? ""} onChange={(e) => set(key)(e.target.value)}><option value="">{tr("Défaut de Proxmox")}</option>{opts.map((o) => <option key={o}>{o}</option>)}</select></label>);
  const pairs = (label: string, items: Pair[], setItems: (p: Pair[]) => void, hint: string) => (
    <fieldset className="space-y-1.5 text-sm"><legend className="text-muted">{label}</legend>
      {items.map((p, i) => (<div key={i} className="flex gap-2"><input className="field w-1/3" placeholder={tr("nom")} value={p.name} autoComplete="off" onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
        <input className="field flex-1" type="password" placeholder={tr("valeur (jamais relue)")} value={p.value} autoComplete="off" onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
        <button type="button" className="text-danger underline" onClick={() => setItems(items.filter((_, j) => j !== i))}>{tr("Retirer")}</button></div>))}
      <button type="button" className="underline" onClick={() => setItems([...items, { name: "", value: "" }])}>{tr("Ajouter")}</button><p className="text-xs text-muted">{hint}</p></fieldset>);

  if (done) return <Modal title={tr("Fait")} onClose={onClose} onSubmit={onClose} submitLabel={tr("Fermer")} canSubmit><Notice kind="ok">{done}</Notice></Modal>;
  const title = k === "new" ? tr("Ajouter une cible de notification") : k === "edit" ? `Modifier ${tg!.name}` : k === "delete" ? `Supprimer ${tg!.name}` : `Tester ${tg!.name}`;
  return (
    <Modal title={title} subtitle={tr("L'aperçu dit ce qui sera envoyé ; les secrets ne sont jamais affichés.")} onClose={busy ? () => {} : onClose} onSubmit={run} submitLabel={k === "delete" ? tr("Supprimer") : k === "test" ? tr("Envoyer le test") : tr("Appliquer")}
      danger={k === "delete" || k === "test"} busy={busy} error={err} canSubmit={ready} wide>
      {(k === "delete" || k === "test") ? <Notice kind="error">{k === "test" ? <>{tr("Cela envoie un")}{" "}<b>{tr("VRAI message")}</b>{" "}{tr("à la cible")}{" "}<code>{tg!.name}</code>{" "}{tr("({p}). Une fois par minute au plus.", { p: TYPE_LABEL[tg!.type] })}</> : <>{tr("La cible")}{" "}<code>{tg!.name}</code>{" "}{tr("sera supprimée (refusé si une règle l'utilise).")}</>}{" "}{tr("Retape")}{" "}<code>{tg!.name}</code>{" "}{tr("pour confirmer.")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-2" /></Notice>
        : k === "edit" && !d ? <p className="text-sm text-muted">{tr("Chargement…")}</p> : <>
        {k === "new" && <div className="grid gap-4 sm:grid-cols-2"><Field label={tr("Nom")} value={f.name ?? ""} onChange={(e) => set("name")(e.target.value)} maxLength={64} hint={tr("Lettre puis lettres, chiffres, . _ -")} autoComplete="off" />
          <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Type")}</span><select className="field" value={type} onChange={(e) => setType(e.target.value as NotifType)}>{(Object.keys(TYPE_LABEL) as NotifType[]).map((x) => <option key={x} value={x}>{TYPE_LABEL[x]}</option>)}</select></label></div>}
        {(t === "sendmail" || t === "smtp") && <>
          <div className="grid gap-4 sm:grid-cols-2">{txt(tr("Destinataires (e-mails, séparés par des virgules)"), "mailto")}{txt(tr("Utilisateurs Proxmox (user@realm, séparés par des virgules)"), "mailto_user")}</div>
          <div className="grid gap-4 sm:grid-cols-2">{txt(t === "smtp" ? tr("Adresse d'expédition (obligatoire)") : tr("Adresse d'expédition"), "from_address")}{txt(tr("Auteur"), "author")}</div></>}
        {t === "smtp" && <>
          <div className="grid gap-4 sm:grid-cols-3">{txt("Serveur SMTP (obligatoire)", "server", tr("Adresses locales refusées"))}{txt(tr("Port"), "port", tr("1 à 65535"), "number")}{sel(tr("Chiffrement"), "mode", ["insecure", "starttls", "tls"])}</div>
          <div className="grid gap-4 sm:grid-cols-2">{txt("Nom d'utilisateur", "username")}{txt(k === "edit" ? tr("Mot de passe (jamais relu : vide = inchangé)") : tr("Mot de passe"), "password", tr("Écriture seule"), "password")}</div>
          {k === "edit" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={clearSecret} onChange={(e) => setClearSecret(e.target.checked)} />{tr("Retirer le mot de passe")}</label>}</>}
        {t === "gotify" && <div className="grid gap-4 sm:grid-cols-2">{txt(tr("URL du serveur Gotify (obligatoire)"), "server", tr("http(s)://…, sans identifiants"))}{txt(k === "edit" ? tr("Jeton (jamais relu : vide = inchangé)") : "Jeton (obligatoire)", "token", tr("Écriture seule"), "password")}</div>}
        {t === "webhook" && <>
          <div className="grid gap-4 sm:grid-cols-3"><div className="sm:col-span-2">{txt("URL (obligatoire)", "url", tr("http(s)://…, sans identifiants, adresses locales refusées"))}</div>{sel(tr("Méthode (obligatoire)"), "method", ["post", "put", "get"])}</div>
          {pairs(tr("En-têtes HTTP"), headers, setHeaders, k === "edit" ? tr("Remplace TOUS les en-têtes actuels (leurs valeurs ne sont pas relues) : laisse vide pour ne rien changer.") : tr("Valeurs saisies en clair, encodées par Kaji."))}
          {pairs(tr("Secrets (utilisables dans le corps)"), secrets, setSecrets, k === "edit" ? tr("Remplace tous les secrets actuels : laisse vide pour ne rien changer.") : tr("Jamais relus."))}
          <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Corps (modèle)")}</span><textarea className="field min-h-[5rem] font-mono text-xs" value={f.body ?? ""} onChange={(e) => set("body")(e.target.value)} autoComplete="off" /></label>
          {k === "edit" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={clearSecret} onChange={(e) => setClearSecret(e.target.checked)} />{tr("Retirer le corps")}</label>}</>}
        {txt(tr("Commentaire"), "comment", tr("ASCII uniquement : Proxmox altère les accents"))}
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={disable} onChange={(e) => setDisable(e.target.checked)} /><span><b>{tr("Désactivée")}</b>{" "}{tr(": la cible existe mais ne reçoit rien")}</span></label>
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!readyToLook} onClick={look}>{tr("Aperçu")}</button>
      {preview && <Notice kind="ok">{k === "delete" ? <>{tr("Sera supprimé :")}{" "}<code>{tg!.name}</code></> : k === "test" ? <>{tr("Un message de test partira vers")}{" "}<code>{tg!.name}</code> ({preview.sends_a_real_message ? tr("envoi réel") : ""}).</> :
        <>{tr("Sera envoyé :")}{" "}<code>{Object.entries(preview.params ?? {}).map(([a, b]) => `${a}=${Array.isArray(b) ? b.join("|") : b}`).join(", ") || tr("rien")}</code>{preview.remove?.length ? <>{" "}{tr("· retiré :")}{" "}<code>{preview.remove.join(", ")}</code></> : null}</>}</Notice>}
    </Modal>
  );
}
