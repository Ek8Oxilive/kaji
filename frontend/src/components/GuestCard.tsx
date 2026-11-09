import type { Guest, GuestAction } from "../lib/api";
import { bytes, pct, uptime } from "../lib/format";
import { guestHash } from "../lib/route";
import { Gauge } from "./Gauge";
import { Button } from "./ui";

export function GuestCard({ guest, status, busyLabel, onAction, onOpen, onClone, index }: {
  guest: Guest; status: string | null; busyLabel?: string; onAction: (a: GuestAction) => void; onOpen: () => void; onClone: () => void; index: number;
}) {
  const running = status === "running";
  const stopped = status === "stopped";
  const paused = status === "paused";          // VM suspendue : « Reprendre » est sur la page de la machine (ticket #201)
  const alive = running || paused;
  // Juste après un clonage ou une création, Proxmox met sa liste à jour avec retard : nom absent et état inconnu pendant quelques secondes.
  const creating = !guest.template && guest.name === null && (status === null || status === "unknown");
  const dot = creating ? "bg-muted animate-pulse" : busyLabel ? "bg-warn animate-pulse" : running ? "bg-ok dot-live" : stopped ? "bg-muted" : "bg-warn";
  const text = creating ? "Création en cours" : busyLabel ?? (running ? "En marche" : paused ? "En pause" : stopped ? "Arrêtée" : (status ?? "Inconnu"));
  const off = !!busyLabel;
  return (
    // Un clic n'importe où sur la carte (hors boutons et liens) ouvre la page de la machine ; le nom est un vrai lien, pour le clavier.
    <article className="panel card-hover rise flex cursor-pointer flex-col gap-4 p-5" style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}
      onClick={(e) => { if (!(e.target as HTMLElement).closest("button, a")) onOpen(); }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold"><a href={guestHash(guest)} className="hover:underline focus-visible:underline">{guest.name ?? `#${guest.vmid}`}</a>{creating && <span className="ml-2 text-xs font-normal italic text-muted">(création en cours)</span>}</h3>
          <p className="text-xs text-muted">#{guest.vmid} · {guest.node}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className="rounded-md border border-line px-1.5 py-0.5 text-[0.7rem] font-medium uppercase tracking-wide text-muted">
            {guest.template ? "Modèle" : guest.type === "qemu" ? "VM" : "LXC"}
          </span>
          <span className="flex items-center gap-1.5 text-xs"><span className={`size-2 rounded-full ${dot}`} />{text}</span>
        </div>
      </div>

      <div className="space-y-2.5">
        <Gauge label="CPU" value={alive ? guest.cpu * 100 : 0} detail={alive ? `${(guest.cpu * 100).toFixed(0)} % · ${guest.maxcpu ?? "?"} vCPU` : `${guest.maxcpu ?? "?"} vCPU`} />
        <Gauge label="RAM" value={alive ? pct(guest.mem, guest.maxmem) : 0} detail={alive ? `${bytes(guest.mem)} / ${bytes(guest.maxmem)}` : bytes(guest.maxmem)} />
      </div>

      <div className="mt-auto space-y-3">
        <p className="text-xs text-muted">{creating ? "Proxmox n'a pas encore actualisé cette machine." : running ? `Actif depuis ${uptime(guest.uptime)}` : paused ? "En pause : ouvre la machine pour la reprendre" : "Arrêtée"}</p>
        <div className="flex flex-wrap gap-1.5">
          <Button variant="ghost" onClick={onClone} disabled={creating} className="!px-3 !py-1.5" title={guest.template ? "Créer une machine à partir de ce modèle" : "Copier cette machine"}>Cloner</Button>
          {!guest.template && <>
            {stopped && <Button onClick={() => onAction("start")} disabled={off} className="!px-3 !py-1.5" title="Démarre la machine">Démarrer</Button>}
            {running && <>
              <Button variant="ghost" onClick={() => onAction("reboot")} disabled={off} className="!px-3 !py-1.5" title="Redémarrage propre : le système s'arrête puis redémarre">Redémarrer</Button>
              <Button variant="ghost" onClick={() => onAction("shutdown")} disabled={off} className="!px-3 !py-1.5" title="Extinction propre : demande au système de s'arrêter">Éteindre</Button>
            </>}
            {alive && <Button variant="danger" onClick={() => onAction("stop")} disabled={off} className="!px-3 !py-1.5" title="Coupure brutale : arrête la machine sans la prévenir (risque de perte de données)">Forcer</Button>}
          </>}
        </div>
      </div>
    </article>
  );
}
