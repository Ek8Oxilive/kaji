import type { ReactNode } from "react";
import { isErr, type FwOptions, type FwPart, type FwRule } from "../lib/types/reseau";
import { Notice } from "./ui";

import { tr } from "../lib/i18n";
export const yn = (v: boolean | null | undefined) => (v === null || v === undefined ? "–" : v ? tr("oui") : tr("non"));
export const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[36rem] text-sm">
    <thead><tr className="border-b border-line text-left text-xs text-muted">{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
);
export const Empty = ({ children }: { children: ReactNode }) => <div className="rounded-xl border border-line bg-surface2 p-4 text-sm text-muted">{children}</div>;

export function Rules({ rules }: { rules: FwPart<FwRule[]> }) {
  if (isErr(rules)) return <Notice kind="error">{rules.error}</Notice>;
  if (rules.length === 0) return <Empty>{tr("Aucune règle.")}</Empty>;
  return (
    <Table head={["#", tr("Sens"), tr("Action"), tr("Source"), tr("Destination"), tr("Protocole"), tr("Commentaire")]}>
      {rules.map((r) => (
        <tr key={r.pos} className={`border-b border-line/60 last:border-0 ${r.enable === false ? "opacity-50" : ""}`}>
          <td className="px-4 py-2 tabular-nums text-muted">{r.pos}</td><td className="px-4 py-2">{r.type ?? "–"}</td>
          <td className={`px-4 py-2 font-medium ${r.action === "ACCEPT" ? "text-ok" : r.action === "DROP" || r.action === "REJECT" ? "text-danger" : ""}`}>{r.action ?? "–"}</td>
          <td className="px-4 py-2 text-muted">{r.source ?? tr("tous")}</td><td className="px-4 py-2 text-muted">{r.dest ?? tr("tous")}{r.dport ? `:${r.dport}` : ""}</td>
          <td className="px-4 py-2 text-muted">{r.macro ?? r.proto ?? "–"}</td><td className="px-4 py-2 text-muted">{r.comment ?? ""}{r.enable === false ? tr(" (désactivée)") : ""}</td>
        </tr>))}
    </Table>
  );
}
export const Options = ({ o }: { o: FwPart<FwOptions> }) => isErr(o) ? <Notice kind="error">{o.error}</Notice> : (
  <p className="text-sm text-muted">{Object.entries(o).filter(([k]) => k !== "digest").map(([k, v]) => `${k} : ${v === null ? "–" : typeof v === "boolean" ? yn(v) : v}`).join(" · ") || tr("Aucune option définie.")}</p>);
