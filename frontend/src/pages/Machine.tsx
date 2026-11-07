import { useEffect, useState } from "react";
import { BackupsTab } from "../components/BackupsTab";
import { CloneDialog } from "../components/CloneDialog";
import { GuestCharts } from "../components/charts/MetricsPanels";
import { GuestTags } from "../components/GuestTags";
import { GuestTasksTab } from "../components/GuestTasksTab";
import { ConsoleTab } from "../components/ConsoleTab";
import { CloudInitTab } from "../components/CloudInitTab";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Gauge } from "../components/Gauge";
import { HardwareTab } from "../components/HardwareTab";
import { SnapshotsTab } from "../components/SnapshotsTab";
import { Button, Notice } from "../components/ui";
import type { GuestAction } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import { bytes, pct, uptime } from "../lib/format";
import { CONFIRM } from "../lib/guestConfirm";
import { guestHash } from "../lib/route";
import { useCluster, useGuestActions } from "../lib/useCluster";

type Tab = "hardware" | "metrics" | "console" | "snapshots" | "cloudinit" | "backups" | "tasks";
const TABS: [Tab, string][] = [["hardware", "Matériel"], ["metrics", "Performances"], ["console", "Console"], ["snapshots", "Snapshots"], ["cloudinit", "Cloud-init"], ["backups", "Sauvegardes"], ["tasks", "Tâches"]];

// Ces valeurs viennent de l'adresse : on les contrôle, et elles ne servent qu'à retrouver la machine dans la liste du cluster.
const NODE = /^[A-Za-z0-9]([A-Za-z0-9-]{0,62})$/;
const parse = ([node, type, vmid, tab]: string[]) => {
  if (!node || !NODE.test(node) || (type !== "qemu" && type !== "lxc") || !/^[0-9]{3,9}$/.test(vmid ?? "")) return null;
  return { node, type: type as "qemu" | "lxc", vmid: Number(vmid), tab: (TABS.some(([t]) => t === tab) ? tab : "hardware") as Tab };
};

