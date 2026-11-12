import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { Button, Notice } from "./ui";
import { ConfirmDialog } from "./ConfirmDialog";

import { tr, locale } from "../lib/i18n";
type Summary = { subject: string; issuer: string; self_signed: boolean; not_after: string; san: string[]; chain_length: number; key: string; fingerprint: string };
const field = "mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 font-mono text-xs text-fg";

/** Installer ou retirer un certificat personnalisé. La clé privée reste en mémoire le temps de l'envoi puis est effacée ; elle n'est jamais affichée. */
export function NodeCerts({ connId, node, hasCustom }: { connId: number; node: string; hasCustom: boolean }) {
  const qc = useQueryClient();
  const url = `/api/connections/${connId}/nodes/${encodeURIComponent(node)}/certificates/custom`;
  const [open, setOpen] = useState(false);
  const [certs, setCerts] = useState("");
  const [key, setKey] = useState("");
  const [sum, setSum] = useState<Summary | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<"install" | "remove" | null>(null);

  const reset = () => { setCerts(""); setKey(""); setSum(null); };
  const done = (text: string) => { setMsg({ kind: "ok", text }); reset(); setOpen(false); setAsk(null); qc.invalidateQueries({ queryKey: ["node-system", connId, node] }); };
  const fail = (e: unknown) => { setMsg({ kind: "error", text: (e as Error).message }); setAsk(null); };

  const check = async () => {
    setBusy(true); setMsg(null); setSum(null);
    try { setSum(await api<Summary>(`${url}/check`, { method: "POST", body: { certificates: certs, key } })); } catch (e) { fail(e); }
    setBusy(false);
  };
  const install = async () => {
    setBusy(true);
    try { await api(url, { method: "PUT", body: { certificates: certs, key, confirm: true, restart: true, replace_existing: hasCustom } }); done(tr("Certificat installé : pveproxy redémarre, la page de Proxmox sert le nouveau certificat.")); } catch (e) { fail(e); }
    setBusy(false);
  };
  const remove = async () => {
    setBusy(true);
    try { await api(`${url}?confirm=true&restart=true`, { method: "DELETE" }); done(tr("Certificat personnalisé retiré : retour au certificat auto-signé de Proxmox.")); } catch (e) { fail(e); }
    setBusy(false);
  };

  return (
    <div className="space-y-2">
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" className="!px-3 !py-1.5" onClick={() => { setOpen(!open); setMsg(null); }}>{hasCustom ? tr("Remplacer le certificat personnalisé") : tr("Installer un certificat personnalisé")}</Button>
        {hasCustom && <Button variant="danger" className="!px-3 !py-1.5" disabled={busy} onClick={() => setAsk("remove")}>{tr("Retirer le certificat personnalisé")}</Button>}
      </div>
      {open && (
        <form className="space-y-2 text-sm" autoComplete="off" onSubmit={(e) => { e.preventDefault(); check(); }}>
          <label className="block text-xs text-muted">{tr("Certificat puis chaîne (PEM)")}<textarea value={certs} onChange={(e) => setCerts(e.target.value)} rows={6} spellCheck={false} className={field} /></label>
          <label className="block text-xs text-muted">{tr("Clé privée (PEM, non chiffrée)")}<textarea value={key} onChange={(e) => setKey(e.target.value)} rows={4} spellCheck={false} autoComplete="off" className={field} /></label>
          <p className="text-xs text-muted">{tr("La clé traverse Kaji jusqu'à Proxmox ; elle n'est ni conservée, ni journalisée, ni affichée.")}</p>
          <Button type="submit" variant="ghost" disabled={busy || !certs || !key}>{tr("Contrôler")}</Button>
          {sum && (
            <div className="space-y-1 rounded-lg border border-line p-3 text-xs">
              <div><b>{sum.subject}</b>{" "}{tr("· émis par {issuer}{p}", { issuer: sum.issuer, p: sum.self_signed && tr(" (auto-signé)") })}</div>
              <div className="text-muted">{tr("Expire le {p} · clé {key} · {chain_length} certificat(s) · SAN : {p2}", { p: new Date(sum.not_after).toLocaleDateString(locale()), key: sum.key, chain_length: sum.chain_length, p2: sum.san.join(", ") || "aucun" })}</div>
              <div className="break-all text-muted">{tr("SHA-256 {fingerprint}", { fingerprint: sum.fingerprint })}</div>
              {!sum.san.some((s) => s === node || s.startsWith(`${node}.`)) && <p className="text-warn">{tr("Aucun nom du certificat ne correspond à « {node} » : les navigateurs signaleront une erreur.", { node })}</p>}
              <Button variant="danger" disabled={busy} onClick={() => setAsk("install")}>{tr("Installer…")}</Button>
            </div>)}
        </form>)}
      {ask === "install" && (
        <ConfirmDialog title={tr("Installer ce certificat sur {node} ?", { node })} confirmLabel={tr("Installer")} danger onCancel={() => setAsk(null)} onConfirm={install}>{tr("pveproxy redémarre : l'interface de Proxmox est coupée quelques secondes{p}. Si la connexion de Kaji vérifie le certificat, elle doit lui faire confiance.", { p: hasCustom ? tr(" et le certificat personnalisé actuel est remplacé") : "" })}</ConfirmDialog>)}
      {ask === "remove" && (
        <ConfirmDialog title={tr("Retirer le certificat personnalisé de {node} ?", { node })} confirmLabel={tr("Retirer")} danger onCancel={() => setAsk(null)} onConfirm={remove}>{tr("Le nœud reviendra au certificat auto-signé de Proxmox et pveproxy redémarrera. Les navigateurs afficheront un avertissement.")}</ConfirmDialog>)}
    </div>
  );
}
