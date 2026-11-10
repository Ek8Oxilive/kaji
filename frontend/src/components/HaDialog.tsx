import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Guest, NodeInfo } from "../lib/api";
import type { HaIgnored, HaMode, HaMoveResult, HaPreview, HaResource } from "../lib/types/ha";
import { Modal } from "./Modal";
import { Field, Notice } from "./ui";

const PHRASE = "COUPURE POSSIBLE";
const ignoredText = (list: HaIgnored[], target: string) =>
  `La HA va ignorer cette demande : ${list.map((i) => `la règle stricte « ${i.rule} » (${i.resources.join(", ")}) n'autorise que ${i.nodes.join(", ") || "aucun nœud"}`).join(" ; ")}. Rien ne bougera vers ${target || "ce nœud"} tant que cette règle existe : modifie-la ou désactive-la d'abord.`;
const STATES = ["", "started", "stopped", "enabled", "disabled", "ignored"];
type Tri = "" | "yes" | "no";
const tri = (t: Tri) => (t === "yes" ? true : t === "no" ? false : undefined);
const triOf = (v: boolean | null | undefined): Tri => (v === true ? "yes" : v === false ? "no" : "");

/**
 * Écriture HA : ressources, règles, migrer / relocaliser. Le serveur décide des verrous : on demande d'abord un aperçu (`dry_run`), puis on affiche ce qu'il exige
 * (case « effet immédiat », ou case + phrase `COUPURE POSSIBLE` quand le cluster a moins de 3 nœuds). Une machine protégée est refusée par le serveur, même confirmée.
 */
export function HaDialog({ connId, mode, onClose }: { connId: number; mode: HaMode; onClose: () => void }) {
  const qc = useQueryClient();
  const k = mode.kind;
  const editingRes = k === "resource-edit" ? mode.resource : null, editingRule = k === "rule-edit" ? mode.rule : null;
  const guests = useQuery({ queryKey: ["guests", connId], queryFn: () => api<Guest[]>(`/api/connections/${connId}/guests`), enabled: k === "resource-new" });
  const nodes = useQuery({ queryKey: ["nodes", connId], queryFn: () => api<NodeInfo[]>(`/api/connections/${connId}/nodes`), enabled: ["migrate", "relocate", "rule-new", "rule-edit"].includes(k) });
  const haRes = useQuery({ queryKey: ["ha", connId, "resources"], queryFn: () => api<HaResource[]>(`/api/connections/${connId}/ha/resources`), enabled: k === "resource-new" || k === "rule-new" || k === "rule-edit" });

  // Ressource
  const [sid, setSid] = useState(""), [state, setState] = useState(editingRes?.state ?? ""), [maxRestart, setMaxRestart] = useState(editingRes?.max_restart?.toString() ?? ""),
    [maxRelocate, setMaxRelocate] = useState(editingRes?.max_relocate?.toString() ?? ""), [failback, setFailback] = useState<Tri>(triOf(editingRes?.failback)), [comment, setComment] = useState(editingRes?.comment ?? editingRule?.comment ?? "");
  // Déplacement
  const [target, setTarget] = useState("");
  // Règle
  const [ruleName, setRuleName] = useState(""), [rtype, setRtype] = useState<"node-affinity" | "resource-affinity">(editingRule?.type === "resource-affinity" ? "resource-affinity" : "node-affinity"),
    [rRes, setRRes] = useState<string[]>(editingRule?.resources ?? []), [nodeSel, setNodeSel] = useState<Record<string, string>>(() => Object.fromEntries((editingRule?.nodes ?? []).map((n) => [n.node, n.priority !== null ? String(n.priority) : ""]))),
    [strict, setStrict] = useState<Tri>(triOf(editingRule?.strict)), [affinity, setAffinity] = useState(editingRule?.affinity ?? ""), [disable, setDisable] = useState<Tri>(triOf(editingRule?.disable));

  const [preview, setPreview] = useState<HaPreview | null>(null), [moved, setMoved] = useState<HaMoveResult | null>(null);
  const [ackLive, setAckLive] = useState(false), [ackCut, setAckCut] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [done, setDone] = useState(false), [err, setErr] = useState<string | null>(null);
  useEffect(() => { setPreview(null); setAckLive(false); setAckCut(false); setTyped(""); setErr(null); }, [sid, state, maxRestart, maxRelocate, failback, comment, target, ruleName, rtype, rRes, nodeSel, strict, affinity, disable]);

  const base = `/api/connections/${connId}/ha`;
  const target_ = k === "resource-edit" || k === "resource-delete" || k === "migrate" || k === "relocate" ? (mode as { resource: HaResource }).resource.sid : editingRule?.rule ?? (k === "rule-delete" ? mode.rule.rule : "");
  const parseNodes = () => Object.entries(nodeSel).map(([node, p]) => (p !== "" ? { node, priority: Number(p) } : { node }));
  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));

  /** Requête de l'action choisie ; `extra` porte dry_run / confirm / déverrouillages. */
  const request = (extra: Record<string, unknown>) => {
    if (k === "resource-delete" || k === "rule-delete") {
      const q = new URLSearchParams(Object.entries(extra).filter(([, v]) => v !== undefined && v !== false).map(([a, v]) => [a, String(v)]));
      return { path: `${base}/${k === "rule-delete" ? "rules" : "resources"}/${encodeURIComponent(target_)}?${q}`, init: { method: "DELETE" } };
    }
    if (k === "migrate" || k === "relocate") return { path: `${base}/resources/${encodeURIComponent(target_)}/${k}`, init: { method: "POST", body: { node: target, ...extra } } };
    if (k === "resource-new" || k === "resource-edit") {
      const clear: string[] = [];
      const f: Record<string, unknown> = {};
      const put = (name: string, v: unknown, was: unknown) => { if (v !== undefined && v !== "") f[name] = v; else if (editingRes && was !== null && was !== undefined && (v === undefined || v === "")) clear.push(name); };
      if (state) f.state = state;
      put("max_restart", num(maxRestart), editingRes?.max_restart); put("max_relocate", num(maxRelocate), editingRes?.max_relocate);
      put("failback", tri(failback), editingRes?.failback); put("comment", comment.trim() || undefined, editingRes?.comment);
      return k === "resource-new" ? { path: `${base}/resources`, init: { method: "POST", body: { sid, ...f, ...extra } } }
        : { path: `${base}/resources/${encodeURIComponent(target_)}`, init: { method: "PUT", body: { ...f, ...(clear.length ? { clear } : {}), ...extra } } };
    }
    const f: Record<string, unknown> = { type: rtype };
    const clear: string[] = [];
    f.resources = rRes;
    if (rtype === "node-affinity") { f.nodes = parseNodes(); if (tri(strict) !== undefined) f.strict = tri(strict); else if (editingRule?.strict != null && strict === "") clear.push("strict"); }
    if (affinity) f.affinity = affinity;
    if (tri(disable) !== undefined) f.disable = tri(disable); else if (editingRule?.disable != null && disable === "") clear.push("disable");
    if (comment.trim()) f.comment = comment.trim(); else if (editingRule?.comment) clear.push("comment");
    return k === "rule-new" ? { path: `${base}/rules`, init: { method: "POST", body: { rule: ruleName, ...f, ...extra } } }
      : { path: `${base}/rules/${encodeURIComponent(target_)}`, init: { method: "PUT", body: { ...f, ...(clear.length ? { clear } : {}), ...extra } } };
  };

  const look = async () => {
    setErr(null);
    try { const r = request({ dry_run: true }); setPreview(await api<HaPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); }
  };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const r = request({ confirm: true, ...(ackLive ? { acknowledge_live: true } : {}), ...(ackCut ? { acknowledge_cut_access: true, type_name: typed } : {}) });
      const out = await api<HaMoveResult | Record<string, unknown>>(r.path, r.init);
      if (k === "migrate" || k === "relocate") setMoved(out as HaMoveResult);
      await qc.invalidateQueries({ queryKey: ["ha", connId] });
      setDone(true);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };

  const cut = !!preview?.locks.cut.length, live = !!preview?.locks.live.length;
  const ready = !!preview && (!cut || (ackCut && typed === PHRASE)) && (!live || cut || ackLive);
  const inHa = useMemo(() => new Set((haRes.data ?? []).map((r) => r.sid)), [haRes.data]);
  const free = (guests.data ?? []).filter((g) => !g.template && g.vmid !== null && !inHa.has(`${g.type === "lxc" ? "ct" : "vm"}:${g.vmid}`));
  const title = { "resource-new": "Ajouter une machine à la HA", "resource-edit": `Modifier ${target_}`, "resource-delete": `Retirer ${target_} de la HA`, migrate: `Migrer ${target_}`, relocate: `Relocaliser ${target_}`,
    "rule-new": "Nouvelle règle HA", "rule-edit": `Modifier la règle ${target_}`, "rule-delete": `Supprimer la règle ${target_}` }[k];
  const readyToLook = k === "resource-new" ? sid !== "" : k === "migrate" || k === "relocate" ? target !== "" : k === "rule-new" ? ruleName !== "" && rRes.length > 0 && (rtype === "resource-affinity" || Object.keys(nodeSel).length > 0) : true;
  const select = (label: string, v: string, set: (s: string) => void, opts: [string, string][]) => (
    <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span><select className="field" value={v} onChange={(e) => set(e.target.value)}>{opts.map(([val, text]) => <option key={val} value={val}>{text}</option>)}</select></label>);
  const triSel = (label: string, v: Tri, set: (t: Tri) => void) => select(label, v, (s) => set(s as Tri), [["", "Défaut de Proxmox"], ["yes", "Oui"], ["no", "Non"]]);

  if (done) return (
    <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit>
      <Notice kind="ok">{k === "migrate" || k === "relocate" ? `Demande envoyée à la HA : ${moved?.from ?? "?"} → ${moved?.requested ?? target}. Le déplacement est asynchrone (suivre l'état HA).` : "Enregistré, relu chez Proxmox."}</Notice>
      {moved && moved.comigrated.length > 0 && <Notice kind="ok">Déplacées avec elle (affinité positive) : {moved.comigrated.join(", ")}.</Notice>}
      {moved && (moved.ignored?.length ?? 0) > 0 && <Notice kind="error">{ignoredText(moved.ignored ?? [], moved.requested)}</Notice>}
      {moved && moved.blocking.length > 0 && <Notice kind="error">Bloquées : {moved.blocking.map((b) => `${b.sid}${b.cause ? ` (${b.cause})` : ""}`).join(", ")}.</Notice>}
    </Modal>);

  return (
    <Modal title={title} subtitle="Rien n'est écrit sans aperçu : le serveur dit quels verrous s'appliquent." onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={k === "resource-delete" || k === "rule-delete" ? "Supprimer" : "Appliquer"} danger={cut || live || k === "resource-delete" || k === "rule-delete"} busy={busy} error={err} canSubmit={ready} wide>
      {k === "resource-new" && select("Machine", sid, setSid, [["", guests.isLoading ? "Chargement…" : "Choisir une machine"], ...free.map((g) => [`${g.type === "lxc" ? "ct" : "vm"}:${g.vmid}`, `${g.type === "lxc" ? "ct" : "vm"}:${g.vmid} · ${g.name ?? ""} (${g.node})`] as [string, string])])}
      {(k === "resource-new" || k === "resource-edit") && <>
        {select("État demandé", state, setState, STATES.map((s) => [s, s || (editingRes ? "Ne pas changer" : "Défaut (started)")]))}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Redémarrages max." type="number" min={0} max={10} value={maxRestart} onChange={(e) => setMaxRestart(e.target.value)} hint="Vide = défaut de Proxmox (retire le réglage en modification)" />
          <Field label="Déplacements max." type="number" min={0} max={10} value={maxRelocate} onChange={(e) => setMaxRelocate(e.target.value)} />
        </div>
        {triSel("Retour sur le nœud préféré (failback)", failback, setFailback)}
        <Field label="Commentaire" value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} hint="ASCII uniquement : Proxmox altère les accents des commentaires HA" />
      </>}
      {(k === "migrate" || k === "relocate") && select("Nœud cible", target, setTarget, [["", "Choisir un nœud"], ...(nodes.data ?? []).map((n) => [n.node, n.node] as [string, string])])}
      {k === "resource-delete" && <Notice kind="error">La machine n'est pas touchée : seule sa gestion par la HA s'arrête. Refusé tant qu'une règle la cite.</Notice>}
      {k === "rule-delete" && <Notice kind="error">Les machines ne sont pas touchées : la règle disparaît, la HA les place alors sans cette contrainte.</Notice>}
      {(k === "rule-new" || k === "rule-edit") && <>
        {k === "rule-new" && <Field label="Nom de la règle" value={ruleName} maxLength={64} onChange={(e) => setRuleName(e.target.value)} hint="Lettre puis lettres, chiffres, _ ou -" />}
        {k === "rule-new" ? select("Type", rtype, (s) => setRtype(s as typeof rtype), [["node-affinity", "node-affinity : placer sur des nœuds"], ["resource-affinity", "resource-affinity : garder ensemble ou séparées"]])
          : <p className="text-sm text-muted">Type : <code>{rtype}</code> (non modifiable)</p>}
        <fieldset className="space-y-1 text-sm"><legend className="text-muted">Machines de la règle (déjà gérées par la HA)</legend>
          {(haRes.data ?? []).length === 0 && <p className="text-muted">Aucune ressource HA : ajoute d'abord une machine à la HA.</p>}
          {(haRes.data ?? []).map((r) => (<label key={r.sid} className="mr-4 inline-flex items-center gap-2"><input type="checkbox" checked={rRes.includes(r.sid)} onChange={(e) => setRRes(e.target.checked ? [...rRes, r.sid] : rRes.filter((x) => x !== r.sid))} /><span className="font-mono">{r.sid}</span></label>))}
        </fieldset>
        {rtype === "node-affinity" ? <>
          <fieldset className="space-y-1.5 text-sm"><legend className="text-muted">Nœuds (priorité facultative : le plus grand nombre est préféré)</legend>
            {(nodes.data ?? []).map((n) => (
              <div key={n.node} className="flex items-center gap-3">
                <label className="flex w-40 items-center gap-2"><input type="checkbox" checked={n.node in nodeSel} onChange={(e) => setNodeSel((cur) => { const c = { ...cur }; if (e.target.checked) c[n.node] = ""; else delete c[n.node]; return c; })} /><span className="font-mono">{n.node}</span></label>
                <input className="field max-w-[8rem]" type="number" min={0} max={1000} placeholder="priorité" aria-label={`Priorité de ${n.node}`} disabled={!(n.node in nodeSel)} value={nodeSel[n.node] ?? ""} onChange={(e) => setNodeSel((cur) => ({ ...cur, [n.node]: e.target.value }))} />
              </div>))}
          </fieldset>
          {triSel("Stricte (aucun autre nœud autorisé)", strict, setStrict)}
        </> : select("Affinité", affinity, setAffinity, [["", "Choisir"], ["positive", "positive : sur le même nœud"], ["negative", "négative : sur des nœuds différents"]])}
        {triSel("Désactivée", disable, setDisable)}
        <Field label="Commentaire" value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} hint="ASCII uniquement : Proxmox altère les accents des commentaires HA" />
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!readyToLook} onClick={look}>Aperçu des verrous</button>
      {preview && (
        <div className="space-y-3 text-sm">
          {(preview.comigrated?.length ?? 0) > 0 && <Notice kind="error">Cette migration entraîne aussi (affinité positive) : {preview.comigrated?.join(", ")}.</Notice>}
          {(preview.ignored?.length ?? 0) > 0 && <Notice kind="error">{ignoredText(preview.ignored ?? [], target)}</Notice>}
          {preview.locks.inert && <Notice kind="ok">Aucun verrou : rien ne bouge tout de suite.</Notice>}
          {live && !cut && <Notice kind="error">{preview.locks.live.join(" ; ")}.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ackLive} onChange={(e) => setAckLive(e.target.checked)} /><span>Je comprends que cela s'applique tout de suite</span></label></Notice>}
          {cut && <Notice kind="error"><b>Coupure possible</b> : {preview.locks.cut.join(" ; ")}.
            <label className="mt-2 flex gap-2"><input type="checkbox" checked={ackCut} onChange={(e) => setAckCut(e.target.checked)} /><span>Je comprends qu'un nœud peut redémarrer tout seul et couper l'accès à Proxmox et à Kaji</span></label>
            <label className="mt-2 block text-xs">Retape <code>{PHRASE}</code><input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label></Notice>}
        </div>)}
    </Modal>
  );
}
