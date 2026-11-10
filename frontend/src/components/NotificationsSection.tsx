import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { TYPE_LABEL, type NotifEndpoint, type NotifTarget, type Notifications } from "../lib/types/notifications";
import { NotifMatcherDialog, type MatcherMode } from "./NotifMatcherDialog";
import { NotifTargetDialog, type TargetMode } from "./NotifTargetDialog";
import { Button, Notice } from "./ui";

const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[32rem] text-sm">
    <thead><tr className="border-b border-line text-left text-xs text-muted">{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
);

/** Résumé d'une cible : destination utile, jamais un secret (mot de passe, jeton, valeurs d'en-têtes). */
function destination(e: NotifEndpoint | undefined): string {
  if (!e) return "–";
  if (e.type === "sendmail") return [...(e.mailto ?? []), ...(e.mailto_user ?? [])].join(", ") || "–";
  if (e.type === "smtp") return `${e.server ?? "?"}:${e.port ?? "?"} (${e.mode ?? "défaut"}) → ${(e.mailto ?? []).concat(e.mailto_user ?? []).join(", ") || "–"}`;
  if (e.type === "gotify") return e.server ?? "–";
  return `${(e.method ?? "post").toUpperCase()} ${e.url ?? "?"}${e.header_names?.length ? ` · en-têtes : ${e.header_names.join(", ")}` : ""}${e.secret_names?.length ? ` · secrets : ${e.secret_names.join(", ")}` : ""}`;
}

/** Datacenter → Notifications : cibles et règles (ajouter, modifier, supprimer, tester). Aucun secret affiché ; mot de passe, jeton, valeurs d'en-têtes en écriture seule. */
export function NotificationsSection({ connId }: { connId: number }) {
  const q = useQuery({ queryKey: ["notifications", connId], queryFn: () => api<Notifications>(`/api/connections/${connId}/notifications`) });
  const [open, setOpen] = useState(true), [tmode, setTmode] = useState<TargetMode | null>(null), [mmode, setMmode] = useState<MatcherMode | null>(null);
  const d = q.data;
  const ep = (t: NotifTarget) => d?.endpoints[t.type]?.find((e) => e.name === t.name);
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Notifications</h2><button className="text-xs underline" onClick={() => setOpen(!open)}>{open ? "Replier" : "Déplier"}</button></div>
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}
      {d && Object.entries(d.errors).map(([k, m]) => <Notice key={k} kind="error">Lecture « {k} » impossible : {m}</Notice>)}
      {open && d && <>
        <div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-muted">Cibles</h3><Button variant="ghost" onClick={() => setTmode({ kind: "new" })}>Ajouter une cible…</Button></div>
        {d.targets.length === 0 ? <p className="text-sm text-muted">Aucune cible de notification.</p> : (
          <Table head={["Nom", "Type", "Destination", "Utilisée par", "État", ""]}>{d.targets.map((t) => (
            <tr key={t.name} className={`border-b border-line/60 last:border-0 align-top ${t.disable ? "opacity-60" : ""}`}>
              <td className="px-4 py-2 font-mono">{t.name}{t.builtin && <span className="ml-2 rounded bg-surface2 px-1.5 py-0.5 font-sans text-xs text-muted">intégrée</span>}</td>
              <td className="px-4 py-2 text-muted">{TYPE_LABEL[t.type]}</td>
              <td className="max-w-[22rem] break-all px-4 py-2 font-mono text-xs text-muted">{destination(ep(t))}</td>
              <td className="px-4 py-2 text-muted">{t.used_by.length ? t.used_by.join(", ") : <span className="text-danger">aucune règle</span>}</td>
              <td className="px-4 py-2 text-muted">{t.disable ? "désactivée" : "active"}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setTmode({ kind: "edit", target: t })}>Modifier</button><button className="underline" onClick={() => setTmode({ kind: "test", target: t })}>Tester</button>{!t.builtin && <button className="text-danger underline" onClick={() => setTmode({ kind: "delete", target: t })}>Supprimer</button>}</td>
            </tr>))}</Table>)}
        <div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-muted">Règles (matchers)</h3><Button variant="ghost" onClick={() => setMmode({ kind: "new" })}>Ajouter une règle…</Button></div>
        {d.matchers.length === 0 ? <p className="text-sm text-muted">Aucune règle : rien n'est envoyé.</p> : (
          <Table head={["Nom", "Condition", "Cibles", "État", ""]}>{d.matchers.map((m) => (
            <tr key={m.name} className={`border-b border-line/60 last:border-0 align-top ${m.disable ? "opacity-60" : ""}`}>
              <td className="px-4 py-2 font-mono">{m.name}{m.builtin && <span className="ml-2 rounded bg-surface2 px-1.5 py-0.5 font-sans text-xs text-muted">intégrée</span>}</td>
              <td className="px-4 py-2 text-xs text-muted">{[m.match_severity.length ? `gravité : ${m.match_severity.join(", ")}` : null, ...m.match_field, ...m.match_calendar.map((c) => `quand : ${c}`)].filter(Boolean).join(" · ") || "tout"}
                {" "}<span className="text-muted/70">({m.mode === "any" ? "une condition suffit" : "toutes"}{m.invert ? ", inversé" : ""})</span></td>
              <td className="px-4 py-2 font-mono text-xs text-muted">{m.targets.join(", ") || "–"}</td>
              <td className="px-4 py-2 text-muted">{m.disable ? "désactivée" : "active"}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMmode({ kind: "edit", matcher: m })}>Modifier</button>{!m.builtin && <button className="text-danger underline" onClick={() => setMmode({ kind: "delete", matcher: m })}>Supprimer</button>}</td>
            </tr>))}</Table>)}
        <p className="text-xs text-muted">Les mots de passe, jetons et valeurs d'en-têtes ne sont jamais affichés. « Tester » envoie un vrai message.</p>
      </>}
      {tmode && <NotifTargetDialog connId={connId} mode={tmode} onClose={() => setTmode(null)} />}
      {mmode && d && <NotifMatcherDialog connId={connId} mode={mmode} targets={d.targets} onClose={() => setMmode(null)} />}
    </section>
  );
}
