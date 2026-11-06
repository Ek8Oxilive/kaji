import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api, type Guest, type HwConfig, type HwDisk, type HwNet, type HwUpdate } from "../lib/api";
import { mem } from "../lib/format";
import { BootDialog, CdromDialog, CpuDialog, DeleteGuestDialog, DiskAddDialog, DiskDestroyDialog, DiskDetachDialog, DiskMoveDialog, DiskReattachDialog, MemoryDialog, MigrateDialog, NetAddDialog, NetDialog, NetRemoveDialog, ResizeDialog, SwapDialog } from "./HardwareDialogs";
import { useToast } from "./Toast";
import { Button, Notice } from "./ui";

type Dialog =
  | { k: "memory" } | { k: "cpu" } | { k: "swap" } | { k: "boot" } | { k: "netadd" } | { k: "netdel"; net: HwNet }
  | { k: "delete" } | { k: "migrate" } | { k: "diskadd" } | { k: "detach"; disk: HwDisk } | { k: "move"; disk: HwDisk }
  | { k: "reattach"; item: { key: string; volume: string } } | { k: "destroy"; item: { key: string; volume: string } }
  | { k: "net"; net: HwNet } | { k: "cdrom"; disk: HwDisk } | { k: "resize"; disk: HwDisk };

function Row({ label, children, pending, action }: { label: string; children: ReactNode; pending?: string | null; action?: ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-b border-line/60 py-3 last:border-0">
      <div className="w-32 shrink-0 text-sm text-muted">{label}</div>
      <div className="min-w-0 flex-1 text-sm">
        <div className="break-words">{children}</div>
        {pending && <div className="mt-1 inline-block rounded-md bg-warn/15 px-2 py-0.5 text-xs text-warn">En attente : {pending}</div>}
      </div>
      {action}
    </div>
  );
}

