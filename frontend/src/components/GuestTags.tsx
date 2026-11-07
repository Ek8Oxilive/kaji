import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest } from "../lib/api";
import { Button, Notice } from "./ui";

const TAG = /^[a-z0-9_][a-z0-9_\-+.]{0,31}$/;

/** Étiquettes d'une machine : puces + éditeur. Le serveur valide à nouveau (motif, 20 au plus) et ne touche à aucune autre option. */
export function GuestTags({ connId, guest }: { connId: number; guest: Guest }) {
  const qc = useQueryClient();
  const tags = guest.tags ?? [];
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = () => { setDraft(tags); setText(""); setErr(null); setEdit(true); };
  const add = () => {
    const t = text.trim().toLowerCase();
    if (!t) return;
    if (!TAG.test(t)) { setErr("Étiquette invalide : lettres minuscules, chiffres, _ - + . (32 caractères au plus)."); return; }
    setErr(null); setText("");
    if (!draft.includes(t)) setDraft([...draft, t].sort());
  };
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      await api(`/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/${guest.type}/${guest.vmid}/tags`, { method: "PUT", body: { tags: draft } });
      qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] });
      setEdit(false);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const chip = "rounded-md border border-line px-2 py-0.5 text-xs";

  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Étiquettes">
      {!edit ? <>
        {tags.length === 0 && <span className="text-xs text-muted">Aucune étiquette</span>}
        {tags.map((t) => <span key={t} className={chip}>{t}</span>)}
        <Button variant="ghost" className="!px-2 !py-0.5 text-xs" onClick={start}>Modifier</Button>
      </> : <>
        {draft.map((t) => <span key={t} className={`${chip} flex items-center gap-1`}>{t}<button type="button" aria-label={`Retirer ${t}`} className="text-muted hover:text-danger" onClick={() => setDraft(draft.filter((x) => x !== t))}>✕</button></span>)}
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }}
          placeholder="ajouter…" aria-label="Nouvelle étiquette" maxLength={32} className="field !w-32 !py-0.5 text-xs" />
        <Button className="!px-2 !py-0.5 text-xs" onClick={save} disabled={busy}>Enregistrer</Button>
        <Button variant="ghost" className="!px-2 !py-0.5 text-xs" onClick={() => setEdit(false)} disabled={busy}>Annuler</Button>
        {err && <div className="w-full"><Notice kind="error">{err}</Notice></div>}
      </>}
    </div>
  );
}