export function Machine({ params, go, onGoConnections }: { params: string[]; go: (hash: string, o?: { replace?: boolean }) => void; onGoConnections: () => void }) {
  const ref = parse(params);
  const { active, id, conns } = useActiveConnection();
  const { guests, nodes, problem } = useCluster(id);
  const { run, busy, effectiveStatus } = useGuestActions(id);
  const [pending, setPending] = useState<Exclude<GuestAction, "start"> | null>(null);
  const [clone, setClone] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  const list = guests.data;
  const guest = ref && list ? list.find((g) => g.node === ref.node && g.type === ref.type && g.vmid === ref.vmid) : undefined;
  // Machine migrée (ou ouverte avec un ancien lien) : même identifiant sur un autre nœud, on suit.
  const moved = ref && list && !guest ? list.find((g) => g.type === ref.type && g.vmid === ref.vmid) : undefined;
  useEffect(() => { if (ref && moved) go(guestHash(moved, ref.tab === "hardware" ? undefined : ref.tab), { replace: true }); }, [moved?.node]); // eslint-disable-line react-hooks/exhaustive-deps

  const back = <Button variant="ghost" onClick={() => go("#/")} className="!px-3 !py-1.5">← Machines</Button>;
  if (!ref) return <div className="mx-auto max-w-4xl space-y-4">{back}<Notice kind="error">Adresse de machine invalide.</Notice></div>;
  if (conns.isLoading || (id && guests.isLoading)) return <div className="mx-auto max-w-4xl space-y-4">{back}<div className="panel h-40 animate-pulse" /></div>;
  if (!active) return <div className="mx-auto max-w-4xl space-y-4">{back}<Notice kind="error">Aucun cluster connecté. <button className="underline" onClick={onGoConnections}>Ajouter un cluster</button></Notice></div>;
  if (guests.error && !list) return <div className="mx-auto max-w-4xl space-y-4">{back}<Notice kind="error">{(guests.error as Error).message} — <button className="underline" onClick={() => guests.refetch()}>réessayer</button></Notice></div>;
  if (!guest) return <div className="mx-auto max-w-4xl space-y-4">{back}<Notice kind="error">{moved ? "Cette machine a changé de nœud, redirection…" : `Machine ${ref.vmid} introuvable sur le cluster « ${active.name} ».`}</Notice></div>;

  const connId = active.id;
  const status = effectiveStatus(guest), running = status === "running", stopped = status === "stopped";
  const busyLabel = busy[`${guest.node}/${guest.type}/${guest.vmid}`], off = !!busyLabel;
  const name = guest.name ?? String(guest.vmid);
  const dot = busyLabel ? "bg-warn animate-pulse" : running ? "bg-ok dot-live" : stopped ? "bg-muted" : "bg-warn";
  const text = busyLabel ?? (running ? "En marche" : stopped ? "Arrêtée" : (status ?? "Inconnu"));
  const tabs = TABS.filter(([t]) => t !== "cloudinit" || guest.type === "qemu");
  const tab = tabs.some(([t]) => t === ref.tab) ? ref.tab : "hardware";
  void now;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {back}
      {problem && <Notice kind="error">Proxmox ne répond pas ({problem}). Les dernières données connues restent affichées.</Notice>}

      <header className="panel space-y-5 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{name}</h1>
            <p className="text-sm text-muted">#{guest.vmid} · {guest.template ? "Modèle" : guest.type === "qemu" ? "VM" : "LXC"} · {guest.node}</p>
            <div className="mt-2"><GuestTags connId={connId} guest={guest} /></div>
          </div>
          <span className="flex items-center gap-1.5 text-sm"><span className={`size-2 rounded-full ${dot}`} />{text}</span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Gauge label="CPU" value={running ? guest.cpu * 100 : 0} detail={running ? `${(guest.cpu * 100).toFixed(0)} % · ${guest.maxcpu ?? "?"} vCPU` : `${guest.maxcpu ?? "?"} vCPU`} />
          <Gauge label="RAM" value={running ? pct(guest.mem, guest.maxmem) : 0} detail={running ? `${bytes(guest.mem)} / ${bytes(guest.maxmem)}` : bytes(guest.maxmem)} />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-auto text-xs text-muted">{running ? `Actif depuis ${uptime(guest.uptime)}` : "Arrêtée"}</p>
          <Button variant="ghost" onClick={() => setClone(true)} className="!px-3 !py-1.5" title={guest.template ? "Créer une machine à partir de ce modèle" : "Copier cette machine"}>Cloner</Button>
          {!guest.template && <>
            {stopped && <Button onClick={() => run(guest, "start")} disabled={off} className="!px-3 !py-1.5">Démarrer</Button>}
            {running && <>
              <Button variant="ghost" onClick={() => setPending("reboot")} disabled={off} className="!px-3 !py-1.5">Redémarrer</Button>
              <Button variant="ghost" onClick={() => setPending("shutdown")} disabled={off} className="!px-3 !py-1.5">Éteindre</Button>
              <Button variant="danger" onClick={() => setPending("stop")} disabled={off} className="!px-3 !py-1.5" title="Coupure brutale">Forcer</Button>
            </>}
          </>}
        </div>
      </header>

      {guest.template
        ? <div className="rounded-xl border border-line bg-surface2 p-4 text-sm text-muted">Cette machine est un modèle : elle ne se démarre pas et son matériel ne se modifie pas ici. Tu peux la cloner.</div>
        : <>
          <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
            {tabs.map(([id, label]) => (
              <button key={id} role="tab" aria-selected={tab === id} onClick={() => go(guestHash(guest, id === "hardware" ? undefined : id), { replace: true })}
                className={`-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm transition ${tab === id ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg"}`}>{label}</button>
            ))}
          </div>
          {tab === "hardware" && <HardwareTab connId={connId} guest={guest} onDeleted={() => go("#/")} onMigrated={(target) => go(guestHash({ ...guest, node: target }), { replace: true })} />}
          {tab === "metrics" && <GuestCharts connId={connId} node={guest.node} type={guest.type} vmid={guest.vmid} />}
          {tab === "console" && <ConsoleTab connId={connId} guest={guest} />}
          {tab === "snapshots" && <SnapshotsTab connId={connId} guest={guest} running={running} />}
          {tab === "cloudinit" && guest.type === "qemu" && <CloudInitTab connId={connId} guest={guest} />}
          {tab === "backups" && <BackupsTab connId={connId} guest={guest} />}
          {tab === "tasks" && <GuestTasksTab connId={connId} guest={guest} />}
        </>}

      {clone && <CloneDialog connId={connId} guest={guest} nodes={nodes.data ?? []} onClose={() => setClone(false)} />}
      {pending && (
        <ConfirmDialog title={`${CONFIRM[pending].title} « ${name} » ?`} confirmLabel={CONFIRM[pending].verb} danger={pending !== "reboot"}
          onCancel={() => setPending(null)} onConfirm={() => { const a = pending; setPending(null); run(guest, a); }}>
          {CONFIRM[pending].text}
        </ConfirmDialog>
      )}
    </div>
  );
}
