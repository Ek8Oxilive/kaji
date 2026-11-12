import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ClusterMode, ClusterPreview, ClusterWriteResult } from "../lib/types/cluster";
import { Modal } from "./Modal";
import { Field, Notice } from "./ui";

import { tr } from "../lib/i18n";
const PHRASE = "COUPURE POSSIBLE";
const FP = /^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$/;

/**
 * Écriture du cluster : créer (nœud isolé), joindre (nœud isolé, mot de passe root du pair), retirer un nœud hors ligne.
 * Le serveur décide des verrous : aperçu (`dry_run`) d'abord, puis refus affichés (jamais levables), case « machines » et phrase `COUPURE POSSIBLE`.
 * Le mot de passe n'est gardé que dans cet état, envoyé une fois, effacé à la fermeture ; il n'apparaît dans aucune réponse.
 */
export function ClusterDialog({ connId, mode, onClose }: { connId: number; mode: ClusterMode; onClose: () => void }) {
  const qc = useQueryClient();
  const k = mode.kind;
  const [name, setName] = useState(""), [link0, setLink0] = useState(""), [hostname, setHostname] = useState(""), [fingerprint, setFingerprint] = useState(""), [password, setPassword] = useState(""), [retyped, setRetyped] = useState("");
  const [preview, setPreview] = useState<ClusterPreview | null>(null), [result, setResult] = useState<ClusterWriteResult | null>(null);
  const [ackGuests, setAckGuests] = useState(false), [ackCut, setAckCut] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  useEffect(() => { setPreview(null); setAckGuests(false); setAckCut(false); setTyped(""); setErr(null); }, [name, link0, hostname, fingerprint, password, retyped]);
  useEffect(() => () => setPassword(""), []);

  const base = `/api/connections/${connId}/cluster`;
  const links = link0.trim() ? [{ link: 0, address: link0.trim() }] : [];
  const request = (extra: Record<string, unknown>) => {
    if (k === "remove") {
      const q = new URLSearchParams(Object.entries({ name: retyped, ...extra } as Record<string, unknown>).filter(([, v]) => v !== undefined && v !== false && v !== "").map(([a, v]) => [a, String(v)]));
      return { path: `${base}/nodes/${encodeURIComponent(mode.node)}?${q}`, init: { method: "DELETE" } };
    }
    if (k === "create") return { path: `${base}/create`, init: { method: "POST", body: { clustername: name, links, ...extra } } };
    return { path: `${base}/join`, init: { method: "POST", body: { hostname: hostname.trim(), fingerprint: fingerprint.trim(), password, links, ...extra } } };
  };
  const look = async () => {
    setErr(null);
    try { const r = request({ dry_run: true }); setPreview(await api<ClusterPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); }
  };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const r = request({ confirm: true, ...(ackGuests ? { acknowledge_guests: true } : {}), ...(ackCut ? { acknowledge_cut_access: true, type_name: typed } : {}) });
      setResult(await api<ClusterWriteResult>(r.path, r.init));
      setPassword("");
      await qc.invalidateQueries({ queryKey: ["cluster-config", connId] });
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };

  const blocked = !!preview?.locks.blockers.length, cut = !!preview?.locks.cut.length, live = !!preview?.locks.live.length;
  const ready = !!preview && !blocked && (!cut || (ackCut && typed === PHRASE)) && (!live || ackGuests);
  const readyToLook = k === "create" ? name !== "" : k === "join" ? hostname.trim() !== "" && FP.test(fingerprint.trim()) && password !== "" : retyped === mode.node;
  const title = k === "create" ? tr("Créer un cluster") : k === "join" ? tr("Joindre un cluster") : tr("Retirer le nœud {node}", { node: mode.kind === "remove" ? mode.node : "" });

  if (result) return (
    <Modal title={tr("Fait")} onClose={onClose} onSubmit={onClose} submitLabel={tr("Fermer")} canSubmit>
      <Notice kind="ok">{k === "create" ? tr("Création du cluster « {name} » demandée au nœud {node}. Recharge la page dans quelques secondes.", { name, node: result.node ?? "?" })
        : k === "join" ? tr("Jonction demandée au nœud {node} vers {via}. Ce nœud redémarre ses services et sa configuration est remplacée : la connexion de Kaji à ce nœud ne marchera plus. Ajoute une connexion au cluster rejoint.", { node: result.joining ?? "?", via: result.via ?? "?" })
        : tr("Nœud {node} retiré de la configuration du cluster. Il ne doit JAMAIS être rallumé avec son ancienne configuration : réinstalle-le avant de le réutiliser.", { node: result.removed ?? "?" })}</Notice>
      {k === "remove" && (result.guests?.length ?? 0) > 0 && <Notice kind="error">{tr("Configurations de machines restées sur le nœud retiré : {p}.", { p: result.guests?.join(", ") })}</Notice>}
    </Modal>);

  return (
    <Modal title={title} subtitle={tr("Rien n'est écrit sans aperçu : le serveur dit quels verrous s'appliquent.")} onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={k === "remove" ? tr("Retirer le nœud") : k === "join" ? tr("Joindre") : tr("Créer")} danger busy={busy} error={err} canSubmit={ready} wide>
      {k === "create" && <>
        <Notice kind="error">{tr("À faire sur un nœud ISOLÉ (la connexion active doit pointer sur lui). Proxmox refuse sur un nœud déjà en cluster.")}</Notice>
        <Field label={tr("Nom du cluster")} value={name} maxLength={15} onChange={(e) => setName(e.target.value)} hint={tr("15 caractères au plus : lettres, chiffres, tiret")} />
        <Field label={tr("Adresse du lien 0 (facultatif)")} value={link0} maxLength={45} onChange={(e) => setLink0(e.target.value)} hint={tr("Adresse IP de ce nœud sur le réseau du cluster ; vide = son adresse locale")} />
      </>}
      {k === "join" && <>
        <Notice kind="error">{tr("À faire sur un nœud ISOLÉ et vide de machines (la connexion active doit pointer sur lui). Sa configuration sera REMPLACÉE par celle du cluster.")}</Notice>
        <Field label={tr("Adresse d'un nœud du cluster à rejoindre")} value={hostname} maxLength={253} onChange={(e) => setHostname(e.target.value)} hint={tr("Voir « Information de jonction » sur la page Cluster du cluster à rejoindre")} />
        <Field label={tr("Empreinte du certificat de ce nœud")} value={fingerprint} maxLength={95} onChange={(e) => setFingerprint(e.target.value)} hint={tr("32 octets en hexadécimal séparés par « : »")} />
        <Field label={tr("Mot de passe root du nœud contacté")} type="password" autoComplete="off" value={password} maxLength={128} onChange={(e) => setPassword(e.target.value)} hint={tr("Envoyé une seule fois à Proxmox, jamais gardé ni affiché ni journalisé")} />
        <Field label={tr("Adresse du lien 0 (facultatif)")} value={link0} maxLength={45} onChange={(e) => setLink0(e.target.value)} hint={tr("Adresse IP de ce nœud sur le réseau du cluster ; vide = celle de son nom d'hôte")} />
      </>}
      {k === "remove" && <>
        <Notice kind="error">{tr("Le nœud doit être ÉTEINT pour de bon et ne jamais revenir avec son ancienne configuration. Les machines qui y sont configurées ne démarreront plus tant qu'elles ne sont pas déplacées.")}</Notice>
        <Field label={tr("Retape le nom du nœud ({node}) pour confirmer", { node: mode.node })} value={retyped} autoComplete="off" onChange={(e) => setRetyped(e.target.value)} />
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!readyToLook} onClick={look}>{tr("Aperçu des verrous")}</button>
      {preview && (
        <div className="space-y-3 text-sm">
          {preview.node && <p className="text-muted">{tr("Nœud concerné :")}{" "}<code>{preview.node}</code></p>}
          {blocked && <Notice kind="error"><b>{tr("Refusé")}</b> : {preview.locks.blockers.join(" ; ")}.</Notice>}
          {!blocked && !cut && !live && <Notice kind="ok">{tr("Aucun verrou : rien d'autre ne se passe que l'opération demandée.")}</Notice>}
          {!blocked && live && <Notice kind="error">{preview.locks.live.join(" ; ")}.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ackGuests} onChange={(e) => setAckGuests(e.target.checked)} /><span>{tr("Je comprends que ces machines ne démarreront plus depuis ce nœud")}</span></label></Notice>}
          {!blocked && cut && <Notice kind="error"><b>{tr("Coupure possible")}</b> : {preview.locks.cut.join(" ; ")}.
            <label className="mt-2 flex gap-2"><input type="checkbox" checked={ackCut} onChange={(e) => setAckCut(e.target.checked)} /><span>{tr("Je comprends que l'accès à Proxmox ou à Kaji peut être coupé")}</span></label>
            <label className="mt-2 block text-xs">{tr("Retape")}{" "}<code>{PHRASE}</code><input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label></Notice>}
        </div>)}
    </Modal>
  );
}
