import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ClusterSettings } from "../components/ClusterSettings";
import { WebauthnSettings } from "../components/WebauthnSettings";
import { MetricsServers } from "../components/MetricsServers";
import { ResourceMappings } from "../components/ResourceMappings";
import { NotificationsSection } from "../components/NotificationsSection";
import { PoolsSection } from "../components/PoolsSection";
import { Button, Field, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { CONSOLES, KEYBOARDS, LANGUAGES, ORDERINGS, SHAPES, USER_ALLOW, type DatacenterOptions, type TagColor } from "../lib/types/datacenter";

import { tr } from "../lib/i18n";
const tagsOf = (s: string) => [...new Set(s.split(/[\s,;]+/).map((x) => x.trim().toLowerCase()).filter(Boolean))];

/** Table des couleurs d'étiquettes : une ligne par étiquette, « nom couleur [couleur-du-texte] » (couleurs en hexadécimal, sans #). */
const colorsToText = (m: TagColor[]) => m.map((c) => `${c.tag} ${c.color}${c.text ? " " + c.text : ""}`).join("\n");
const textToColors = (s: string): TagColor[] => s.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
  const [tag = "", color = "", text] = l.split(/\s+/);
  return { tag, color: color.replace(/^#/, ""), text: text ? text.replace(/^#/, "") : null };
});

const LABELS: Record<string, string> = { get ha() { return tr("Haute disponibilité"); }, get fencing() { return tr("Mode de fencing"); }, get crs() { return tr("Ordonnancement des ressources"); }, get bwlimit() { return tr("Limites de débit"); }, get "next-id"() { return tr("Plage des identifiants libres"); }, get "tag-style"() { return tr("Style des étiquettes"); }, get replication() { return tr("Réplication"); } };

/** Datacenter → Options et notes. Liste blanche côté serveur ; HA, fencing, CRS, débits et réplication : section `ClusterSettings` (lot #365). */
export function Datacenter({ onGoConnections }: { onGoConnections: () => void }) {
  const { active, id } = useActiveConnection();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["datacenter", id], queryFn: () => api<DatacenterOptions>(`/api/connections/${id}/datacenter/options`), enabled: id !== null });
  const d = q.data;
  const [f, setF] = useState({ keyboard: "", language: "", console: "", email_from: "", mac_prefix: "", max_workers: "", http_proxy: "", mtype: "", mnet: "", idlo: "", idhi: "", tshape: "", tord: "", tcase: false, tcolors: "", rtags: "", uallow: "", ulist: "", consent: "" });
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);
  useEffect(() => {
    if (!d) return;
    setF({ keyboard: d.keyboard ?? "", language: d.language ?? "", console: d.console ?? "", email_from: d.email_from ?? "", mac_prefix: d.mac_prefix ?? "", max_workers: d.max_workers?.toString() ?? "",
      http_proxy: d.http_proxy ?? "", mtype: d.migration.type ?? "", mnet: d.migration.network ?? "",
      idlo: d.next_id.lower?.toString() ?? "", idhi: d.next_id.upper?.toString() ?? "", tshape: d.tag_style.shape ?? "", tord: d.tag_style.ordering ?? "", tcase: !!d.tag_style.case_sensitive, tcolors: colorsToText(d.tag_style.color_map),
      rtags: d.registered_tags.join("\n"), uallow: d.user_tag_access.user_allow ?? "", ulist: d.user_tag_access.user_allow_list.join(", "), consent: d.consent_text ?? "" });
    setNotes(d.description ?? "");
  }, [d]);
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center"><div className="panel space-y-4 p-10">
      <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1><Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button></div></div>
  );
  const set = (k: Exclude<keyof typeof f, "tcase">) => (v: string) => setF((cur) => ({ ...cur, [k]: v }));
  const setCase = (v: boolean) => setF((cur) => ({ ...cur, tcase: v }));
  const insecureNew = f.mtype === "insecure" && d?.migration.type !== "insecure";

  /** Corps de la requête : seulement ce qui a changé ; un champ vidé qui avait une valeur est retiré (`clear`). */
  const diff = () => {
    if (!d) return {};
    const body: Record<string, unknown> = {}, clear: string[] = [];
    const text = (k: "keyboard" | "language" | "console" | "email_from" | "mac_prefix" | "http_proxy", cur: string | null) => { if (f[k] !== (cur ?? "")) { if (f[k]) body[k] = f[k]; else clear.push(k); } };
    text("keyboard", d.keyboard); text("language", d.language); text("console", d.console); text("email_from", d.email_from); text("mac_prefix", d.mac_prefix); text("http_proxy", d.http_proxy);
    if (f.max_workers !== (d.max_workers?.toString() ?? "")) { if (f.max_workers) body.max_workers = Number(f.max_workers); else clear.push("max_workers"); }
    if (f.mtype !== (d.migration.type ?? "") || f.mnet !== (d.migration.network ?? "")) {
      if (!f.mtype && !f.mnet) clear.push("migration");
      else body.migration = { ...(f.mtype !== (d.migration.type ?? "") && f.mtype ? { type: f.mtype } : {}), ...(f.mnet !== (d.migration.network ?? "") ? { network: f.mnet } : {}) };
    }
    const lo = f.idlo !== (d.next_id.lower?.toString() ?? ""), hi = f.idhi !== (d.next_id.upper?.toString() ?? "");
    if (lo || hi) body.next_id = { ...(lo && f.idlo ? { lower: Number(f.idlo) } : {}), ...(hi && f.idhi ? { upper: Number(f.idhi) } : {}) };
    const ts: Record<string, unknown> = {};
    if (f.tshape !== (d.tag_style.shape ?? "") && f.tshape) ts.shape = f.tshape;
    if (f.tord !== (d.tag_style.ordering ?? "") && f.tord) ts.ordering = f.tord;
    if (f.tcase !== !!d.tag_style.case_sensitive) ts.case_sensitive = f.tcase;
    if (f.tcolors.trim() !== colorsToText(d.tag_style.color_map)) ts.color_map = textToColors(f.tcolors);
    if (Object.keys(ts).length) body.tag_style = ts;
    if (tagsOf(f.rtags).join(" ") !== d.registered_tags.join(" ")) body.registered_tags = tagsOf(f.rtags);
    if (f.uallow !== (d.user_tag_access.user_allow ?? "") || (f.uallow === "list" && tagsOf(f.ulist).join(" ") !== d.user_tag_access.user_allow_list.join(" "))) {
      if (f.uallow) body.user_tag_access = { user_allow: f.uallow, ...(f.uallow === "list" ? { user_allow_list: tagsOf(f.ulist) } : {}) }; else clear.push("user_tag_access");
    }
    if (f.consent !== (d.consent_text ?? "")) { if (f.consent.trim()) body.consent_text = f.consent; else clear.push("consent_text"); }
    return { ...body, ...(clear.length ? { clear } : {}) };
  };
  const save = async (what: string, body: Record<string, unknown>) => {
    setBusy(what); setErr(null); setOk(null);
    try {
      await api(`/api/connections/${id}/datacenter/options`, { method: "PUT", body: { ...body, digest: d?.digest, ...(insecureNew && what === "options" ? { confirm: true } : {}) } });
      await qc.invalidateQueries({ queryKey: ["datacenter", id] });
      setOk(what === "notes" ? tr("Notes enregistrées, relues chez Proxmox.") : tr("Options enregistrées, relues chez Proxmox."));
    } catch (e) { setErr((e as Error).message); }
    setBusy(null);
  };
  const changes = diff(), changed = Object.keys(changes).length > 0;
  const notesChanged = d ? notes !== (d.description ?? "") : false;
  const sel = (label: string, k: Exclude<keyof typeof f, "tcase">, opts: readonly string[]) => (
    <label className="block space-y-1.5 text-sm"><span className="text-muted">{label}</span>
      <select className="field" value={f[k]} onChange={(e) => set(k)(e.target.value)}><option value="">{tr("Défaut de Proxmox")}</option>{opts.map((o) => <option key={o} value={o}>{o}</option>)}</select></label>);

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header><h1 className="text-2xl font-semibold tracking-tight">{tr("Datacenter")}</h1><p className="text-muted">{tr("{name} · options et notes", { name: active.name })}</p></header>
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}
      {err && <Notice kind="error">{err}</Notice>}
      {ok && <Notice kind="ok">{ok}</Notice>}
      {!d ? <p className="text-sm text-muted">{tr("Chargement…")}</p> : <>
        <section className="space-y-4"><h2 className="text-lg font-semibold">{tr("Options")}</h2>
          <div className="panel space-y-4 p-5">
            <div className="grid gap-4 sm:grid-cols-3">{sel(tr("Clavier par défaut"), "keyboard", KEYBOARDS)}{sel(tr("Langue"), "language", LANGUAGES)}{sel(tr("Visionneuse de console"), "console", CONSOLES)}</div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={tr("Adresse d'expédition des e-mails")} value={f.email_from} maxLength={254} onChange={(e) => set("email_from")(e.target.value)} hint={tr("Vide = défaut de Proxmox (root@nœud)")} />
              <Field label={tr("Préfixe des adresses MAC")} value={f.mac_prefix} maxLength={8} placeholder={tr("BC:24:11")} onChange={(e) => set("mac_prefix")(e.target.value)} hint={tr("Trois octets, premier octet pair")} />
              <Field label={tr("Tâches parallèles par nœud (max_workers)")} type="number" min={1} max={64} value={f.max_workers} onChange={(e) => set("max_workers")(e.target.value)} hint={tr("1 à 64")} />
              <Field label={tr("Proxy HTTP des nœuds")} value={f.http_proxy} maxLength={300} placeholder={tr("http://proxy.lan:3128")} onChange={(e) => set("http_proxy")(e.target.value)} hint={tr("http:// uniquement, sans identifiants ; adresses locales refusées")} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Migration : type")}</span>
                <select className="field" value={f.mtype} onChange={(e) => set("mtype")(e.target.value)}><option value="">{tr("Défaut de Proxmox (sécurisé)")}</option><option value="secure">{tr("secure : tunnel SSH chiffré")}</option><option value="insecure">{tr("insecure : non chiffré")}</option></select></label>
              <Field label={tr("Migration : réseau dédié (CIDR)")} value={f.mnet} maxLength={43} placeholder="10.0.0.0/24" onChange={(e) => set("mnet")(e.target.value)} hint={tr("Vide = réseau par défaut")} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={tr("Identifiants libres : à partir de")} type="number" min={100} max={999999999} value={f.idlo} onChange={(e) => set("idlo")(e.target.value)} hint={tr("100 à 999 999 999 ; vide = défaut de Proxmox (100)")} />
              <Field label={tr("Identifiants libres : jusqu'à")} type="number" min={100} max={999999999} value={f.idhi} onChange={(e) => set("idhi")(e.target.value)} hint={tr("Doit être supérieur au début de plage")} />
            </div>
            {(d.next_id.lower !== null || d.next_id.upper !== null) && <div><Button variant="ghost" disabled={busy !== null} onClick={() => save("options", { clear: ["next_id"] })} className="!px-3 !py-1.5">{tr("Retirer la plage d'identifiants")}</Button></div>}
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Étiquettes : forme")}</span>
                <select className="field" value={f.tshape} onChange={(e) => set("tshape")(e.target.value)}>{!d.tag_style.shape && <option value="">{tr("Défaut de Proxmox")}</option>}{SHAPES.map((o) => <option key={o} value={o}>{o}</option>)}</select></label>
              <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Étiquettes : ordre")}</span>
                <select className="field" value={f.tord} onChange={(e) => set("tord")(e.target.value)}>{!d.tag_style.ordering && <option value="">{tr("Défaut de Proxmox")}</option>}{ORDERINGS.map((o) => <option key={o} value={o}>{o === "config" ? tr("config : ordre de la table") : tr("alphabetical : alphabétique")}</option>)}</select></label>
              <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={f.tcase} onChange={(e) => setCase(e.target.checked)} /><span>{tr("Distinguer majuscules et minuscules")}</span></label>
            </div>
            <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Couleurs des étiquettes (une ligne par étiquette : nom couleur [couleur du texte])")}</span>
              <textarea className="field min-h-[5rem] font-mono text-sm" value={f.tcolors} onChange={(e) => set("tcolors")(e.target.value)} placeholder={tr("prod ff0000 ffffff\ndev 00aa00")} maxLength={4000} />
              <span className="block text-xs text-muted">{tr("Couleurs en hexadécimal à 6 chiffres, sans #. Vide = aucune couleur personnalisée.")}</span></label>
            {(d.tag_style.shape || d.tag_style.ordering || d.tag_style.case_sensitive || d.tag_style.color_map.length > 0) && <div><Button variant="ghost" disabled={busy !== null} onClick={() => save("options", { clear: ["tag_style"] })} className="!px-3 !py-1.5">{tr("Retirer le style des étiquettes")}</Button></div>}
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Étiquettes réservées (modifiables par Sys.Modify seulement)")}</span>
                <textarea className="field min-h-[4rem] font-mono text-sm" value={f.rtags} onChange={(e) => set("rtags")(e.target.value)} placeholder={tr("prod\nsecurite")} maxLength={8000} />
                <span className="block text-xs text-muted">{tr("Une par ligne (ou séparées par des virgules) : minuscules, chiffres, _ . + -. Vide = aucune.")}</span></label>
              <div className="space-y-3">
                <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Étiquettes : droits des utilisateurs")}</span>
                  <select className="field" value={f.uallow} onChange={(e) => set("uallow")(e.target.value)}><option value="">{tr("Défaut de Proxmox (free)")}</option>{Object.entries(USER_ALLOW).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                {f.uallow === "list" && <Field label={tr("Étiquettes permises")} value={f.ulist} maxLength={4000} onChange={(e) => set("ulist")(e.target.value)} hint={tr("Séparées par des virgules ou des espaces")} />}
              </div>
            </div>
            <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Texte de consentement (affiché à tous avant la connexion à Proxmox)")}</span>
              <textarea className="field min-h-[4rem] text-sm" value={f.consent} onChange={(e) => set("consent")(e.target.value)} maxLength={3000} />
              <span className="block text-xs text-muted">{tr("3000 caractères au plus. Vide = aucun texte. Le contenu n'est jamais copié dans le journal d'audit.")}</span></label>
            {insecureNew && <Notice kind="error">{tr("La migration non chiffrée envoie la mémoire des machines")}{" "}<b>{tr("en clair")}</b>{" "}{tr("sur le réseau. À réserver à un réseau privé de confiance.")}</Notice>}
            <div className="flex justify-end"><Button disabled={!changed || busy !== null} onClick={() => save("options", changes)}>{busy === "options" ? "…" : insecureNew ? tr("Appliquer (migration non chiffrée)") : tr("Appliquer")}</Button></div>
          </div>
        </section>
        {id !== null && <ClusterSettings connId={id} d={d} />}
        {id !== null && <WebauthnSettings connId={id} d={d} />}
        <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("Notes du datacenter")}</h2>
          <div className="panel space-y-3 p-5">
            <textarea className="field min-h-[10rem] font-mono text-sm" value={notes} onChange={(e) => setNotes(e.target.value)} aria-label={tr("Notes du datacenter")} maxLength={65536} />
            <div className="flex justify-end"><Button disabled={!notesChanged || busy !== null} onClick={() => save("notes", notes.trim() ? { description: notes } : { clear: ["description"] })}>{busy === "notes" ? "…" : tr("Enregistrer les notes")}</Button></div>
          </div>
        </section>
        {id !== null && <NotificationsSection connId={id} />}
        {id !== null && <MetricsServers connId={id} />}
        {id !== null && <ResourceMappings connId={id} />}
        {id !== null && <PoolsSection connId={id} />}
        {Object.keys(d.readonly).length > 0 && (
          <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("Non modifiable dans Kaji")}</h2>
            <dl className="panel p-4 text-sm">{Object.entries(d.readonly).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 border-b border-line/60 py-1.5 last:border-0"><dt className="text-muted">{LABELS[k] ?? k}</dt><dd className="max-w-[60%] break-all text-right font-mono text-xs">{v}</dd></div>))}</dl>
            <p className="text-xs text-muted">{tr("Réglages ou sous-clés que Kaji ne connaît pas (version plus récente de Proxmox) : ils sont gardés tels quels et se modifient dans l'interface de Proxmox.")}</p>
          </section>)}
      </>}
    </div>
  );
}
