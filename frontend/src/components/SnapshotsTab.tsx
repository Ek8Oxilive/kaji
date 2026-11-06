import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest, type SnapshotList } from "../lib/api";
import { runTask } from "../lib/tasks";
import { useSubmit } from "./HardwareDialogs";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

const stamp = () => { const d = new Date(), p = (n: number) => String(n).padStart(2, "0"); return `snap-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`; };
const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }) : "—");

type Dlg = { k: "create" } | { k: "delete"; name: string } | { k: "rollback"; name: string };

export function SnapshotsTab({ connId, guest, running }: { connId: number; guest: Guest; running: boolean }) {
  const base = `/api/connections/${connId}/guests/${guest.node}/${guest.type}/${guest.vmid}/snapshots`;
  const qk = ["snaps", connId, guest.node, guest.type, guest.vmid];
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading, refetch } = useQuery({ queryKey: qk, queryFn: () => api<SnapshotList>(base), staleTime: 0 });
  const [dlg, setDlg] = useState<Dlg | null>(null);
  const done = async (msg: string) => { toast("ok", msg); await qc.invalidateQueries({ queryKey: qk }); };
  const label = guest.name ?? String(guest.vmid);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">Points de restauration de la machine. Un snapshot ne remplace pas une sauvegarde : il vit sur le même stockage.</p>
        <Button onClick={() => setDlg({ k: "create" })} className="shrink-0">Créer</Button>
      </div>

      {isLoading && <div className="space-y-3">{[0, 1].map((i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-surface2" />)}</div>}
      {error && <Notice kind="error">{(error as Error).message} — <button className="underline" onClick={() => refetch()}>réessayer</button></Notice>}
      {data && data.snapshots.length === 0 && <div className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-muted">Aucun snapshot pour cette machine.</div>}

      <ol className="space-y-2">
        {data?.snapshots.map((s) => (
          <li key={s.name} className="panel space-y-2 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{s.name}</span>
                  {s.vmstate && <span className="rounded-md border border-line px-1.5 text-[0.7rem] uppercase tracking-wide text-muted">Avec mémoire</span>}
                  {data.current_parent === s.name && <span className="rounded-md bg-accent/15 px-1.5 text-[0.7rem] uppercase tracking-wide text-accent">Vous êtes ici</span>}
                </div>
                <p className="text-xs text-muted">{when(s.time)}{s.parent ? ` · après ${s.parent}` : ""}</p>
                {s.description && <p className="mt-1 text-sm">{s.description}</p>}
              </div>
              <div className="flex shrink-0 gap-1.5">
                <Button variant="ghost" className="!px-3 !py-1" onClick={() => setDlg({ k: "rollback", name: s.name })}>Restaurer</Button>
                <Button variant="danger" className="!px-3 !py-1" onClick={() => setDlg({ k: "delete", name: s.name })}>Supprimer</Button>
              </div>
            </div>
          </li>
        ))}
      </ol>

      {dlg?.k === "create" && <CreateDialog guest={guest} running={running} onClose={() => setDlg(null)}
        onCreate={async (b) => { await runTask(connId, guest.node, () => api(base, { method: "POST", body: b }), "Snapshot"); await done(`Snapshot « ${b.name} » créé`); }} />}

      {dlg?.k === "delete" && <DeleteDialog name={dlg.name} onClose={() => setDlg(null)}
        onDelete={async () => { await runTask(connId, guest.node, () => api(`${base}/${dlg.name}?confirm=true`, { method: "DELETE" }), "Suppression"); await done(`Snapshot « ${dlg.name} » supprimé`); }} />}

      {dlg?.k === "rollback" && <RollbackDialog name={dlg.name} machine={label} running={running} onClose={() => setDlg(null)}
        onRollback={async () => { await runTask(connId, guest.node, () => api(`${base}/${dlg.name}/rollback`, { method: "POST", body: { confirm: true } }), "Restauration"); await done(`Machine restaurée à « ${dlg.name} »`); qc.invalidateQueries({ queryKey: ["hw", connId, guest.node, guest.type, guest.vmid] }); qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] }); }} />}
    </div>
  );
}

function CreateDialog({ guest, running, onClose, onCreate }: { guest: Guest; running: boolean; onClose: () => void; onCreate: (b: { name: string; description: string; vmstate: boolean }) => Promise<void> }) {
  const [name, setName] = useState(stamp());
  const [description, setDescription] = useState("");
  const [vmstate, setVmstate] = useState(false);
  const { busy, error, run } = useSubmit(onClose);
  const ok = /^[A-Za-z][A-Za-z0-9_-]{1,39}$/.test(name);
  return (
    <Modal title="Créer un snapshot" onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Créer" onSubmit={() => run(() => onCreate({ name, description, vmstate }))}>
      <Field label="Nom" value={name} onChange={(e) => setName(e.target.value)} hint="Lettres, chiffres, - et _ ; commence par une lettre (2 à 40 caractères)" autoFocus />
      <Field label="Description (facultatif)" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} placeholder="avant la mise à jour de…" />
      {guest.type === "qemu" && running && (
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={vmstate} onChange={(e) => setVmstate(e.target.checked)} />
          <span>Inclure la mémoire <span className="block text-xs text-muted">Restaure la machine en marche, plus long à créer et plus volumineux.</span></span>
        </label>
      )}
      {busy && <p className="text-sm text-muted">Création en cours, cela peut prendre quelques secondes…</p>}
    </Modal>
  );
}

function DeleteDialog({ name, onClose, onDelete }: { name: string; onClose: () => void; onDelete: () => Promise<void> }) {
  const { busy, error, run } = useSubmit(onClose);
  return (
    <Modal title={`Supprimer « ${name} » ?`} danger onClose={onClose} busy={busy} error={error} submitLabel="Supprimer" onSubmit={() => run(onDelete)}>
      <p className="text-sm text-muted">Ce point de restauration sera définitivement supprimé. La machine elle-même n'est pas touchée.</p>
    </Modal>
  );
}

function RollbackDialog({ name, machine, running, onClose, onRollback }: { name: string; machine: string; running: boolean; onClose: () => void; onRollback: () => Promise<void> }) {
  const [typed, setTyped] = useState("");
  const { busy, error, run } = useSubmit(onClose);
  return (
    <Modal title={`Restaurer « ${name} »`} danger onClose={onClose} busy={busy} error={error} canSubmit={typed === machine} submitLabel="Restaurer" onSubmit={() => run(onRollback)}>
      <div className="rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm">
        <strong>Tout ce qui a changé depuis ce snapshot sera perdu</strong> : fichiers, configuration, données.{running && " La machine sera arrêtée pendant l'opération."}
      </div>
      <Field label={`Pour confirmer, retape le nom de la machine : ${machine}`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoFocus />
    </Modal>
  );
}