const Section = ({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) => (
  <section className="space-y-1">
    <div className="flex items-center justify-between"><h3 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>{action}</div>
    <div>{children}</div>
  </section>
);

const cores = (n: unknown) => `${n} ${Number(n) > 1 ? "cœurs" : "cœur"}`;

const Edit = ({ onClick, label = "Modifier" }: { onClick: () => void; label?: string }) => (
  <Button variant="ghost" onClick={onClick} className="!px-3 !py-1">{label}</Button>
);

/** Onglet « Matériel » de la page Machine. `onDeleted` / `onMigrated` : la machine n'existe plus ici, la page doit changer. */
export function HardwareTab({ connId, guest, onDeleted, onMigrated }: { connId: number; guest: Guest; onDeleted: () => void; onMigrated: (target: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const base = `/api/connections/${connId}/guests/${guest.node}/${guest.type}/${guest.vmid}`;
  const qk = ["hw", connId, guest.node, guest.type, guest.vmid];
  const { data: cfg, error, isLoading, refetch } = useQuery({ queryKey: qk, queryFn: () => api<HwConfig>(`${base}/config`), staleTime: 0 });
  const [dlg, setDlg] = useState<Dialog | null>(null);

  const save = async (body: HwUpdate) => {
    await api(`${base}/config`, { method: "PATCH", body });
    toast("ok", "Configuration enregistrée");
    await qc.invalidateQueries({ queryKey: qk });
  };
  const resized = async () => { toast("ok", "Disque agrandi"); await qc.invalidateQueries({ queryKey: qk }); };

  const pend = (key: string) => {
    const p = cfg?.pending.find((x) => x.key === key);
    return !p ? null : p.delete ? "suppression" : String(p.pending);
  };
  const qemu = guest.type === "qemu";
  const s = cfg?.settings ?? {};
  const disks = cfg?.disks.filter((d) => d.kind === "disk") ?? [];
  const cdroms = cfg?.disks.filter((d) => d.kind === "cdrom") ?? [];

  return (
    <div className="space-y-6">
        {isLoading && <div className="space-y-3">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-surface2" />)}</div>}
        {error && <Notice kind="error">{(error as Error).message} — <button className="underline" onClick={() => refetch()}>réessayer</button></Notice>}

        {cfg && <>
          {cfg.reboot_required && (
            <Notice kind="error">
              Changements en attente : ils s'appliqueront au prochain redémarrage de la machine ({cfg.pending.map((p) => p.key).join(", ")}).
            </Notice>
          )}

          <Section title="Ressources">
            <Row label="Mémoire" pending={pend("memory")} action={<Edit onClick={() => setDlg({ k: "memory" })} />}>
              {mem(s.memory)}{qemu && s.balloon !== undefined && <span className="text-muted"> · minimum {Number(s.balloon) === 0 ? "ballooning désactivé" : mem(s.balloon)}</span>}
            </Row>
            <Row label="Processeurs" pending={pend("cores") ?? pend("sockets") ?? pend("cpu")} action={<Edit onClick={() => setDlg({ k: "cpu" })} />}>
              {qemu
                ? <>{Number(s.cores ?? 1) * Number(s.sockets ?? 1)} vCPU <span className="text-muted">({s.sockets ?? 1} socket{Number(s.sockets ?? 1) > 1 ? "s" : ""} × {cores(s.cores ?? 1)}) · {String(s.cpu ?? "kvm64")}</span></>
                : <>{s.cores ? cores(s.cores) : "illimité"}</>}
            </Row>
            {qemu && <Row label="Démarrage" pending={pend("boot")} action={<Edit onClick={() => setDlg({ k: "boot" })} />}>
              {cfg.boot_order.length ? cfg.boot_order.join(" → ") : <span className="text-muted">ordre par défaut</span>}
            </Row>}
            {!qemu && <Row label="Swap" pending={pend("swap")} action={<Edit onClick={() => setDlg({ k: "swap" })} />}>{mem(s.swap ?? 0)}</Row>}
          </Section>

          <Section title="Disques" action={<Edit label="+ Ajouter" onClick={() => setDlg({ k: "diskadd" })} />}>
            {disks.length === 0 && <p className="py-2 text-sm text-muted">Aucun disque.</p>}
            {disks.map((d) => (
              <Row key={d.key} label={d.key} pending={pend(d.key)} action={<div className="flex flex-wrap justify-end gap-1.5"><Edit label="Agrandir" onClick={() => setDlg({ k: "resize", disk: d })} /><Edit label="Déplacer" onClick={() => setDlg({ k: "move", disk: d })} />{d.key !== "rootfs" && <Edit label="Détacher" onClick={() => setDlg({ k: "detach", disk: d })} />}</div>}>
                {d.storage}:{d.volume} <span className="text-muted">· {d.size ?? "taille inconnue"}</span>
              </Row>
            ))}
          </Section>

          {cfg.unused.length > 0 && (
            <Section title="Disques non utilisés">
              {cfg.unused.map((u) => (
                <Row key={u.key} label={u.key} action={<div className="flex gap-1.5"><Edit label="Rattacher" onClick={() => setDlg({ k: "reattach", item: u })} /><Button variant="danger" onClick={() => setDlg({ k: "destroy", item: u })} className="!px-3 !py-1">Supprimer</Button></div>}>
                  {u.volume} <span className="text-muted">· données conservées</span>
                </Row>
              ))}
            </Section>
          )}

          {qemu && cdroms.length > 0 && (
            <Section title="CD/DVD">
              {cdroms.map((d) => (
                <Row key={d.key} label={d.key} pending={pend(d.key)} action={d.cloudinit ? undefined : <Edit onClick={() => setDlg({ k: "cdrom", disk: d })} />}>
                  {d.cloudinit ? <>Lecteur cloud-init <span className="text-muted">· géré dans l'onglet Cloud-init</span></> : d.empty ? <span className="text-muted">Aucun média</span> : `${d.storage}:${d.volume}`}
                </Row>
              ))}
            </Section>
          )}

          <Section title="Cartes réseau" action={<Edit label="+ Ajouter" onClick={() => setDlg({ k: "netadd" })} />}>
            {cfg.nets.length === 0 && <p className="py-2 text-sm text-muted">Aucune carte réseau.</p>}
            {cfg.nets.map((n) => (
              <Row key={n.key} label={n.name ?? n.key} pending={pend(n.key)} action={<div className="flex gap-1.5"><Edit onClick={() => setDlg({ k: "net", net: n })} /><Button variant="danger" onClick={() => setDlg({ k: "netdel", net: n })} className="!px-3 !py-1" aria-label={`Retirer ${n.key}`}>Retirer</Button></div>}>
                <span>{n.bridge ?? "?"}</span>
                <span className="text-muted">{n.tag ? ` · VLAN ${n.tag}` : ""}{n.firewall ? " · firewall" : ""}{n.model ? ` · ${n.model}` : ""}{n.ip ? ` · ${n.ip}` : ""}</span>
                {n.mac && <div className="font-mono text-xs text-muted">{n.mac}</div>}
              </Row>
            ))}
          </Section>

          <Section title="Emplacement">
            <Row label="Nœud" action={<Button variant="ghost" onClick={() => setDlg({ k: "migrate" })} className="!px-3 !py-1">Migrer</Button>}>
              {guest.node} <span className="text-muted">· déplacer la machine vers un autre nœud du cluster</span>
            </Row>
          </Section>

          <Section title="Zone dangereuse">
            <Row label="Supprimer" action={<Button variant="danger" disabled={guest.status !== "stopped"} onClick={() => setDlg({ k: "delete" })} className="!px-3 !py-1">Supprimer la machine</Button>}>
              <span className="text-muted">{guest.status === "stopped" ? "Détruit la machine et tous ses disques, sans retour possible." : "La machine doit d'abord être arrêtée."}</span>
            </Row>
          </Section>

          <p className="text-xs text-muted">Les ajouts de passthrough PCI/USB et d'autres options avancées ne sont pas gérés.</p>
        </>}

      {cfg && dlg?.k === "memory" && <MemoryDialog cfg={cfg} save={save} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "cpu" && <CpuDialog cfg={cfg} save={save} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "swap" && <SwapDialog cfg={cfg} save={save} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "net" && <NetDialog net={dlg.net} connId={connId} node={guest.node} save={save} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "cdrom" && <CdromDialog disk={dlg.disk} connId={connId} node={guest.node} save={save} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "boot" && <BootDialog cfg={cfg} save={save} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "netadd" && <NetAddDialog cfg={cfg} connId={connId} node={guest.node} base={base} onDone={async () => { toast("ok", "Carte réseau ajoutée"); await qc.invalidateQueries({ queryKey: qk }); }} onClose={() => setDlg(null)} />}
      {dlg?.k === "netdel" && <NetRemoveDialog net={dlg.net} base={base} onDone={async () => { toast("ok", `Carte ${dlg.net.key} retirée`); await qc.invalidateQueries({ queryKey: qk }); }} onClose={() => setDlg(null)} />}
      {dlg?.k === "migrate" && <MigrateDialog connId={connId} node={guest.node} gtype={guest.type} vmid={guest.vmid} name={guest.name ?? String(guest.vmid)}
        running={guest.status === "running"} base={base}
        onDone={async (target) => { toast("ok", `« ${guest.name ?? guest.vmid} » migrée vers ${target}`); await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] }); onMigrated(target); }} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "delete" && <DeleteGuestDialog cfg={cfg} name={guest.name ?? String(guest.vmid)} node={guest.node} connId={connId} base={base}
        onDeleted={async () => { toast("ok", `Machine « ${guest.name ?? guest.vmid} » supprimée`); await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] }); onDeleted(); }} onClose={() => setDlg(null)} />}
      {cfg && dlg?.k === "diskadd" && <DiskAddDialog cfg={cfg} connId={connId} node={guest.node} base={base} onDone={async () => { toast("ok", "Disque ajouté"); await qc.invalidateQueries({ queryKey: qk }); }} onClose={() => setDlg(null)} />}
      {dlg?.k === "detach" && <DiskDetachDialog disk={dlg.disk} base={base} onDone={async () => { toast("ok", `Disque ${dlg.disk.key} détaché (données conservées)`); await qc.invalidateQueries({ queryKey: qk }); }} onClose={() => setDlg(null)} />}
      {dlg?.k === "move" && <DiskMoveDialog disk={dlg.disk} lxc={!qemu} connId={connId} node={guest.node} base={base} onDone={async () => { toast("ok", `Disque ${dlg.disk.key} déplacé`); await qc.invalidateQueries({ queryKey: qk }); }} onClose={() => setDlg(null)} />}
      {dlg?.k === "reattach" && <DiskReattachDialog item={dlg.item} lxc={!qemu} base={base} onDone={async () => { toast("ok", "Disque rattaché"); await qc.invalidateQueries({ queryKey: qk }); }} onClose={() => setDlg(null)} />}
      {dlg?.k === "destroy" && <DiskDestroyDialog item={dlg.item} machine={guest.name ?? String(guest.vmid)} base={base} onDone={async () => { toast("ok", "Disque détruit"); await qc.invalidateQueries({ queryKey: qk }); }} onClose={() => setDlg(null)} />}
      {dlg?.k === "resize" && <ResizeDialog disk={dlg.disk} connPath={base} onDone={resized} onClose={() => setDlg(null)} />}
    </div>
  );
}
