import { useEffect, type FormEvent, type ReactNode } from "react";
import { Button, Notice } from "./ui";

/** Fenêtre de formulaire : Échap ou clic à l'extérieur pour fermer ; erreur affichée dans la fenêtre. */
export function Modal({ title, subtitle, onClose, onSubmit, submitLabel, busy, error, danger, canSubmit = true, children }: {
  title: string; subtitle?: string; onClose: () => void; onSubmit: () => void; submitLabel: string;
  busy?: boolean; error?: string | null; danger?: boolean; canSubmit?: boolean; children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  const submit = (e: FormEvent) => { e.preventDefault(); if (canSubmit && !busy) onSubmit(); };
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <form role="dialog" aria-modal="true" aria-label={title} onSubmit={submit} onClick={(e) => e.stopPropagation()} className="panel rise max-h-[92vh] w-full max-w-md space-y-4 overflow-y-auto p-6">
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
        </div>
        <div className="space-y-4">{children}</div>
        {error && <Notice kind="error">{error}</Notice>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Annuler</Button>
          <Button type="submit" variant={danger ? "danger" : "primary"} disabled={busy || !canSubmit}>{busy ? "…" : submitLabel}</Button>
        </div>
      </form>
    </div>
  );
}
