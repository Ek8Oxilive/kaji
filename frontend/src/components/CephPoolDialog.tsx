import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { confirmReasons } from "../lib/confirmRisk";
import { runTask } from "../lib/tasks";
import type { Ceph, CephPool, CephRules, PoolApplication, PoolAutoscale, PoolCreateBody, PoolFields, PoolPatchBody, PoolWriteResult } from "../lib/types/ceph";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Field } from "./ui";

const warn = "rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn";
const PG = Array.from({ length: 16 }, (_, i) => 2 ** i);                      // 1 à 32768 : seules les puissances de 2
const AUTOSCALE: { id: PoolAutoscale; label: string }[] = [
  { id: "warn", label: "Avertir si le nombre de groupes n'est pas optimal (défaut)" }, { id: "on", label: "Ajuster automatiquement" }, { id: "off", label: "Désactivé" },
];
const APPLICATIONS: PoolApplication[] = ["rbd", "cephfs", "rgw"];

/** Bandeau affiché au-dessus de toute action d'écriture Ceph : la fonction n'a jamais tourné sur un vrai Ceph. */
export function UnvalidatedBanner() {
  return (
    <div className={warn} role="note">
      <p className="font-medium">Écriture Ceph : fonction non validée en réel</p>
      <p className="mt-1 text-xs">Aucun Ceph n'est disponible pour l'essayer : elle a été testée avec un faux Proxmox uniquement. Évite de l'utiliser sur un Ceph en production tant qu'elle n'a pas été validée sur un Ceph jetable.</p>
    </div>
  );
}

