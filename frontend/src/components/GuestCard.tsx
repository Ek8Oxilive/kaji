import type { Guest, GuestAction } from "../lib/api";
import { bytes, pct, uptime } from "../lib/format";
import { Gauge } from "./Gauge";
import { Button } from "./ui";

export function GuestCard({ guest, status, busyLabel, onAction, onHardware, onClone, index }: {
  guest: Guest; status: string | null; busyLabel?: string; onAction: (a: GuestAction) => void; onHardware: () => void; onClone: () => void; index: number;
}) {
  const running = status === "running";
  const stopped = status === "stopped";
  const dot = busyLabel ? "bg-warn animate-pulse" : running ? "bg-ok dot-live" : stopped ? "bg-muted" : "bg-warn";
  const text = busyLabel ?? (running ? "En marche" : stopped ? "Arrêtée" : (status ?? "Inconnu"));
  const off = !!busyLabel;
  return (
    <article className="panel card-hover rise flex flex-col gap-4 p-5" style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{guest.name ?? `#${guest.vmid}`}</h3>
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
        <Gauge label="CPU" value={running ? guest.cpu * 100 : 0} detail={running ? `${(guest.cpu * 100).toFixed(0)} % · ${guest.maxcpu ?? "?"} vCPU` : `${guest.maxcpu ?? "?"} vCPU`} />
        <Gauge label="RAM" value={running ? pct(guest.mem, guest.maxmem) : 0} detail={running ? `${bytes(guest.mem)} / ${bytes(guest.maxmem)}` : bytes(guest.maxmem)} />
      </div>

      <div className="mt-auto space-y-3">
        <p className="text-xs text-muted">{running ? `Actif depuis ${uptime(guest.uptime)}` : "Arrêtée"}</p>
        <div className="flex flex-wrap gap-1.5">
          {!guest.template && <Button variant="ghost" onClick={onHardware} className="!px-3 !py-1.5" title="Voir et modifier le matériel">Matériel</Button>}
          <Button variant="ghost" onClick={onClone} className="!px-3 !py-1.5" title={guest.template ? "Créer une machine à partir de ce modèle" : "Copier cette machine"}>Cloner</Button>
          {!guest.template && <>
            {stopped && <Button onClick={() => onAction("start")} disabled={off} className="!px-3 !py-1.5">Démarrer</Button>}
            {running && <>
              <Button variant="ghost" onClick={() => onAction("reboot")} disabled={off} className="!px-3 !py-1.5">Redémarrer</Button>
              <Button variant="ghost" onClick={() => onAction("shutdown")} disabled={off} className="!px-3 !py-1.5">Éteindre</Button>
              <Button variant="danger" onClick={() => onAction("stop")} disabled={off} className="!px-3 !py-1.5" title="Coupure brutale">Forcer</Button>
            </>}
          </>}
        </div>
      </div>
    </article>
  );
}
