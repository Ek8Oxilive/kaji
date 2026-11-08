import { useState } from "react";
import { Button, Notice } from "./ui";

/** Secret affiché UNE seule fois (token d'API). On ne ferme qu'après confirmation : ensuite, ni Kaji ni Proxmox ne peuvent le redonner. */
export function SecretOnceDialog({ title, subject, secret, onDone }: { title: string; subject: string; secret: string; onDone: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => { try { await navigator.clipboard.writeText(secret); setCopied(true); } catch { /* le texte reste sélectionnable */ } };
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4">
      <div role="dialog" aria-modal="true" aria-label={title} className="panel rise w-full max-w-lg space-y-4 p-6">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm text-muted">Token <code>{subject}</code></p>
        <Notice kind="error">Note ce secret maintenant (gestionnaire de mots de passe). Il ne sera <b>plus jamais affiché</b> : ni par Kaji, ni par Proxmox. Le token n'a aucun droit tant qu'une ACL ne lui en donne pas.</Notice>
        <input readOnly value={secret} onFocus={(e) => e.currentTarget.select()} aria-label="Secret du token" className="field font-mono text-xs" />
        <div className="flex items-center justify-between gap-3">
          <Button type="button" variant="ghost" onClick={copy}>{copied ? "Copié" : "Copier"}</Button>
          <label className="flex gap-2 text-sm"><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /><span>J'ai noté le secret</span></label>
        </div>
        <div className="flex justify-end"><Button type="button" onClick={onDone} disabled={!saved}>Terminer</Button></div>
      </div>
    </div>
  );
}