/** Création (`pool` absent) ou modification d'un pool. Les confirmations viennent du SERVEUR : on envoie sans `confirm`, on montre ses raisons, puis on renvoie avec `confirm: true`. */
export function CephPoolDialog({ connId, pool, onClose }: { connId: number; pool: CephPool | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const edit = pool !== null;
  const erasure = pool?.type === "erasure";
  const rules = useQuery({ queryKey: ["ceph", connId, "rules"], queryFn: () => api<Ceph<CephRules>>(`/api/connections/${connId}/ceph/rules`), staleTime: 30_000, retry: false });

  const [name, setName] = useState("");
  const [size, setSize] = useState(String(pool?.size ?? 3));
  const [minSize, setMinSize] = useState(String(pool?.min_size ?? 2));
  const [pgNum, setPgNum] = useState(String(pool?.pg_num ?? 128));
  const [autoscale, setAutoscale] = useState<PoolAutoscale>((pool?.autoscale as PoolAutoscale) ?? "warn");
  const [application, setApplication] = useState<PoolApplication>("rbd");
  const [crush, setCrush] = useState(pool?.crush_rule ?? "");
  const [addStorage, setAddStorage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [risk, setRisk] = useState<string[] | null>(null);

  const sz = Number(size), ms = Number(minSize);
  const copiesOk = Number.isInteger(sz) && sz >= 2 && sz <= 7 && Number.isInteger(ms) && ms >= 2 && ms <= 7 && ms <= sz;
  const nameOk = edit || /^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$/.test(name);
  const ruleNames = rules.data?.installed ? rules.data.rules.map((r) => r.name) : [];

  /** Création : tout. Modification : seulement ce qui change (le serveur ignore de toute façon ce qui est identique). */
  const body = useMemo((): PoolCreateBody | PoolPatchBody | null => {
    if (!copiesOk || !nameOk) return null;
    if (!edit) return { name, size: sz, min_size: ms, pg_num: Number(pgNum), autoscale, application, ...(crush ? { crush_rule: crush } : {}), ...(application === "rbd" && addStorage ? { add_storage: true } : {}) };
    const p: PoolFields = {};
    if (!erasure && sz !== pool!.size) p.size = sz;
    if (ms !== pool!.min_size) p.min_size = ms;
    if (Number(pgNum) !== pool!.pg_num) p.pg_num = Number(pgNum);
    if (autoscale !== pool!.autoscale) p.autoscale = autoscale;
    if (!erasure && crush && crush !== pool!.crush_rule) p.crush_rule = crush;
    return Object.keys(p).length ? p : null;
  }, [copiesOk, nameOk, edit, erasure, pool, name, sz, ms, pgNum, autoscale, application, crush, addStorage]);

  // Une confirmation ne vaut que pour la demande qui l'a provoquée : si un champ change, les raisons ne sont plus celles-là.
  const bodyKey = JSON.stringify(body);
  useEffect(() => { setRisk(null); }, [bodyKey]);

  const send = async (confirm: boolean) => {
    if (!body) return;
    setBusy(true); setError(null);
    try {
      const payload = { ...body, ...(confirm ? { confirm: true } : {}) };
      const base = `/api/connections/${connId}/ceph/pools`;
      const res = edit ? await api<PoolWriteResult>(`${base}/${encodeURIComponent(pool!.name)}`, { method: "PUT", body: payload })
                       : await api<PoolWriteResult>(base, { method: "POST", body: payload });
      const upid = res.upid;
      if (upid) await runTask(connId, res.node, async () => ({ upid }), edit ? "Modification du pool" : "Création du pool", 300);
      toast("ok", edit ? `Pool « ${pool!.name} » modifié` : `Pool « ${name} » créé`);
      await Promise.all([qc.invalidateQueries({ queryKey: ["ceph", connId, "pools"] }), qc.invalidateQueries({ queryKey: ["ceph", connId, "status"] })]);
      onClose();
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setRisk(reasons); else setError((e as Error).message);
    } finally { setBusy(false); }
  };

  return (
    <Modal wide title={edit ? `Modifier le pool « ${pool!.name} »` : "Nouveau pool"} subtitle={edit ? "Seuls les réglages modifiés sont envoyés." : "Un pool répliqué. Les pools à effacement ne sont pas gérés ici."}
      onClose={onClose} busy={busy} error={error} canSubmit={!!body} submitLabel={risk ? "Confirmer et enregistrer" : edit ? "Enregistrer" : "Créer le pool"} danger={!!risk}
      onSubmit={() => send(!!risk)}>
      <UnvalidatedBanner />
      {!edit && <Field label="Nom du pool" value={name} onChange={(e) => setName(e.target.value)} autoFocus maxLength={63} aria-invalid={name !== "" && !nameOk}
        hint={name === "" || nameOk ? "Lettres, chiffres, « _ », « - » et « . » ; ne peut pas être changé ensuite." : "Nom invalide : il doit commencer par une lettre ou un chiffre."} />}
      {erasure && <p className={warn}>Pool à effacement : le nombre de copies (size) et la règle CRUSH ne peuvent pas être modifiés.</p>}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Copies des données (size)" type="number" min={2} max={7} value={size} onChange={(e) => setSize(e.target.value)} disabled={erasure}
          hint="Au moins 2 : avec une seule copie, la panne d'un disque fait perdre des données." aria-invalid={!copiesOk} />
        <Field label="Copies minimales pour écrire (min_size)" type="number" min={2} max={7} value={minSize} onChange={(e) => setMinSize(e.target.value)}
          hint="Au moins 2, et pas plus que size." aria-invalid={!copiesOk} />
      </div>
      {!copiesOk && <p className="text-xs text-danger">size et min_size doivent être des entiers de 2 à 7, avec min_size inférieur ou égal à size.</p>}

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-1.5"><span className="text-sm text-muted">Groupes de placement (pg_num)</span>
          <select className="field" value={pgNum} onChange={(e) => setPgNum(e.target.value)}>
            {!PG.includes(Number(pgNum)) && <option value={pgNum}>{pgNum} (actuel)</option>}{PG.map((n) => <option key={n} value={n}>{n}</option>)}
          </select></label>
        <label className="block space-y-1.5"><span className="text-sm text-muted">Règle CRUSH</span>
          <select className="field" value={crush} onChange={(e) => setCrush(e.target.value)} disabled={erasure}>
            <option value="">{edit ? "Inchangée" : "Règle par défaut"}</option>
            {edit && pool!.crush_rule && !ruleNames.includes(pool!.crush_rule) && <option value={pool!.crush_rule}>{pool!.crush_rule} (actuelle)</option>}
            {ruleNames.map((r) => <option key={r} value={r}>{r}</option>)}
          </select></label>
      </div>
      <label className="block space-y-1.5"><span className="text-sm text-muted">Ajustement automatique des groupes (autoscaler)</span>
        <select className="field" value={autoscale} onChange={(e) => setAutoscale(e.target.value as PoolAutoscale)}>{AUTOSCALE.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>

      {!edit && (
        <>
          <label className="block space-y-1.5"><span className="text-sm text-muted">Application</span>
            <select className="field" value={application} onChange={(e) => { const v = e.target.value as PoolApplication; setApplication(v); if (v !== "rbd") setAddStorage(false); }}>
              {APPLICATIONS.map((a) => <option key={a} value={a}>{a}</option>)}</select></label>
          <label className={`flex items-start gap-2 text-sm ${application === "rbd" ? "" : "opacity-50"}`}>
            <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={addStorage} disabled={application !== "rbd"} onChange={(e) => setAddStorage(e.target.checked)} />
            <span>Créer aussi le stockage RBD associé<span className="block text-xs text-muted">Ajoute une définition de stockage à tout le cluster (visible dans « Stockage »).</span></span></label>
        </>
      )}

      {risk && (
        <div className={`${warn} space-y-2`} role="alert">
          <p className="font-medium">Confirmation requise</p>
          <ul className="list-disc space-y-1 pl-5">{risk.map((r) => <li key={r}>{r}</li>)}</ul>
          <p>Clique sur « Confirmer et enregistrer » pour continuer, ou modifie le formulaire.</p>
        </div>
      )}
    </Modal>
  );
}
