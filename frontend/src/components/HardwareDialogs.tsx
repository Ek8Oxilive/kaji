import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Bridge, type HwConfig, type HwDisk, type HwNet, type HwUpdate, type Iso } from "../lib/api";
import { bytes, mem } from "../lib/format";
import { Modal } from "./Modal";
import { Field } from "./ui";

export type Save = (body: HwUpdate) => Promise<void>;
type Common = { onClose: () => void; save: Save; cfg: HwConfig };

/** Exécute une action, affiche l'erreur dans la fenêtre, ferme en cas de succès. */
export function useSubmit(onClose: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); onClose(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return { busy, error, run };
}

const num = (v: string) => (v.trim() === "" ? NaN : Number(v));

export function MemoryDialog({ cfg, save, onClose }: Common) {
  const qemu = cfg.type === "qemu";
  const [memory, setMemory] = useState(String(cfg.settings.memory ?? ""));
  const [balloon, setBalloon] = useState(String(cfg.settings.balloon ?? ""));
  const { busy, error, run } = useSubmit(onClose);
  const m = num(memory), b = num(balloon);
  const body: HwUpdate = {};
  if (m !== Number(cfg.settings.memory)) body.memory = m;
  if (qemu && !Number.isNaN(b) && b !== Number(cfg.settings.balloon ?? NaN)) body.balloon = b;
  const ok = Number.isInteger(m) && m >= 16 && Object.keys(body).length > 0 && (!("balloon" in body) || (b >= 0 && b <= m));
  return (
    <Modal title="Mémoire" onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Enregistrer" onSubmit={() => run(() => save(body))}>
      <Field label="Mémoire (Mo)" type="number" min={16} step={256} value={memory} onChange={(e) => setMemory(e.target.value)} hint={Number.isFinite(m) ? `= ${mem(m)}` : undefined} autoFocus />
      {qemu && <Field label="Mémoire minimale / ballooning (Mo)" type="number" min={0} value={balloon} onChange={(e) => setBalloon(e.target.value)} hint="0 désactive le ballooning ; doit rester ≤ à la mémoire" />}
    </Modal>
  );
}

export function CpuDialog({ cfg, save, onClose }: Common) {
  const qemu = cfg.type === "qemu";
  const [cores, setCores] = useState(String(cfg.settings.cores ?? 1));
  const [sockets, setSockets] = useState(String(cfg.settings.sockets ?? 1));
  const [type, setType] = useState(String(cfg.settings.cpu ?? ""));
  const { busy, error, run } = useSubmit(onClose);
  const body: HwUpdate = {};
  if (num(cores) !== Number(cfg.settings.cores ?? 1)) body.cores = num(cores);
  if (qemu && num(sockets) !== Number(cfg.settings.sockets ?? 1)) body.sockets = num(sockets);
  if (qemu && type && type !== String(cfg.settings.cpu ?? "")) body.cpu = type;
  const ok = Object.keys(body).length > 0 && Number.isInteger(num(cores)) && num(cores) >= 1 && (!qemu || (Number.isInteger(num(sockets)) && num(sockets) >= 1)) && /^[A-Za-z0-9_-]*$/.test(type);
  return (
    <Modal title="Processeurs" onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Enregistrer" onSubmit={() => run(() => save(body))}>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Cœurs" type="number" min={1} max={512} value={cores} onChange={(e) => setCores(e.target.value)} autoFocus />
        {qemu && <Field label="Sockets" type="number" min={1} max={8} value={sockets} onChange={(e) => setSockets(e.target.value)} />}
      </div>
      {qemu && <>
        <Field label="Type de CPU" list="cpu-types" value={type} onChange={(e) => setType(e.target.value)} placeholder="host" hint="host = performances maximales ; x86-64-v2-AES = bon compromis pour migrer entre nœuds" />
        <datalist id="cpu-types">{["host", "x86-64-v2-AES", "x86-64-v3", "x86-64-v4", "kvm64", "qemu64"].map((t) => <option key={t} value={t} />)}</datalist>
      </>}
      {qemu && <p className="text-sm text-muted">Total : {(num(cores) || 0) * (num(sockets) || 0)} vCPU</p>}
    </Modal>
  );
}

