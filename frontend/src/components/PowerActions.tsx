import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest } from "../lib/api";
import type { PowerOp, PowerState } from "../lib/types/alimentation-vm";
import { runTask } from "../lib/tasks";
import { Button, Notice } from "./ui";
import { useToast } from "./Toast";

const TEXT: Record<PowerOp, { title: string; verb: string; busy: string; done: string; text: string; danger: boolean }> = {
  reset: { title: "Réinitialiser", verb: "Réinitialiser", busy: "Réinitialisation", done: "réinitialisée", danger: true,
    text: "Coupure brutale puis redémarrage, comme le bouton reset : les données non enregistrées dans la VM sont perdues." },
  suspend: { title: "Suspendre", verb: "Suspendre", busy: "Suspension", done: "suspendue", danger: false,
    text: "La VM est figée en mémoire (état « pause ») jusqu'à ce que tu la reprennes." },
  hibernate: { title: "Hiberner", verb: "Hiberner", busy: "Hibernation", done: "hibernée", danger: true,
    text: "La mémoire est écrite sur disque et la VM s'arrête ; elle reprend là où elle en était au prochain démarrage. Sans agent invité, Proxmox peut refuser." },
  resume: { title: "Reprendre", verb: "Reprendre", busy: "Reprise", done: "reprise", danger: false, text: "La VM reprend son exécution." },
  template: { title: "Convertir en modèle", verb: "Convertir en modèle", busy: "Conversion", done: "convertie en modèle", danger: true,
    text: "Irréversible : la machine ne pourra plus démarrer, seulement être clonée. Les disques d'une VM sont renommés « base-… » chez Proxmox." },
};

/** Reset, suspendre, hiberner, reprendre (VM) et convertir en modèle (VM et LXC). Le serveur relit l'état de la machine et refuse si elle ne s'y prête pas. */
export function PowerActions({ connId, guest, running, stopped, disabled }: { connId: number; guest: Guest; running: boolean; stopped: boolean; disabled: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [op, setOp] = useState<PowerOp | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isVm = guest.type === "qemu";
  const base = `/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/${guest.type}/${guest.vmid}`;
  const state = useQuery({ queryKey: ["power", connId, guest.vmid], enabled: isVm && running && !guest.template, refetchInterval: 8000,
    queryFn: () => api<PowerState>(`${base}/power`) });
  const paused = isVm && running && state.data?.paused === true;
  const name = guest.name ?? "";

  const close = () => { if (!busy) { setOp(null); setTyped(""); setErr(null); } };
  const submit = async () => {
    if (!op) return;
    setBusy(true); setErr(null);
    const t = TEXT[op];
    try {
      const body = op === "template" ? { confirm: true, name: typed } : op === "reset" || op === "hibernate" ? { confirm: true } : {};
      await runTask(connId, guest.node, () => api<{ upid: string }>(`${base}/${op}`, { method: "POST", body }), t.busy);
      toast("ok", `${name || guest.vmid} ${t.done}`);
      setOp(null); setTyped("");
    } catch (e) { setErr((e as Error).message); setBusy(false); return; }
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["power", connId, guest.vmid] });
    for (const ms of [0, 5_000, 12_000]) setTimeout(() => qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] }), ms);
  };

  if (guest.template) return null;
  const btn = (o: PowerOp, danger = false) => <Button variant={danger ? "danger" : "ghost"} onClick={() => setOp(o)} disabled={disabled} className="!px-3 !py-1.5">{TEXT[o].title}{o === "template" ? "…" : ""}</Button>;
  const t = op ? TEXT[op] : null;
  return (
    <>
      {isVm && running && !paused && <>{btn("suspend")}{btn("hibernate")}{btn("reset")}</>}
      {paused && btn("resume")}
      {stopped && btn("template")}
      {op && t && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4" onClick={close}>
          <div role="dialog" aria-modal="true" aria-label={t.title} className="panel rise w-full max-w-md space-y-4 p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">{t.title} « {name || `#${guest.vmid}`} » ?</h2>
            <Notice kind={t.danger ? "error" : "ok"}>{t.text}</Notice>
            {op === "template" && (
              <label className="block text-xs text-muted">Retape <code>{name}</code> pour confirmer
                <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg" /></label>
            )}
            {err && <Notice kind="error">{err}</Notice>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close} disabled={busy}>Annuler</Button>
              <Button variant={t.danger ? "danger" : "primary"} onClick={submit} disabled={busy || (op === "template" && (name === "" || typed !== name))}>{busy ? "En cours…" : t.verb}</Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
