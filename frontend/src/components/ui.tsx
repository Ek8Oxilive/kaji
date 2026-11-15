import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { tr } from "../lib/i18n";

export function Button({ variant = "primary", className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-accent text-accentfg font-medium hover:brightness-110",
    ghost: "bg-surface2 text-fg hover:brightness-125 border border-line",
    danger: "bg-danger/15 text-danger border border-danger/40 hover:bg-danger/25",
  }[variant];
  return <button {...p} className={`rounded-xl px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`} />;
}

export function Field({ label, hint, ...p }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm text-muted">{label}</span>
      <input {...p} className="field" />
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Notice({ kind, children }: { kind: "ok" | "error" | "warn"; children: ReactNode }) {
  const tone = kind === "ok" ? "border-ok/40 bg-ok/10 text-ok" : kind === "warn" ? "border-warn/40 bg-warn/10 text-warn" : "border-danger/40 bg-danger/10 text-danger";
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-xl border px-3 py-2 text-sm ${tone}`}>
      {children}
    </div>
  );
}

/** Refus de droits (403 traduit par le backend) : Proxmox répond, c'est le jeton qui est limité. À ne pas présenter comme une panne. */
export const FORBIDDEN_PROBLEM = "Droits insuffisants";

export function ProxmoxProblem({ problem, resume }: { problem: string; resume?: boolean }) {
  if (problem.startsWith(FORBIDDEN_PROBLEM)) {
    return <Notice kind="warn">{tr("Droits limités : Proxmox répond, mais ton jeton ne donne pas accès à toutes les données (nœuds, RAM, disques…). Ce que tu peux voir reste affiché.")}</Notice>;
  }
  return <Notice kind="error">{resume
    ? tr("Proxmox ne répond pas ({problem}). Les dernières données connues restent affichées ; la reprise est automatique.", { problem })
    : tr("Proxmox ne répond pas ({problem}). Les dernières données connues restent affichées.", { problem })}</Notice>;
}
