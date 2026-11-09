import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createPortal } from "react-dom";
import { api, type Guest } from "../lib/api";
import type { PowerOp, PowerState } from "../lib/types/alimentation-vm";
import { runTask } from "../lib/tasks";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";
import { useToast } from "./Toast";

const TEXT: Record<PowerOp, { title: string; busy: string; done: string; text: string; danger: boolean }> = {
  reset: { title: "Réinitialiser", busy: "Réinitialisation", done: "réinitialisée", danger: true,
    text: "Coupure brutale puis redémarrage, comme le bouton reset : les données non enregistrées dans la VM sont perdues." },
  suspend: { title: "Suspendre", busy: "Suspension", done: "suspendue", danger: false,
    text: "La VM est figée en mémoire (état « pause ») jusqu'à ce que tu la reprennes." },
  hibernate: { title: "Hiberner", busy: "Hibernation", done: "hibernée", danger: true,
    text: "La mémoire est écrite sur disque et la VM s'arrête ; elle reprend là où elle en était au prochain démarrage. Sans agent invité, Proxmox peut refuser." },
  resume: { title: "Reprendre", busy: "Reprise", done: "reprise", danger: false, text: "La VM reprend son exécution." },
  template: { title: "Convertir en modèle", busy: "Conversion", done: "convertie en modèle", danger: true, text: "" },
};

/** Infobulle au survol de chaque bouton (comme « Coupure brutale » sur Forcer). */
const HINT: Record<PowerOp, string> = {
  suspend: "Met la VM en pause : elle est figée en mémoire, à reprendre ensuite",
  hibernate: "Écrit la mémoire sur disque et arrête la VM ; elle reprend là où elle en était au prochain démarrage",
  reset: "Coupure brutale puis redémarrage, comme le bouton reset",
  resume: "Reprend l'exécution de la VM en pause",
  template: "Convertit la machine en modèle (irréversible) : elle ne démarre plus, elle se clone",
};

/** Le texte de la conversion dépend du type : les disques d'une VM sont renommés « base-… », le volume d'un conteneur aussi (ticket #206). */
const templateText = (isVm: boolean) =>
  `Irréversible : la machine ne pourra plus démarrer, seulement être clonée. ${isVm ? "Les disques de la VM sont" : "Le volume du conteneur est"} renommé${isVm ? "s" : ""} « base-… » chez Proxmox.`;

/**
 * Reset, suspendre, hiberner, reprendre (VM) et convertir en modèle (VM et LXC). Le serveur relit l'état de la machine et refuse si elle ne s'y prête pas.
 * `status` : état de la liste des machines (`running`, `stopped`, `paused`…), après les actions rapides.
 */
export function PowerActions({ connId, guest, status, disabled }: { connId: number; guest: Guest; status: string | null; disabled: boolean }) {
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
  const state = useQuery({ queryKey: ["power", connId, guest.vmid], enabled: isVm && (running || listPaused) && !guest.template, refetchInterval: 8000,
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
      {isVm && running && state.data !== undefined && !paused && <>{btn("suspend")}{btn("hibernate")}{btn("reset")}</>}
      {paused && btn("resume")}
      {stopped && btn("template")}
      {/* Dans un portail : la carte d'en-tête crée son propre repère (animation), un `fixed` posé dedans passait sous la carte Notes (ticket #202). */}
      {op && t && createPortal(
        <Modal title={`${t.title} « ${name || `#${guest.vmid}`} » ?`} danger={t.danger} onClose={close} busy={busy} error={err}
          canSubmit={op !== "template" || (name !== "" && typed === name)} submitLabel={t.title} onSubmit={submit}>
          <Notice kind={t.danger ? "error" : "ok"}>{op === "template" ? templateText(isVm) : t.text}</Notice>
          {op === "template" && <Field label={`Retape ${name} pour confirmer`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoFocus />}
        </Modal>,
        document.body)}
    </>
  );
}
