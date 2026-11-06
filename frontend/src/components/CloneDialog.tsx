import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Guest, type NodeInfo, type StorageInfo } from "../lib/api";
import { bytes } from "../lib/format";
import { runTask } from "../lib/tasks";
import { useSubmit } from "./HardwareDialogs";
import { Modal } from "./Modal";
import { PoolField } from "./PoolField";
import { useToast } from "./Toast";
import { Field } from "./ui";

export function CloneDialog({ connId, guest, nodes, onClose }: { connId: number; guest: Guest; nodes: NodeInfo[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const lxc = guest.type === "lxc";
  const base = `/api/connections/${connId}`;
  const [name, setName] = useState(`${guest.name ?? guest.vmid}-clone`);
  const [newid, setNewid] = useState("");
  const [target, setTarget] = useState(guest.node);
  const [full, setFull] = useState(true);
  const [storage, setStorage] = useState("");
  const [pool, setPool] = useState("");
  const [description, setDescription] = useState("");
  const { busy, error, run } = useSubmit(onClose);

  const nextId = useQuery({ queryKey: ["nextid", connId], queryFn: () => api<{ vmid: number }>(`${base}/nextid`), staleTime: 0, retry: false });
  const stores = useQuery({ queryKey: ["storages", connId, target, lxc ? "rootdir" : "images"], retry: false, staleTime: 30_000,
    queryFn: () => api<StorageInfo[]>(`${base}/nodes/${target}/storages?content=${lxc ? "rootdir" : "images"}`) });

  const id = newid || String(nextId.data?.vmid ?? "");
  const ok = /^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$/.test(name) && Number.isInteger(Number(id)) && Number(id) >= 100 && Number(id) !== guest.vmid;
  const body = { name, newid: Number(id), full, ...(target !== guest.node ? { target_node: target } : {}),
    ...(full && storage ? { storage } : {}), ...(pool ? { pool } : {}), description };

  return (
    <Modal title={guest.template ? `Créer depuis le modèle « ${guest.name} »` : `Cloner « ${guest.name ?? guest.vmid} »`} subtitle={`Source : #${guest.vmid} · ${lxc ? "LXC" : "VM"} · ${guest.node}`}
      onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Cloner"
      onSubmit={() => run(async () => {
        await runTask(connId, guest.node, () => api(`${base}/guests/${guest.node}/${guest.type}/${guest.vmid}/clone`, { method: "POST", body }), "Clonage");
        toast("ok", `« ${name} » créée (#${id})`);
        await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] });
      })}>
      <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
        <Field label={lxc ? "Nom d'hôte" : "Nom"} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <Field label="Identifiant" type="number" min={100} value={id} onChange={(e) => setNewid(e.target.value)} hint={nextId.data ? `Libre : ${nextId.data.vmid}` : undefined} />
      </div>
      <label className="block space-y-1.5">
        <span className="text-sm text-muted">Nœud de destination</span>
        <select className="field" value={target} onChange={(e) => { setTarget(e.target.value); setStorage(""); }}>{nodes.map((n) => <option key={n.node} value={n.node}>{n.node}{n.node === guest.node ? " (même nœud)" : ""}</option>)}</select>
      </label>
      <fieldset className="space-y-2" aria-label="Mode de clonage">
        <label className="flex items-start gap-2 text-sm"><input type="radio" name="mode" className="mt-0.5 size-4 accent-[var(--accent)]" checked={full} onChange={() => setFull(true)} />
          <span>Clone complet <span className="block text-xs text-muted">Copie tous les disques : indépendant de la source, mais plus long et plus volumineux.</span></span></label>
        <label className={`flex items-start gap-2 text-sm ${guest.template ? "" : "opacity-50"}`}><input type="radio" name="mode" className="mt-0.5 size-4 accent-[var(--accent)]" checked={!full} disabled={!guest.template} onChange={() => { setFull(false); setStorage(""); }} />
          <span>Clone lié <span className="block text-xs text-muted">{guest.template ? "Instantané et léger, mais dépend du modèle (ne pas le supprimer)." : "Réservé aux modèles."}</span></span></label>
      </fieldset>
      {full && (
        <label className="block space-y-1.5">
          <span className="text-sm text-muted">Stockage de destination</span>
          <select className="field" value={storage} onChange={(e) => setStorage(e.target.value)}>
            <option value="">Même stockage que la source</option>
            {stores.data?.map((s) => <option key={s.storage} value={s.storage} disabled={!s.active}>{s.storage}{s.type ? ` (${s.type})` : ""}{s.avail ? ` · ${bytes(s.avail)} libres` : ""}</option>)}
          </select>
        </label>
      )}
      <PoolField connId={connId} value={pool} onChange={setPool} />
      <Field label="Description (facultatif)" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} />
      {guest.status === "running" && !guest.template && <p className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn">La machine est en marche : la copie sera celle d'un instant donné, comme après une coupure de courant. Pour une copie fiable, éteins-la d'abord.</p>}
      {busy && <p className="text-sm text-muted">Clonage en cours, cela peut prendre du temps selon la taille des disques…</p>}
    </Modal>
  );
}
