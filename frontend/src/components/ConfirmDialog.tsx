import { useEffect, type ReactNode } from "react";
import { Button } from "./ui";

import { tr } from "../lib/i18n";
export function ConfirmDialog({ title, children, confirmLabel, danger, onConfirm, onCancel }: {
  title: string; children: ReactNode; confirmLabel: string; danger?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4" onClick={onCancel}>
      <div role="dialog" aria-modal="true" aria-label={title} className="panel rise w-full max-w-md space-y-4 p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold">{title}</h2>
        <div className="text-sm text-muted">{children}</div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>{tr("Annuler")}</Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} autoFocus>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}
