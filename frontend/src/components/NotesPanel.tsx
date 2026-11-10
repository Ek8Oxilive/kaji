import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Button, Notice } from "./ui";

const MAX = 8192;

/** Notes d'une machine ou d'un nœud. Le texte est affiché tel quel (jamais interprété comme du HTML) ; le serveur exige le digest lu juste avant : on relit donc les notes à l'ouverture de l'éditeur (d'autres écrans, comme les étiquettes, modifient la même configuration). */
export function NotesPanel({ url, label }: { url: string; label: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["notes", url], staleTime: 0, queryFn: () => api<{ notes: string; digest: string | null; empty: boolean }>(url) });
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!edit && q.data) setText(q.data.notes); }, [q.data, edit]);

  const save = async () => {
    if (!q.data || (!q.data.digest && !q.data.empty)) return;          // sans digest, seule une configuration vide (nœud sans réglage) est modifiable
    setBusy(true); setErr(null);
    try {
      await api(url, { method: "PUT", body: { notes: text, digest: q.data.digest ?? undefined } });
      await qc.invalidateQueries({ queryKey: ["notes", url] });
      setEdit(false);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };

  if (q.isLoading) return <div className="panel h-16 animate-pulse" />;
  if (q.error || !q.data) return <Notice kind="error">{(q.error as Error | null)?.message ?? "Notes illisibles"}</Notice>;
  return (
    <section className="panel space-y-2 p-4" aria-label={label}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">{label}</h3>
        {!edit && (q.data.digest || q.data.empty) && <Button variant="ghost" className="!px-3 !py-1 text-xs" onClick={async () => { setErr(null); const r = await q.refetch(); if (r.data) { setText(r.data.notes); setEdit(true); } }}>Modifier</Button>}
      </div>
      {!edit ? (q.data.notes.trim() ? <p className="whitespace-pre-wrap break-words text-sm">{q.data.notes}</p> : <p className="text-sm text-muted">Aucune note.</p>) : (
        <div className="space-y-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} maxLength={MAX} aria-label={label} className="field font-mono text-xs" spellCheck={false} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-muted">{text.length} / {MAX}. Un texte vide supprime la note.</span>
            <span className="flex gap-2"><Button variant="ghost" className="!px-3 !py-1.5" onClick={() => setEdit(false)} disabled={busy}>Annuler</Button><Button className="!px-3 !py-1.5" onClick={save} disabled={busy}>Enregistrer</Button></span>
          </div>
        </div>)}
      {err && <Notice kind="error">{err}</Notice>}
    </section>
  );
}
