import { useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
/** Fenêtre de formulaire : Échap ou clic à l'extérieur pour fermer ; erreur affichée dans la fenêtre. */
export function Modal({ title, subtitle, onClose, onSubmit, submitLabel, busy, error, danger, canSubmit = true, wide, children }: {
  title: string; subtitle?: string; onClose: () => void; onSubmit: () => void; submitLabel: string;
  busy?: boolean; error?: string | null; danger?: boolean; canSubmit?: boolean; wide?: boolean; children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  // L'erreur s'affiche sous le formulaire : sur un petit écran elle serait hors de vue sans défilement. On l'y amène.
  const errorBox = useRef<HTMLDivElement>(null);
  useEffect(() => { if (error) errorBox.current?.scrollIntoView({ block: "nearest" }); }, [error]);
  const submit = (e: FormEvent) => { e.preventDefault(); if (canSubmit && !busy) onSubmit(); };
  // Rendu dans <body> : un parent à flou d'arrière-plan (`backdrop-filter`) sert de repère aux éléments `fixed` et coupait la fenêtre (page Accès, section apt).
  return createPortal(
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-2 sm:p-4" onClick={onClose}>
      <form role="dialog" aria-modal="true" aria-label={title} onSubmit={submit} onClick={(e) => e.stopPropagation()} className={`panel rise max-h-[94dvh] w-full ${wide ? "max-w-2xl" : "max-w-md"} space-y-4 overflow-y-auto p-4 sm:max-h-[92dvh] sm:p-6`}>
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
        </div>
        <div className="space-y-4">{children}</div>
        {error && <div ref={errorBox}><Notice kind="error">{error}</Notice></div>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>{tr("Annuler")}</Button>
          <Button type="submit" variant={danger ? "danger" : "primary"} disabled={busy || !canSubmit}>{busy ? "…" : submitLabel}</Button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
