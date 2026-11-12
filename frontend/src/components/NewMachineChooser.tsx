import { useEffect } from "react";

import { tr } from "../lib/i18n";
export function NewMachineChooser({ onPick, onClose }: { onPick: (k: "vm" | "lxc") => void; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const card = "panel card-hover flex flex-col gap-1 p-5 text-left";
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={tr("Nouvelle machine")} className="panel rise w-full max-w-lg space-y-4 p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold">{tr("Nouvelle machine")}</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <button className={card} onClick={() => onPick("vm")} autoFocus>
            <span className="font-semibold">{tr("Machine virtuelle")}</span>
            <span className="text-sm text-muted">{tr("Un système complet, avec son propre noyau : Windows, Linux, tout ce qui s'installe depuis une image ISO.")}</span>
          </button>
          <button className={card} onClick={() => onPick("lxc")}>
            <span className="font-semibold">{tr("Conteneur LXC")}</span>
            <span className="text-sm text-muted">{tr("Léger et rapide : un Linux qui partage le noyau de l'hôte, créé en quelques secondes depuis un modèle.")}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
