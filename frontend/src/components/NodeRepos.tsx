import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { RepoInfo } from "../lib/types/systeme";
import { Button, Notice } from "./ui";

type Plan = { kind: "toggle"; path: string; index: number; enabled: boolean; label: string } | { kind: "add"; handle: string; label: string };

/** Dépôts apt : activer / désactiver / ajouter. Le serveur relit l'état, vérifie le digest et impose `accept_risk` quand il y a un risque. */
export function NodeRepos({ connId, node, repos }: { connId: number; node: string; repos: RepoInfo }) {
  const qc = useQueryClient();
  const url = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/apt/repositories`;
  const [plan, setPlan] = useState<Plan | null>(null);
  const [risk, setRisk] = useState<string | null>(null);
  const [accept, setAccept] = useState(false);
  const [busy, setBusy] = useState(false);
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
      {!repos.digest && <Notice kind="error">Empreinte des dépôts illisible : modification désactivée.</Notice>}
      {repos.files.map((f) => (
        <div key={f.path}>
          <div className="text-xs text-muted">{f.path}</div>
          {f.repositories.map((x) => (
            <div key={x.index} className="flex flex-wrap items-center gap-2 py-0.5">
              <span className={`min-w-0 flex-1 break-all ${x.enabled ? "" : "text-muted line-through"}`}>{x.types.join(" ")} {x.uris.join(" ")} {x.suites.join(" ")} {x.components.join(" ")}</span>
              {f.path && repos.digest && <Button variant="ghost" className="!px-2 !py-1 text-xs" disabled={busy}
                onClick={() => setPlan({ kind: "toggle", path: f.path!, index: x.index, enabled: !x.enabled, label: `${x.enabled ? "Désactivation" : "Activation"} du dépôt ${x.components.join(" ")}` })}>{x.enabled ? "Désactiver" : "Activer"}</Button>}
            </div>))}
        </div>))}
      {repos.errors > 0 && <p className="text-danger">{repos.errors} fichier(s) de dépôts illisible(s).</p>}
      {repos.digest && addable.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line/60 pt-2">
          <span className="text-xs text-muted">Ajouter un dépôt standard :</span>
          {addable.map((s) => <Button key={s.handle} variant="ghost" className="!px-2 !py-1 text-xs" title={s.description ?? ""} disabled={busy}
            onClick={() => setPlan({ kind: "add", handle: s.handle!, label: `Ajout du dépôt ${s.name}` })}>{s.name}</Button>)}
        </div>)}
      {plan && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4" onClick={busy ? undefined : close}>
          <div role="dialog" aria-modal="true" aria-label={plan.label} className="panel rise w-full max-w-md space-y-4 p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">{plan.label} sur {node} ?</h2>
            <p className="text-sm text-muted">Les paquets proposés par apt changent. Kaji relit les dépôts avant d'écrire et refuse si la configuration a bougé entre-temps.</p>
            {risk && <label className="flex gap-2 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} /><span>Risque : {risk}. J'accepte.</span></label>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close} disabled={busy}>Annuler</Button>
              <Button variant="danger" onClick={() => send(accept)} disabled={busy || (!!risk && !accept)}>{busy ? "…" : "Confirmer"}</Button>
            </div>
          </div>
        </div>)}
    </div>
  );
}
