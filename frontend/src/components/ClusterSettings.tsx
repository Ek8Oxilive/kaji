import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { BW_KEYS, BW_LABELS, CRS_MODES, FENCING_LABELS, FENCING_MODES, FENCING_PHRASE, SHUTDOWN_LABELS, SHUTDOWN_POLICIES, type DatacenterOptions, type DatacenterPreview } from "../lib/types/datacenter";
import { Button, Field, Notice } from "./ui";

const init = (d: DatacenterOptions) => ({
  ha: d.ha.shutdown_policy ?? "", fencing: d.fencing ?? "", crsha: d.crs.ha ?? "", reb: !!d.crs.ha_rebalance_on_start,
  bw: Object.fromEntries(BW_KEYS.map((k) => [k, d.bwlimit[k]?.toString() ?? ""])) as Record<string, string>,
  rtype: d.replication.type ?? "", rnet: d.replication.network ?? "",
});

/** Datacenter → Options : haute disponibilité (arrêt d'un nœud), fencing, ordonnancement des ressources (CRS), débits et réplication (`docs/api/datacenter.md`).
 *  « Appliquer » demande d'abord l'aperçu (`dry_run`) : sans verrou on écrit tout de suite, sinon on affiche les risques et on demande la confirmation décidée par le serveur. */
