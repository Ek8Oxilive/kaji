import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../lib/api";
import type { RepoInfo } from "../lib/types/systeme";
import { CustomRepoDialog } from "./NodeRepoCustom";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
type Plan = { kind: "toggle"; path: string; index: number; enabled: boolean; label: string } | { kind: "add"; handle: string; label: string };

/** Dépôts apt : activer / désactiver / ajouter. Le serveur relit l'état, vérifie le digest et impose `accept_risk` quand il y a un risque. */
export function NodeRepos({ connId, node, repos }: { connId: number; node: string; repos: RepoInfo }) {
  const qc = useQueryClient();
  const url = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/apt/repositories`;
  const [plan, setPlan] = useState<Plan | null>(null);
  const [risk, setRisk] = useState<string | null>(null);
  const [accept, setAccept] = useState(false);
  const [busy, setBusy] = useState(false);
  const [custom, setCustom] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const close = () => { setPlan(null); setRisk(null); setAccept(false); };
  const send = async (acceptRisk: boolean) => {
    if (!plan || !repos.digest) return;
    setBusy(true); setMsg(null);
    try {
      const common = { digest: repos.digest, confirm: true, accept_risk: acceptRisk };
      if (plan.kind === "toggle") await api(url, { method: "PUT", body: { path: plan.path, index: plan.index, enabled: plan.enabled, ...common } });
      else await api(url, { method: "POST", body: { handle: plan.handle, ...common } });
      setMsg({ kind: "ok", text: `${plan.label} : fait.` });
      close();
      qc.invalidateQueries({ queryKey: ["node-system", connId, node] });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.message.startsWith("Risque à accepter")) setRisk(e.message.replace("Risque à accepter explicitement (accept_risk) : ", ""));
      else { setMsg({ kind: "error", text: (e as Error).message }); close(); }
    }
    setBusy(false);
  };

  const addable = repos.standard.filter((s) => s.status === null && s.handle);
  return (
    <div className="space-y-3 text-sm">
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      {!repos.digest && <Notice kind="error">{tr("Empreinte des dépôts illisible : modification désactivée.")}</Notice>}
      {repos.files.map((f) => (
        <div key={f.path}>
          <div className="text-xs text-muted">{f.path}</div>
          {f.repositories.map((x) => (
            <div key={x.index} className="flex flex-wrap items-center gap-2 py-0.5">
              <span className={`min-w-0 flex-1 break-all ${x.enabled ? "" : "text-muted line-through"}`}>{x.types.join(" ")} {x.uris.join(" ")} {x.suites.join(" ")} {x.components.join(" ")}</span>
              {f.path && repos.digest && <Button variant="ghost" className="!px-2 !py-1 text-xs" disabled={busy}
                onClick={() => setPlan({ kind: "toggle", path: f.path!, index: x.index, enabled: !x.enabled, label: tr("{p} du dépôt {p2}", { p: x.enabled ? tr("Désactivation") : tr("Activation"), p2: x.components.join(" ") }) })}>{x.enabled ? tr("Désactiver") : tr("Activer")}</Button>}
            </div>))}
        </div>))}
      {repos.errors > 0 && <p className="text-danger">{tr("{errors} fichier(s) de dépôts illisible(s).", { errors: repos.errors })}</p>}
      {repos.digest && addable.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line/60 pt-2">
          <span className="text-xs text-muted">{tr("Ajouter un dépôt standard :")}</span>
          {addable.map((s) => <Button key={s.handle} variant="ghost" className="!px-2 !py-1 text-xs" title={s.description ?? ""} disabled={busy}
            onClick={() => setPlan({ kind: "add", handle: s.handle!, label: tr("Ajout du dépôt {name}", { name: s.name }) })}>{s.name}</Button>)}
        </div>)}
      <div className="flex flex-wrap items-center gap-2 border-t border-line/60 pt-2">
        <Button variant="ghost" className="!px-2 !py-1 text-xs" disabled={busy} onClick={() => setCustom(true)}>{tr("Dépôt personnalisé…")}</Button>
        <span className="text-xs text-muted">{tr("Fichier et commandes à copier : Proxmox n'écrit pas les dépôts libres.")}</span>
      </div>
      {/* Portail : le bloc parent a un flou d'arrière-plan qui sert de repère aux éléments `fixed` (la fenêtre sortait de l'écran) */}
      {custom && createPortal(<CustomRepoDialog connId={connId} node={node} onClose={() => setCustom(false)} />, document.body)}
      {plan && createPortal(
        <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4" onClick={busy ? undefined : close}>
          <div role="dialog" aria-modal="true" aria-label={plan.label} className="panel rise w-full max-w-md space-y-4 p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">{tr("{label} sur {node} ?", { label: plan.label, node })}</h2>
            <p className="text-sm text-muted">{tr("Les paquets proposés par apt changent. Kaji relit les dépôts avant d'écrire et refuse si la configuration a bougé entre-temps.")}</p>
            {risk && <label className="flex gap-2 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} /><span>{tr("Risque : {risk}. J'accepte.", { risk })}</span></label>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close} disabled={busy}>{tr("Annuler")}</Button>
              <Button variant="danger" onClick={() => send(accept)} disabled={busy || (!!risk && !accept)}>{busy ? "…" : tr("Confirmer")}</Button>
            </div>
          </div>
        </div>, document.body)}
    </div>
  );
}
