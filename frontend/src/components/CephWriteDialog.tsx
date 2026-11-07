import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { confirmReasons } from "../lib/confirmRisk";
import { runTask } from "../lib/tasks";
import type { CephWriteResult } from "../lib/types/ceph";
import { UnvalidatedBanner } from "./CephPoolDialog";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Field } from "./ui";

const warn = "rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn";
const CLASSES = ["", "hdd", "ssd", "nvme"];

/** Ce que la fenêtre fait. `nodes` : liste de nœuds à choisir (création) ; sinon `node` est fixé (l'OSD ou le service vit sur ce nœud). */
export type CephWrite = {
  title: string; subtitle?: string; submitLabel: string; done: string;
  tail: string;                      // sous /ceph/nodes/{node}/
  node?: string; nodes?: string[];
  extra?: "mds" | "osd";
};

/**
 * Écriture Ceph sur un nœud (créer, démarrer, arrêter, dedans, dehors). Les confirmations viennent du SERVEUR : on envoie sans `confirm`,
 * on montre ses raisons, puis on renvoie avec `confirm: true`. Créer un OSD EFFACE le disque : on retape alors son nom exact.
 */
export function CephWriteDialog({ connId, spec, onClose }: { connId: number; spec: CephWrite; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [node, setNode] = useState(spec.node ?? spec.nodes?.[0] ?? "");
  const [hot, setHot] = useState(false);
  const [dev, setDev] = useState("");
  const [encrypted, setEncrypted] = useState(false);
  const [cls, setCls] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [risk, setRisk] = useState<string[] | null>(null);

  const osd = spec.extra === "osd";
  const devOk = !osd || /^\/dev\/[A-Za-z0-9][A-Za-z0-9/_-]{0,63}$/.test(dev);
  const body: Record<string, unknown> = spec.extra === "mds" ? { hotstandby: hot }
    : osd ? { dev, encrypted, ...(cls ? { device_class: cls } : {}) } : {};

  // Une confirmation ne vaut que pour la demande qui l'a provoquée : si un champ change, les raisons ne sont plus celles-là.
  const key = JSON.stringify([node, body]);
  useEffect(() => { setRisk(null); setTyped(""); }, [key]);

  const send = async (confirm: boolean) => {
    setBusy(true); setError(null);
    try {
      const payload = { ...body, ...(confirm ? { confirm: true, ...(osd ? { confirm_dev: typed } : {}) } : {}) };
      const res = await api<CephWriteResult>(`/api/connections/${connId}/ceph/nodes/${encodeURIComponent(node)}/${spec.tail}`, { method: "POST", body: payload });
      const upid = res.upid;
      if (upid) await runTask(connId, res.node, async () => ({ upid }), spec.title, 300);
      toast("ok", spec.done);
      await qc.invalidateQueries({ queryKey: ["ceph", connId] });
      onClose();
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setRisk(reasons); else setError((e as Error).message);
    } finally { setBusy(false); }
  };

  const retypeOk = !osd || !risk || typed === dev;
  return (
    <Modal title={spec.title} subtitle={spec.subtitle} onClose={onClose} busy={busy} error={error} canSubmit={!!node && devOk && retypeOk}
      submitLabel={risk ? "Confirmer" : spec.submitLabel} danger={!!risk || osd} onSubmit={() => send(!!risk)}>
      <UnvalidatedBanner />
      {spec.nodes && (
        <label className="block space-y-1.5"><span className="text-sm text-muted">Nœud</span>
          <select className="field" value={node} onChange={(e) => setNode(e.target.value)}>{spec.nodes.map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
      )}
      {spec.extra === "mds" && (
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={hot} onChange={(e) => setHot(e.target.checked)} />
          <span>MDS de secours « chaud »<span className="block text-xs text-muted">Suit de près le MDS actif pour reprendre plus vite.</span></span></label>
      )}
      {osd && (
        <>
          <p className={warn}>Créer un OSD <strong>EFFACE ENTIÈREMENT le disque</strong>. Kaji refuse tout disque qui n'est pas dans la liste des disques inutilisés du nœud.</p>
          <Field label="Disque" value={dev} onChange={(e) => setDev(e.target.value)} placeholder="/dev/sdb" autoFocus maxLength={69} aria-invalid={dev !== "" && !devOk}
            hint={dev === "" || devOk ? "Chemin du disque sur ce nœud, par exemple /dev/sdb." : "Chemin invalide : il doit ressembler à /dev/sdb."} />
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={encrypted} onChange={(e) => setEncrypted(e.target.checked)} />
            <span>Chiffrer l'OSD<span className="block text-xs text-muted">Les données du disque sont chiffrées au repos.</span></span></label>
          <label className="block space-y-1.5"><span className="text-sm text-muted">Classe de disque</span>
            <select className="field" value={cls} onChange={(e) => setCls(e.target.value)}>{CLASSES.map((c) => <option key={c} value={c}>{c || "Détectée automatiquement"}</option>)}</select></label>
        </>
      )}
      {risk && (
        <div className={`${warn} space-y-2`} role="alert">
          <p className="font-medium">Confirmation requise</p>
          <ul className="list-disc space-y-1 pl-5">{risk.map((r) => <li key={r}>{r}</li>)}</ul>
          {osd && <Field label={`Retape « ${dev} » pour confirmer`} value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus autoComplete="off" />}
          <p>{osd ? "Le bouton « Confirmer » s'active quand le nom du disque est identique." : "Clique sur « Confirmer » pour continuer, ou annule."}</p>
        </div>
      )}
    </Modal>
  );
}
