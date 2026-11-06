import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

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

export function Notice({ kind, children }: { kind: "ok" | "error"; children: ReactNode }) {
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-xl border px-3 py-2 text-sm ${kind === "ok" ? "border-ok/40 bg-ok/10 text-ok" : "border-danger/40 bg-danger/10 text-danger"}`}>
      {children}
    </div>
  );
}
