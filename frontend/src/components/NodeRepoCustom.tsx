import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { Modal } from "./Modal";
import { Button, Field } from "./ui";

type Result = { file: string; content: string; commands: string[]; warnings: string[]; exists: boolean | null };
const ARCHS = ["amd64", "arm64", "armhf", "i386", "all"];
const words = (s: string) => s.split(/\s+/).filter(Boolean);

/** Dépôt apt personnalisé : l'API de Proxmox ne sait pas l'écrire, Kaji fabrique donc le fichier et les commandes à coller dans la console du nœud (rien n'est envoyé à Proxmox). */
export function CustomRepoDialog({ connId, node, onClose }: { connId: number; node: string; onClose: () => void }) {
  const [name, setName] = useState(""), [uris, setUris] = useState(""), [suites, setSuites] = useState(""), [components, setComponents] = useState("");
  const [signedBy, setSignedBy] = useState("/usr/share/keyrings/");
  const [src, setSrc] = useState(false);
  const [archs, setArchs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null), [copied, setCopied] = useState<number | null>(null);

  const ok = /^[a-z0-9][a-z0-9-]{0,59}$/.test(name) && words(uris).length > 0 && words(suites).length > 0 && words(components).length > 0;
  const generate = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await api<Result>(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/apt/repositories/custom`, {
        method: "POST", body: { name, types: src ? ["deb", "deb-src"] : ["deb"], uris: words(uris), suites: words(suites), components: words(components),
          signed_by: /\.(gpg|asc)$/.test(signedBy) ? signedBy : null, architectures: archs } }));
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const copy = async (i: number, text: string) => { try { await navigator.clipboard.writeText(text); setCopied(i); setTimeout(() => setCopied(null), 2000); } catch { /* presse-papiers indisponible */ } };

  return (
    <Modal title={tr("Dépôt personnalisé sur {node}", { node })} wide onClose={onClose} onSubmit={generate} submitLabel={tr("Générer les commandes")} busy={busy} error={err} canSubmit={ok}
      subtitle={tr("L'API de Proxmox ne sait pas ajouter un dépôt libre : Kaji prépare le fichier et les commandes à coller dans la console du nœud. Rien n'est envoyé à Proxmox.")}>
      <Field label={tr("Nom du fichier")} value={name} onChange={(e) => setName(e.target.value)} placeholder="mon-depot" hint={tr("Crée /etc/apt/sources.list.d/<nom>.sources : minuscules, chiffres et tirets.")} />
      <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Adresses (une par ligne ou séparées par des espaces)")}</span>
        <textarea className="field" rows={2} value={uris} onChange={(e) => setUris(e.target.value)} placeholder="https://apt.example.org/debian" /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={tr("Suites")} value={suites} onChange={(e) => setSuites(e.target.value)} placeholder="trixie" hint={tr("Séparées par des espaces.")} />
        <Field label={tr("Composants")} value={components} onChange={(e) => setComponents(e.target.value)} placeholder="main" hint={tr("Séparés par des espaces.")} />
      </div>
      <Field label={tr("Clé de signature (Signed-By)")} value={signedBy} onChange={(e) => setSignedBy(e.target.value)} placeholder="/usr/share/keyrings/mon-depot.gpg"
        hint={tr("Chemin d'une clé déjà posée sur le nœud (/usr/share/keyrings ou /etc/apt/keyrings, .gpg ou .asc). Kaji ne télécharge aucune clé.")} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={src} onChange={(e) => setSrc(e.target.checked)} />{tr("Inclure les sources (deb-src)")}</label>
        <span className="text-muted">{tr("Architectures :")}</span>
        {ARCHS.map((a) => <label key={a} className="flex items-center gap-1"><input type="checkbox" checked={archs.includes(a)} onChange={(e) => setArchs(e.target.checked ? [...archs, a] : archs.filter((x) => x !== a))} />{a}</label>)}
      </div>
      {res && (
        <div className="space-y-3 border-t border-line/60 pt-3 text-sm" aria-live="polite">
          {res.warnings.map((w) => <p key={w} className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">{tr("Attention : {w}", { w: tr(w) })}</p>)}
          <p className="text-muted">{tr("Colle ces commandes dans la console du nœud (page Nœud, ou onglet Console) :")}</p>
          {res.commands.map((c, i) => (
            <div key={i} className="flex items-start gap-2">
              <pre className="min-w-0 flex-1 overflow-x-auto rounded bg-surface px-2 py-1 text-xs text-fg">{c}</pre>
              <Button type="button" variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => copy(i, c)}>{copied === i ? tr("Copié") : tr("Copier")}</Button>
            </div>))}
        </div>)}
    </Modal>
  );
}