export function ClusterSettings({ connId, d }: { connId: number; d: DatacenterOptions }) {
  const qc = useQueryClient();
  const [f, setF] = useState(init(d));
  useEffect(() => setF(init(d)), [d]);
  const [pending, setPending] = useState<{ body: Record<string, unknown>; preview: DatacenterPreview } | null>(null);
  const [confirm, setConfirm] = useState(false), [ack, setAck] = useState(false), [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);

  /** Corps de la requête : seulement ce qui a changé ; un champ vidé qui avait une valeur est retiré. */
  const diff = () => {
    const body: Record<string, unknown> = {}, clear: string[] = [];
    if (f.ha !== (d.ha.shutdown_policy ?? "")) { if (f.ha) body.ha = { shutdown_policy: f.ha }; else clear.push("ha"); }
    if (f.fencing !== (d.fencing ?? "")) { if (f.fencing) body.fencing = f.fencing; else clear.push("fencing"); }
    const crs: Record<string, unknown> = {};
    if (f.crsha !== (d.crs.ha ?? "") && f.crsha) crs.ha = f.crsha;
    if (f.reb !== !!d.crs.ha_rebalance_on_start) crs.ha_rebalance_on_start = f.reb;
    if (Object.keys(crs).length) body.crs = crs;
    const bw: Record<string, unknown> = {}, remove: string[] = [];
    for (const k of BW_KEYS) {
      if (f.bw[k] === (d.bwlimit[k]?.toString() ?? "")) continue;
      if (f.bw[k].trim() !== "") bw[k] = Number(f.bw[k]); else remove.push(k);
    }
    if (remove.length) bw.remove = remove;
    if (Object.keys(bw).length) body.bwlimit = bw;
    const rep: Record<string, unknown> = {};
    if (f.rtype !== (d.replication.type ?? "") && f.rtype) rep.type = f.rtype;
    if (f.rnet !== (d.replication.network ?? "")) rep.network = f.rnet;
    if (Object.keys(rep).length) body.replication = rep;
    return { ...body, ...(clear.length ? { clear } : {}) };
  };
  const body = diff(), changed = Object.keys(body).length > 0;
  const url = `/api/connections/${connId}/datacenter/options`;

  const send = async (b: Record<string, unknown>, extra: Record<string, unknown>) => {
    await api(url, { method: "PUT", body: { ...b, digest: d.digest, ...extra } });
    await qc.invalidateQueries({ queryKey: ["datacenter", connId] });
    setPending(null);
    setOk(tr("Réglages enregistrés, relus chez Proxmox."));
  };
  /** Aperçu (`dry_run`) puis, sans verrou, écriture immédiate ; avec verrou, panneau de confirmation. */
  const apply = async (b: Record<string, unknown>) => {
    setBusy(true); setErr(null); setOk(null); setPending(null);
    try {
      const preview = await api<DatacenterPreview>(url, { method: "PUT", body: { ...b, digest: d.digest, dry_run: true } });
      const l = preview.locks;
      if (l.ha || l.replication_insecure || l.fencing_experimental) { setPending({ body: b, preview }); setConfirm(false); setAck(false); setPhrase(""); }
      else await send(b, {});
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const confirmApply = async () => {
    if (!pending) return;
    setBusy(true); setErr(null);
    try { await send(pending.body, { confirm: true, ...(pending.preview.locks.fencing_experimental ? { acknowledge_cut_access: true, type_name: phrase } : {}) }); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const set = (k: "ha" | "fencing" | "crsha" | "rtype" | "rnet") => (v: string) => { setF((c) => ({ ...c, [k]: v })); setPending(null); };
  const setBw = (k: string) => (v: string) => { setF((c) => ({ ...c, bw: { ...c.bw, [k]: v } })); setPending(null); };
  const lk = pending?.preview.locks;
  const needPhrase = !!lk?.fencing_experimental;
  const canConfirm = confirm && (!needPhrase || (ack && phrase === FENCING_PHRASE));

  return (
    <section className="space-y-3"><h2 className="text-lg font-semibold">{tr("Haute disponibilité, ordonnancement et débits")}</h2>
      <div className="panel space-y-4 p-5">
        {err && <Notice kind="error">{err}</Notice>}
        {ok && <Notice kind="ok">{ok}</Notice>}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("HA : à l'arrêt ou au redémarrage d'un nœud")}</span>
            <select className="field" value={f.ha} onChange={(e) => set("ha")(e.target.value)}><option value="">{tr("Défaut de Proxmox (conditional)")}</option>{SHUTDOWN_POLICIES.map((o) => <option key={o} value={o}>{SHUTDOWN_LABELS[o]}</option>)}</select></label>
          <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("HA : mode de fencing")}</span>
            <select className="field" value={f.fencing} onChange={(e) => set("fencing")(e.target.value)}><option value="">{tr("Défaut de Proxmox (watchdog)")}</option>{FENCING_MODES.map((o) => <option key={o} value={o}>{FENCING_LABELS[o]}</option>)}</select></label>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Ordonnancement des ressources (CRS) : choix du nœud")}</span>
            <select className="field" value={f.crsha} onChange={(e) => set("crsha")(e.target.value)}>{!d.crs.ha && <option value="">{tr("Défaut de Proxmox (basic)")}</option>}{CRS_MODES.map((o) => <option key={o} value={o}>{o}</option>)}</select></label>
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={f.reb} onChange={(e) => { setF((c) => ({ ...c, reb: e.target.checked })); setPending(null); }} /><span>{tr("Choisir le nœud au démarrage d'un service HA arrêté (ha-rebalance-on-start)")}</span></label>
        </div>
        {(d.crs.ha || d.crs.ha_rebalance_on_start !== null) && <div><Button variant="ghost" disabled={busy} onClick={() => apply({ clear: ["crs"] })} className="!px-3 !py-1.5">{tr("Retirer l'ordonnancement")}</Button></div>}
        <div>
          <div className="mb-1.5 text-sm text-muted">{tr("Limites de débit, en Kio/s (vide = pas de limite réglée)")}</div>
          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {BW_KEYS.map((k) => <Field key={k} label={BW_LABELS[k]} type="number" min={0} max={1000000000} value={f.bw[k]} onChange={(e) => setBw(k)(e.target.value)} />)}
          </div>
          <p className="mt-1 text-xs text-muted">{tr("Entiers de 0 à 1 000 000 000. Proxmox applique ces limites à toutes les opérations du cluster concernées.")}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("Réplication : type de trafic")}</span>
            <select className="field" value={f.rtype} onChange={(e) => set("rtype")(e.target.value)}>{!d.replication.type && <option value="">{tr("Défaut de Proxmox (sécurisé)")}</option>}<option value="secure">{tr("secure : tunnel SSH chiffré")}</option><option value="insecure">{tr("insecure : non chiffré")}</option></select></label>
          <Field label={tr("Réplication : réseau dédié (CIDR)")} value={f.rnet} maxLength={43} placeholder="10.0.0.0/24" onChange={(e) => set("rnet")(e.target.value)} hint={tr("Vide = réseau par défaut")} />
        </div>
        {pending && lk && (
          <div className="space-y-3 rounded-lg border border-line p-4">
            <Notice kind="error">
              <ul className="list-disc space-y-1 pl-5">
                {lk.ha && <li>{tr("Ce réglage change ce que fait la haute disponibilité à l'arrêt d'un nœud, à la reprise après une panne ou au placement des machines.")}</li>}
                {lk.replication_insecure && <li>{tr("La réplication non chiffrée envoie les disques des machines en clair sur le réseau. À réserver à un réseau privé de confiance.")}</li>}
                {lk.fencing_experimental && <li>{tr("Le fencing matériel est expérimental dans Proxmox : sans appareils configurés dans /etc/pve/ha/fence.cfg, la HA ne reprendra plus les machines d'un nœud tombé.")}</li>}
              </ul>
            </Notice>
            <dl className="text-xs">{Object.entries(pending.preview.params).map(([k, v]) => <div key={k} className="flex justify-between gap-4 py-0.5"><dt className="text-muted">{k}</dt><dd className="break-all font-mono">{String(v)}</dd></div>)}
              {pending.preview.remove.map((k) => <div key={k} className="flex justify-between gap-4 py-0.5"><dt className="text-muted">{k}</dt><dd className="font-mono">{tr("retiré")}</dd></div>)}</dl>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /><span>{tr("Je comprends et je confirme")}</span></label>
            {needPhrase && <>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{tr("J'accepte le risque de coupure de la reprise HA")}</span></label>
              <Field label={tr("Retape {phrase} pour confirmer", { phrase: FENCING_PHRASE })} value={phrase} maxLength={40} onChange={(e) => setPhrase(e.target.value)} />
            </>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" disabled={busy} onClick={() => setPending(null)}>{tr("Annuler")}</Button>
              <Button disabled={!canConfirm || busy} onClick={confirmApply}>{busy ? "…" : tr("Confirmer et appliquer")}</Button>
            </div>
          </div>
        )}
        {!pending && <div className="flex justify-end"><Button disabled={!changed || busy} onClick={() => apply(body)}>{busy ? "…" : tr("Appliquer")}</Button></div>}
      </div>
    </section>
  );
}