export function SwapDialog({ cfg, save, onClose }: Common) {
  const [swap, setSwap] = useState(String(cfg.settings.swap ?? 0));
  const { busy, error, run } = useSubmit(onClose);
  const s = num(swap);
  const ok = Number.isInteger(s) && s >= 0 && s !== Number(cfg.settings.swap ?? 0);
  return (
    <Modal title="Swap" onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Enregistrer" onSubmit={() => run(() => save({ swap: s }))}>
      <Field label="Swap (Mo)" type="number" min={0} step={128} value={swap} onChange={(e) => setSwap(e.target.value)} autoFocus />
    </Modal>
  );
}

export function NetDialog({ net, connId, node, save, onClose }: Omit<Common, "cfg"> & { net: HwNet; connId: number; node: string }) {
  const nets = useQuery({ queryKey: ["bridges", connId, node], queryFn: () => api<Bridge[]>(`/api/connections/${connId}/nodes/${node}/bridges`), staleTime: 60_000, retry: false });
  const [bridge, setBridge] = useState(net.bridge ?? "");
  const [tag, setTag] = useState(net.tag?.toString() ?? "");
  const [firewall, setFirewall] = useState(net.firewall);
  const { busy, error, run } = useSubmit(onClose);
  const t = num(tag);
  const edit: NonNullable<HwUpdate["nets"]>[string] = {};
  if (bridge && bridge !== net.bridge) edit.bridge = bridge;
  if (tag.trim() === "" && net.tag !== null) edit.clear_tag = true;
  else if (!Number.isNaN(t) && t !== net.tag) edit.tag = t;
  if (firewall !== net.firewall) edit.firewall = firewall;
  const ok = Object.keys(edit).length > 0 && /^[A-Za-z0-9_.-]{1,15}$/.test(bridge) && (tag.trim() === "" || (Number.isInteger(t) && t >= 1 && t <= 4094));

  const list = nets.data;
  const known = list?.find((b) => b.name === bridge);
  const bridges = list?.filter((b) => b.kind === "bridge") ?? [];
  const vnets = list?.filter((b) => b.kind === "vnet") ?? [];
  const label = (b: Bridge) => `${b.name}${b.zone ? ` · zone ${b.zone}` : ""}${b.detail ? ` · ${b.detail}` : ""}`;
  return (
    <Modal title={`Carte réseau ${net.key}`} subtitle={net.mac ? `MAC ${net.mac} (conservée)` : undefined} onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Enregistrer" onSubmit={() => run(() => save({ nets: { [net.key]: edit } }))}>
      {list ? (
        <label className="block space-y-1.5">
          <span className="text-sm text-muted">Réseau (bridge ou VNet SDN)</span>
          <select className="field" value={bridge} onChange={(e) => setBridge(e.target.value)} autoFocus>
            {bridge && !known && <option value={bridge}>{bridge} (actuel, introuvable sur ce nœud)</option>}
            <optgroup label="Bridges">{bridges.map((b) => <option key={b.name} value={b.name}>{label(b)}</option>)}</optgroup>
            {vnets.length > 0 && <optgroup label="VNets SDN">{vnets.map((b) => <option key={b.name} value={b.name}>{label(b)}</option>)}</optgroup>}
          </select>
          {known?.kind === "bridge" && !known.vlan_aware && tag && <span className="block text-xs text-warn">Ce bridge n'est pas « VLAN aware » : l'étiquette VLAN sera ignorée.</span>}
          {known?.kind === "vnet" && <span className="block text-xs text-muted">VNet SDN : le VLAN est géré par la zone, laisse l'étiquette vide.</span>}
        </label>
      ) : (
        <Field label="Bridge" value={bridge} onChange={(e) => setBridge(e.target.value)} placeholder="vmbr0"
          hint={nets.isLoading ? "Chargement de la liste…" : "Liste indisponible : saisie manuelle. Un nom inexistant coupe le réseau de la machine."} autoFocus />
      )}
      <Field label="Étiquette VLAN" type="number" min={1} max={4094} value={tag} onChange={(e) => setTag(e.target.value)} placeholder="aucun" hint="Laisse vide pour retirer le VLAN" />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={firewall} onChange={(e) => setFirewall(e.target.checked)} /> Firewall Proxmox activé
      </label>
    </Modal>
  );
}

export function CdromDialog({ disk, connId, node, save, onClose }: Omit<Common, "cfg"> & { disk: HwDisk; connId: number; node: string }) {
  const isos = useQuery({ queryKey: ["isos", connId, node], queryFn: () => api<Iso[]>(`/api/connections/${connId}/nodes/${node}/isos`), staleTime: 60_000, retry: false });
  const current = disk.empty ? "" : `${disk.storage}:${disk.volume}`;
  const [iso, setIso] = useState(current);
  const { busy, error, run } = useSubmit(onClose);
  const ok = /^[A-Za-z0-9_.-]+:iso\/[A-Za-z0-9_.+ -]+\.iso$/.test(iso);
  const list = isos.data;
  const storages = [...new Set(list?.map((i) => i.storage))];
  return (
    <Modal title={`Lecteur ${disk.key}`} subtitle={disk.empty ? "Aucun média" : `Monté : ${current}`} onClose={onClose} busy={busy} error={error} canSubmit={ok && iso !== current} submitLabel="Monter" onSubmit={() => run(() => save({ cdroms: { [disk.key]: { iso } } }))}>
      {list && list.length > 0 ? (
        <label className="block space-y-1.5">
          <span className="text-sm text-muted">Image ISO</span>
          <select className="field" value={iso} onChange={(e) => setIso(e.target.value)} autoFocus>
            <option value="" disabled>Choisir une image…</option>
            {iso && !list.some((i) => i.volid === iso) && <option value={iso}>{iso} (actuel)</option>}
            {storages.map((st) => (
              <optgroup key={st} label={st}>
                {list.filter((i) => i.storage === st).map((i) => <option key={i.volid} value={i.volid}>{i.name}{i.size ? ` · ${bytes(i.size)}` : ""}</option>)}
              </optgroup>
            ))}
          </select>
        </label>
      ) : (
        <Field label="Image ISO" value={iso} onChange={(e) => setIso(e.target.value)} placeholder="local:iso/debian-12.iso"
          hint={isos.isLoading ? "Chargement de la liste…" : list ? "Aucune image ISO trouvée sur ce nœud. Saisie manuelle : stockage:iso/nom.iso" : "Liste indisponible : saisie manuelle (stockage:iso/nom.iso)"} autoFocus />
      )}
      {!disk.empty && (
        <button type="button" disabled={busy} className="text-sm text-accent underline" onClick={() => run(() => save({ cdroms: { [disk.key]: { iso: null } } }))}>Éjecter le média</button>
      )}
    </Modal>
  );
}

export function ResizeDialog({ disk, connPath, onDone, onClose }: { disk: HwDisk; connPath: string; onDone: () => void; onClose: () => void }) {
  const [gb, setGb] = useState("1");
  const [sure, setSure] = useState(false);
  const { busy, error, run } = useSubmit(onClose);
  const n = num(gb);
  const ok = Number.isInteger(n) && n >= 1 && n <= 4096 && sure;
  return (
    <Modal title={`Agrandir ${disk.key}`} subtitle={`${disk.storage}:${disk.volume} · actuellement ${disk.size ?? "?"}`} danger onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel={`Ajouter ${Number.isFinite(n) ? n : "?"} Go`}
      onSubmit={() => run(async () => { await api(`${connPath}/resize`, { method: "POST", body: { disk: disk.key, add_gb: n, confirm: true } }); onDone(); })}>
      <Field label="Espace à ajouter (Go)" type="number" min={1} max={4096} value={gb} onChange={(e) => setGb(e.target.value)} autoFocus />
      <div className="rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm">
        <strong>Irréversible.</strong> Proxmox ne sait pas réduire un disque. Le système invité devra aussi étendre sa partition pour utiliser l'espace ajouté.
        <label className="mt-2 flex items-start gap-2"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={sure} onChange={(e) => setSure(e.target.checked)} /> Je comprends que je ne pourrai pas revenir en arrière.</label>
      </div>
    </Modal>
  );
}

export function NetAddDialog({ cfg, connId, node, base, onDone, onClose }: { cfg: HwConfig; connId: number; node: string; base: string; onDone: () => Promise<void>; onClose: () => void }) {
  const lxc = cfg.type === "lxc";
  const nets = useQuery({ queryKey: ["bridges", connId, node], queryFn: () => api<Bridge[]>(`/api/connections/${connId}/nodes/${node}/bridges`), staleTime: 60_000, retry: false });
  const [bridge, setBridge] = useState("");
  const [model, setModel] = useState("virtio");
  const [tag, setTag] = useState("");
  const [firewall, setFirewall] = useState(false);
  const [ipMode, setIpMode] = useState<"dhcp" | "static" | "none">("dhcp");
  const [ip, setIp] = useState("");
  const [gw, setGw] = useState("");
  const { busy, error, run } = useSubmit(onClose);
  const list = nets.data;
  const chosen = bridge || list?.[0]?.name || "";
  const t = num(tag);
  const tagOk = tag.trim() === "" || (Number.isInteger(t) && t >= 1 && t <= 4094);
  const ipOk = !lxc || ipMode !== "static" || (/^[0-9a-fA-F:.]+\/\d{1,3}$/.test(ip) && (gw === "" || /^[0-9a-fA-F:.]+$/.test(gw)));
  const ok = /^[A-Za-z0-9_.-]{1,15}$/.test(chosen) && tagOk && ipOk;
  const body = { bridge: chosen, tag: tag.trim() ? t : undefined, firewall, ...(lxc ? { ip: ipMode === "dhcp" ? "dhcp" : ipMode === "static" ? ip : undefined, gateway: ipMode === "static" && gw ? gw : undefined } : { model }) };
  const label = (b: Bridge) => `${b.name}${b.zone ? ` · zone ${b.zone}` : ""}${b.detail ? ` · ${b.detail}` : ""}`;
  return (
    <Modal title="Ajouter une carte réseau" subtitle="L'adresse MAC est attribuée par Proxmox." onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Ajouter"
      onSubmit={() => run(async () => { await api(`${base}/nets`, { method: "POST", body }); await onDone(); })}>
      {list ? (
        <label className="block space-y-1.5">
          <span className="text-sm text-muted">Réseau (bridge ou VNet SDN)</span>
          <select className="field" value={chosen} onChange={(e) => setBridge(e.target.value)} autoFocus>
            <optgroup label="Bridges">{list.filter((b) => b.kind === "bridge").map((b) => <option key={b.name} value={b.name}>{label(b)}</option>)}</optgroup>
            {list.some((b) => b.kind === "vnet") && <optgroup label="VNets SDN">{list.filter((b) => b.kind === "vnet").map((b) => <option key={b.name} value={b.name}>{label(b)}</option>)}</optgroup>}
          </select>
        </label>
      ) : <Field label="Bridge" value={bridge} onChange={(e) => setBridge(e.target.value)} placeholder="vmbr0" hint={nets.isLoading ? "Chargement…" : "Liste indisponible : saisie manuelle"} autoFocus />}
      {!lxc && (
        <label className="block space-y-1.5">
          <span className="text-sm text-muted">Modèle</span>
          <select className="field" value={model} onChange={(e) => setModel(e.target.value)}>{["virtio", "e1000", "e1000e", "rtl8139", "vmxnet3"].map((m) => <option key={m}>{m}</option>)}</select>
        </label>
      )}
      <Field label="Étiquette VLAN" type="number" min={1} max={4094} value={tag} onChange={(e) => setTag(e.target.value)} placeholder="aucun" />
      {lxc && <>
        <label className="block space-y-1.5">
          <span className="text-sm text-muted">Adresse IP</span>
          <select className="field" value={ipMode} onChange={(e) => setIpMode(e.target.value as typeof ipMode)}><option value="dhcp">DHCP</option><option value="static">Statique</option><option value="none">Aucune (à configurer dans le conteneur)</option></select>
        </label>
        {ipMode === "static" && <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Adresse (CIDR)" value={ip} onChange={(e) => setIp(e.target.value)} placeholder="192.168.1.50/24" hint="Avec le masque" />
          <Field label="Passerelle (facultatif)" value={gw} onChange={(e) => setGw(e.target.value)} placeholder="192.168.1.1" />
        </div>}
      </>}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-[var(--accent)]" checked={firewall} onChange={(e) => setFirewall(e.target.checked)} /> Firewall Proxmox activé</label>
    </Modal>
  );
}

export function NetRemoveDialog({ net, base, onDone, onClose }: { net: HwNet; base: string; onDone: () => Promise<void>; onClose: () => void }) {
  const { busy, error, run } = useSubmit(onClose);
  return (
    <Modal title={`Retirer la carte ${net.key} ?`} danger onClose={onClose} busy={busy} error={error} submitLabel="Retirer"
      onSubmit={() => run(async () => { await api(`${base}/nets/${net.key}?confirm=true`, { method: "DELETE" }); await onDone(); })}>
      <p className="text-sm text-muted">La machine perdra l'accès au réseau <strong className="text-fg">{net.bridge}</strong> par cette carte.</p>
      <div className="rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm">L'adresse MAC{net.mac ? <> <span className="font-mono">{net.mac}</span></> : ""} sera perdue : une carte ajoutée plus tard en recevra une autre (réservations DHCP à refaire).</div>
    </Modal>
  );
}

export function BootDialog({ cfg, save, onClose }: Common) {
  const devices = [...cfg.disks.map((d) => ({ key: d.key, label: d.kind === "cdrom" ? `${d.key} · CD/DVD ${d.empty ? "(vide)" : `${d.storage}:${d.volume}`}` : `${d.key} · disque ${d.size ?? ""}` })),
    ...cfg.nets.map((n) => ({ key: n.key, label: `${n.key} · réseau ${n.bridge ?? ""}` }))];
  const known = new Map(devices.map((d) => [d.key, d.label]));
  const initial = cfg.boot_order.filter((k) => known.has(k));
  const [order, setOrder] = useState<string[]>([...initial, ...devices.map((d) => d.key).filter((k) => !initial.includes(k))]);
  const [enabled, setEnabled] = useState<Set<string>>(new Set(initial));
  const { busy, error, run } = useSubmit(onClose);
  const move = (i: number, d: number) => setOrder((o) => { const n = [...o]; [n[i], n[i + d]] = [n[i + d], n[i]]; return n; });
  const result = order.filter((k) => enabled.has(k));
  const changed = result.join(";") !== initial.join(";");
  return (
    <Modal title="Ordre de démarrage" subtitle="La machine essaie les périphériques cochés, de haut en bas." onClose={onClose} busy={busy} error={error}
      canSubmit={result.length > 0 && changed} submitLabel="Enregistrer" onSubmit={() => run(() => save({ boot: result }))}>
      <ol className="space-y-1.5">
        {order.map((k, i) => (
          <li key={k} className="flex items-center gap-2 rounded-xl border border-line bg-surface2 px-3 py-2 text-sm">
            <input type="checkbox" aria-label={`Démarrer sur ${k}`} className="size-4 accent-[var(--accent)]" checked={enabled.has(k)}
              onChange={(e) => setEnabled((s) => { const n = new Set(s); if (e.target.checked) n.add(k); else n.delete(k); return n; })} />
            <span className={`flex-1 truncate ${enabled.has(k) ? "" : "text-muted"}`}>{known.get(k)}</span>
            <button type="button" aria-label="Monter" disabled={i === 0} onClick={() => move(i, -1)} className="rounded px-2 py-0.5 text-muted hover:text-fg disabled:opacity-30">↑</button>
            <button type="button" aria-label="Descendre" disabled={i === order.length - 1} onClick={() => move(i, 1)} className="rounded px-2 py-0.5 text-muted hover:text-fg disabled:opacity-30">↓</button>
          </li>
        ))}
      </ol>
      {result.length === 0 && <p className="text-sm text-danger">Coche au moins un périphérique.</p>}
    </Modal>
  );
}
