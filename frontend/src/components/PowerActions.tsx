import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createPortal } from "react-dom";
import { api, type Guest } from "../lib/api";
import type { PowerOp, PowerState } from "../lib/types/alimentation-vm";
import { runTask } from "../lib/tasks";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";
import { useToast } from "./Toast";

import { tr } from "../lib/i18n";
const TEXT: Record<PowerOp, { title: string; busy: string; done: string; text: string; danger: boolean }> = {
  reset: { get title() { return tr("Réinitialiser"); }, get busy() { return tr("Réinitialisation"); }, get done() { return tr("réinitialisée"); }, danger: true,
    get text() { return tr("Coupure brutale puis redémarrage, comme le bouton reset : les données non enregistrées dans la VM sont perdues."); } },
  suspend: { get title() { return tr("Suspendre"); }, get busy() { return tr("Suspension"); }, get done() { return tr("suspendue"); }, danger: false,
    get text() { return tr("La VM est figée en mémoire (état « pause ») jusqu'à ce que tu la reprennes."); } },
  hibernate: { get title() { return tr("Hiberner"); }, get busy() { return tr("Hibernation"); }, get done() { return tr("hibernée"); }, danger: true,
    get text() { return tr("La mémoire est écrite sur disque et la VM s'arrête ; elle reprend là où elle en était au prochain démarrage. Sans agent invité, Proxmox peut refuser."); } },
  resume: { get title() { return tr("Reprendre"); }, get busy() { return tr("Reprise"); }, get done() { return tr("reprise"); }, danger: false, get text() { return tr("La VM reprend son exécution."); } },
  template: { get title() { return tr("Convertir en modèle"); }, get busy() { return tr("Conversion"); }, get done() { return tr("convertie en modèle"); }, danger: true, text: "" },
};

/** Infobulle au survol de chaque bouton (comme « Coupure brutale » sur Forcer). */
const HINT: Record<PowerOp, string> = {
  get suspend() { return tr("Met la VM en pause : elle est figée en mémoire, à reprendre ensuite"); },
  get hibernate() { return tr("Écrit la mémoire sur disque et arrête la VM ; elle reprend là où elle en était au prochain démarrage"); },
  get reset() { return tr("Coupure brutale puis redémarrage, comme le bouton reset"); },
  get resume() { return tr("Reprend l'exécution de la VM en pause"); },
  get template() { return tr("Convertit la machine en modèle (irréversible) : elle ne démarre plus, elle se clone"); },
};

/** Le texte de la conversion dépend du type : les disques d'une VM sont renommés « base-… », le volume d'un conteneur aussi (ticket #206). */
const templateText = (isVm: boolean) =>
  (isVm ? tr("Irréversible : la machine ne pourra plus démarrer, seulement être clonée. Les disques de la VM sont renommés « base-… » chez Proxmox.") : tr("Irréversible : la machine ne pourra plus démarrer, seulement être clonée. Le volume du conteneur est renommé « base-… » chez Proxmox."));

/**
 * Reset, suspendre, hiberner, reprendre (VM) et convertir en modèle (VM et LXC). Le serveur relit l'état de la machine et refuse si elle ne s'y prête pas.
 * `status` : état de la liste des machines (`running`, `stopped`, `paused`…), après les actions rapides.
 */
export function PowerActions({ connId, guest, status, disabled, fromList = false }: { connId: number; guest: Guest; status: string | null; disabled: boolean; fromList?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [op, setOp] = useState<PowerOp | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isVm = guest.type === "qemu";
  const stopped = status === "stopped";
  // Proxmox met une VM suspendue en « paused » dans la liste (essai réel, ticket #201) ; `/power` le confirme avec `paused: true`.
  const listPaused = status === "paused";
  const running = status === "running";
  const base = `/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/${guest.type}/${guest.vmid}`;
  const state = useQuery({ queryKey: ["power", connId, guest.vmid], enabled: !fromList && isVm && (running || listPaused) && !guest.template, refetchInterval: 8000,
    queryFn: () => api<PowerState>(`${base}/power`) });
  const paused = isVm && (listPaused || (running && state.data?.paused === true));
  const name = guest.name ?? "";

  const close = () => { if (!busy) { setOp(null); setTyped(""); setErr(null); } };
  const submit = async () => {
    if (!op) return;
    setBusy(true); setErr(null);
    const t = TEXT[op];
    try {
      const body = op === "template" ? { confirm: true, name: typed } : op === "reset" || op === "hibernate" ? { confirm: true } : {};
      const { upid } = await api<{ upid: string | null }>(`${base}/${op}`, { method: "POST", body });
      if (upid) await runTask(connId, guest.node, async () => ({ upid }), t.busy);      // un LXC converti en modèle ne renvoie pas de tâche : déjà fait
      toast("ok", `${name || guest.vmid} ${t.done}`);
      setOp(null); setTyped("");
    } catch (e) { setErr((e as Error).message); setBusy(false); return; }
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["power", connId, guest.vmid] });
    // La liste de Proxmox change d'état avec quelques secondes de retard (essai réel : 6 à 10 s).
    for (const ms of [0, 4_000, 9_000, 15_000]) setTimeout(() => qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] }), ms);
  };

  if (guest.template) return null;
  const btn = (o: PowerOp, danger = false) => <Button variant={danger ? "danger" : "ghost"} onClick={() => setOp(o)} disabled={disabled} title={HINT[o]} className="!px-3 !py-1.5">{TEXT[o].title}{o === "template" ? "…" : ""}</Button>;
  const t = op ? TEXT[op] : null;
  return (
    <>
      {isVm && running && (fromList || state.data !== undefined) && !paused && <>{btn("suspend")}{btn("hibernate")}{btn("reset")}</>}
      {paused && btn("resume")}
      {stopped && btn("template")}
      {/* Dans un portail : la carte d'en-tête crée son propre repère (animation), un `fixed` posé dedans passait sous la carte Notes (ticket #202). */}
      {op && t && createPortal(
        <Modal title={`${t.title} « ${name || `#${guest.vmid}`} » ?`} danger={t.danger} onClose={close} busy={busy} error={err}
          canSubmit={op !== "template" || (name !== "" && typed === name)} submitLabel={t.title} onSubmit={submit}>
          <Notice kind={t.danger ? "error" : "ok"}>{op === "template" ? templateText(isVm) : t.text}</Notice>
          {op === "template" && <Field label={tr("Retape {name} pour confirmer", { name })} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoFocus />}
        </Modal>,
        document.body)}
    </>
  );
}
