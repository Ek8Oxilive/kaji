import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Bridge, type Iso, type NodeInfo, type StorageInfo, type VmCreateBody } from "../lib/api";
import { bytes } from "../lib/format";
import { runTask, WARN_SUFFIX } from "../lib/tasks";
import { useSubmit } from "./HardwareDialogs";
import { PoolField } from "./PoolField";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

const OS = [
  ["l26", "Linux (noyau 2.6 et plus)"], ["win11", "Windows 11 / 2022 (UEFI + TPM)"], ["win10", "Windows 10 / 2016 / 2019"],
  ["win8", "Windows 8 / 2012"], ["win7", "Windows 7 / 2008"], ["l24", "Linux (noyau 2.4)"], ["other", "Autre"],
] as const;
const STEPS = ["Général", "Matériel", "Réseau", "Récapitulatif"];
const MEM = [512, 1024, 2048, 4096, 8192, 16384];

const Select = ({ label, hint, children, ...p }: { label: string; hint?: string; children: ReactNode } & React.SelectHTMLAttributes<HTMLSelectElement>) => (
  <label className="block space-y-1.5">
    <span className="text-sm text-muted">{label}</span>
    <select {...p} className="field">{children}</select>
    {hint && <span className="block text-xs text-muted">{hint}</span>}
  </label>
);
const Check = ({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) => (
  <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={checked} onChange={(e) => onChange(e.target.checked)} /><span>{children}</span></label>
);

type Form = {
  node: string; name: string; vmid: string; pool: string; ostype: string; description: string;
  cores: string; sockets: string; memory: string; cpu: string; noDisk: boolean; storage: string; size: string; iso: string; agent: boolean;
  noNet: boolean; bridge: string; model: string; tag: string; firewall: boolean; start: boolean;
};

export function CreateVmWizard({ connId, nodes, onClose }: { connId: number; nodes: NodeInfo[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [f, setF] = useState<Form>({
    node: nodes[0]?.node ?? "", name: "", vmid: "", pool: "", ostype: "l26", description: "",
    cores: "2", sockets: "1", memory: "2048", cpu: "x86-64-v2-AES", noDisk: false, storage: "", size: "16", iso: "", agent: false,
    noNet: false, bridge: "", model: "virtio", tag: "", firewall: false, start: false,
  });
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const { busy, error, run } = useSubmit(onClose);
  const base = `/api/connections/${connId}`;
  const q = { staleTime: 30_000, retry: false } as const;

  const nextId = useQuery({ queryKey: ["nextid", connId], queryFn: () => api<{ vmid: number }>(`${base}/nextid`), ...q, staleTime: 0 });
  const stores = useQuery({ queryKey: ["storages", connId, f.node, "images"], queryFn: () => api<StorageInfo[]>(`${base}/nodes/${f.node}/storages?content=images`), enabled: !!f.node, ...q });
  const isos = useQuery({ queryKey: ["isos", connId, f.node], queryFn: () => api<Iso[]>(`${base}/nodes/${f.node}/isos`), enabled: !!f.node, ...q });
  const bridges = useQuery({ queryKey: ["bridges", connId, f.node], queryFn: () => api<Bridge[]>(`${base}/nodes/${f.node}/bridges`), enabled: !!f.node, ...q });

  useEffect(() => { if (nextId.data && !f.vmid) set("vmid", String(nextId.data.vmid)); }, [nextId.data]);          // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (stores.data?.length && !stores.data.some((s) => s.storage === f.storage)) set("storage", stores.data[0].storage); }, [stores.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (bridges.data?.length && !bridges.data.some((b) => b.name === f.bridge)) set("bridge", bridges.data[0].name); }, [bridges.data]);    // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { set("iso", ""); }, [f.node]);                                                                                                           // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const int = (v: string) => (v.trim() === "" ? NaN : Number(v));
  const win11 = f.ostype === "win11";
  const valid = [
    /^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$/.test(f.name) && !!f.node && Number.isInteger(int(f.vmid)) && int(f.vmid) >= 100,
    int(f.cores) >= 1 && int(f.sockets) >= 1 && int(f.memory) >= 16 && /^[A-Za-z0-9_-]{1,40}$/.test(f.cpu)
      && (f.noDisk ? !win11 : !!f.storage && int(f.size) >= 1 && int(f.size) <= 65536),
    f.noNet || (/^[A-Za-z0-9_.-]{1,15}$/.test(f.bridge) && (f.tag.trim() === "" || (int(f.tag) >= 1 && int(f.tag) <= 4094))),
    true,
  ];

  const body = (): VmCreateBody => ({
    name: f.name, vmid: int(f.vmid), memory: int(f.memory), cores: int(f.cores), sockets: int(f.sockets), cpu: f.cpu, ostype: f.ostype,
    ...(f.noDisk ? {} : { disk: { storage: f.storage, size_gb: int(f.size) } }),
    ...(f.noNet ? {} : { net: { bridge: f.bridge, model: f.model, firewall: f.firewall, ...(f.tag.trim() ? { tag: int(f.tag) } : {}) } }),
    ...(f.iso ? { iso: f.iso } : {}), ...(f.pool ? { pool: f.pool } : {}),
    agent: f.agent, start: f.start, description: f.description,
  });

  const create = () => run(async () => {
    const t = await runTask(connId, f.node, () => api(`${base}/nodes/${f.node}/qemu`, { method: "POST", body: body() }), "Création");
    toast("ok", `Machine « ${f.name} » créée (#${f.vmid})${t.warnings ? WARN_SUFFIX : ""}`);
    await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] });
  });

  const lbl = (b: Bridge) => `${b.name}${b.zone ? ` · zone ${b.zone}` : ""}${b.detail ? ` · ${b.detail}` : ""}`;

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4">   {/* pas de fermeture au clic sur le fond : un formulaire en plusieurs étapes ne doit pas se perdre par accident */}
      <div role="dialog" aria-modal="true" aria-label="Créer une machine virtuelle" className="panel rise flex max-h-[92vh] w-full max-w-2xl flex-col">
        <header className="space-y-4 border-b border-line p-6 pb-4">
          <h2 className="text-xl font-semibold tracking-tight">Nouvelle machine virtuelle</h2>
          <ol className="flex gap-2 text-sm" aria-label="Étapes">
            {STEPS.map((s, i) => (
              <li key={s} aria-current={i === step ? "step" : undefined} className={`flex flex-1 items-center gap-2 rounded-lg px-2 py-1.5 ${i === step ? "bg-accent text-accentfg font-medium" : i < step ? "text-ok" : "text-muted"}`}>
                <span className="grid size-5 shrink-0 place-items-center rounded-full border border-current text-xs">{i < step ? "✓" : i + 1}</span><span className="hidden truncate sm:inline">{s}</span>
              </li>
            ))}
          </ol>
        </header>

        <div className="space-y-4 overflow-y-auto p-6">
          {step === 0 && <>
            <Select label="Nœud" value={f.node} onChange={(e) => set("node", e.target.value)}>{nodes.map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}</Select>
            <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
              <Field label="Nom" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="ma-vm" hint="Lettres, chiffres, - et . (sans espace)" autoFocus />
              <Field label="Identifiant" type="number" min={100} value={f.vmid} onChange={(e) => set("vmid", e.target.value)} hint={nextId.data ? `Libre : ${nextId.data.vmid}` : undefined} />
            </div>
            <PoolField connId={connId} value={f.pool} onChange={(v) => set("pool", v)} />
            {!f.pool && <Notice kind="error">Aucun pool choisi : la machine sera créée hors de tout pool.</Notice>}
            <Select label="Système d'exploitation" value={f.ostype} onChange={(e) => set("ostype", e.target.value)}>{OS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
            <Field label="Description (facultatif)" value={f.description} onChange={(e) => set("description", e.target.value)} maxLength={200} />
          </>}

          {step === 1 && <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label="Cœurs" type="number" min={1} max={512} value={f.cores} onChange={(e) => set("cores", e.target.value)} />
              <Field label="Sockets" type="number" min={1} max={8} value={f.sockets} onChange={(e) => set("sockets", e.target.value)} />
            </div>
            <div className="space-y-2">
              <Field label="Mémoire (Mo)" type="number" min={16} step={256} value={f.memory} onChange={(e) => set("memory", e.target.value)} />
              <div className="flex flex-wrap gap-1.5">{MEM.map((m) => <button key={m} type="button" onClick={() => set("memory", String(m))} className={`rounded-lg border px-2.5 py-1 text-xs transition ${f.memory === String(m) ? "border-accent text-accent" : "border-line text-muted hover:text-fg"}`}>{m >= 1024 ? `${m / 1024} Go` : `${m} Mo`}</button>)}</div>
            </div>
            <Field label="Type de CPU" list="wiz-cpu" value={f.cpu} onChange={(e) => set("cpu", e.target.value)} />
            <datalist id="wiz-cpu">{["x86-64-v2-AES", "host", "x86-64-v3", "x86-64-v4", "kvm64"].map((t) => <option key={t} value={t} />)}</datalist>
            <div className="space-y-3 rounded-xl border border-line p-4">
              <Check checked={!f.noDisk} onChange={(v) => set("noDisk", !v)}>Ajouter un disque</Check>
              {!f.noDisk && (
                <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
                  <Select label="Stockage" value={f.storage} onChange={(e) => set("storage", e.target.value)} hint={stores.isError ? "Liste indisponible" : undefined}>
                    {stores.data?.map((s) => <option key={s.storage} value={s.storage} disabled={!s.active}>{s.storage}{s.type ? ` (${s.type})` : ""}{s.avail ? ` · ${bytes(s.avail)} libres` : ""}</option>)}
                  </Select>
                  <Field label="Taille (Go)" type="number" min={1} max={65536} value={f.size} onChange={(e) => set("size", e.target.value)} />
                </div>
              )}
              {f.noDisk && win11 && <p className="text-sm text-danger">Windows 11 demande un disque (il héberge aussi le disque EFI et le TPM).</p>}
            </div>
            <Select label="Image ISO (facultatif)" value={f.iso} onChange={(e) => set("iso", e.target.value)} hint={isos.isError ? "Liste indisponible" : "Monte l'image dans un lecteur CD/DVD et la place dans l'ordre de démarrage."}>
              <option value="">Aucune</option>{isos.data?.map((i) => <option key={i.volid} value={i.volid}>{i.volid.replace(/^.*:iso\//, "")} · {i.storage}</option>)}
            </Select>
            <Check checked={f.agent} onChange={(v) => set("agent", v)}>Agent invité QEMU <span className="block text-xs text-muted">À activer si l'agent est installé dans la machine (arrêt propre, adresse IP visible).</span></Check>
            {win11 && <Notice kind="ok">Windows 11 : UEFI, TPM v2 et disque EFI seront ajoutés automatiquement.</Notice>}
          </>}

          {step === 2 && <>
            <Check checked={!f.noNet} onChange={(v) => set("noNet", !v)}>Ajouter une carte réseau</Check>
            {!f.noNet && <>
              <Select label="Réseau (bridge ou VNet SDN)" value={f.bridge} onChange={(e) => set("bridge", e.target.value)} hint={bridges.isError ? "Liste indisponible" : undefined}>
                <optgroup label="Bridges">{bridges.data?.filter((b) => b.kind === "bridge").map((b) => <option key={b.name} value={b.name}>{lbl(b)}</option>)}</optgroup>
                {bridges.data?.some((b) => b.kind === "vnet") && <optgroup label="VNets SDN">{bridges.data.filter((b) => b.kind === "vnet").map((b) => <option key={b.name} value={b.name}>{lbl(b)}</option>)}</optgroup>}
              </Select>
              <div className="grid gap-4 sm:grid-cols-2">
                <Select label="Modèle" value={f.model} onChange={(e) => set("model", e.target.value)} hint="virtio est le plus rapide (pilote requis sous Windows)">
                  {["virtio", "e1000", "e1000e", "rtl8139", "vmxnet3"].map((m) => <option key={m} value={m}>{m}</option>)}
                </Select>
                <Field label="Étiquette VLAN" type="number" min={1} max={4094} value={f.tag} onChange={(e) => set("tag", e.target.value)} placeholder="aucun" />
              </div>
              <Check checked={f.firewall} onChange={(v) => set("firewall", v)}>Firewall Proxmox activé</Check>
            </>}
          </>}

          {step === 3 && <>
            <dl className="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-2 text-sm">
              {([
                ["Nom", `${f.name} (#${f.vmid})`], ["Nœud", f.node], ["Pool", f.pool || "aucun"], ["Système", OS.find(([v]) => v === f.ostype)?.[1] ?? f.ostype],
                ["Processeur", `${int(f.cores) * int(f.sockets)} vCPU (${f.sockets} × ${f.cores}) · ${f.cpu}`], ["Mémoire", `${f.memory} Mo`],
                ["Disque", f.noDisk ? "aucun" : `${f.size} Go sur ${f.storage}`], ["ISO", f.iso || "aucune"],
                ["Réseau", f.noNet ? "aucune carte" : `${f.model} sur ${f.bridge}${f.tag ? ` · VLAN ${f.tag}` : ""}${f.firewall ? " · firewall" : ""}`],
              ] as const).map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="break-words">{v}</dd></div>)}
            </dl>
            {!f.pool && <Notice kind="error">Cette machine sera créée hors de tout pool.</Notice>}
            <Check checked={f.start} onChange={(v) => set("start", v)}>Démarrer la machine après sa création</Check>
            {busy && <p className="text-sm text-muted">Création en cours, cela peut prendre quelques secondes…</p>}
          </>}

          {error && <Notice kind="error">{error}</Notice>}
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-line p-4 px-6">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Annuler</Button>
          <div className="flex gap-2">
            {step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={busy}>Précédent</Button>}
            {step < 3
              ? <Button onClick={() => setStep(step + 1)} disabled={!valid[step]}>Suivant</Button>
              : <Button onClick={create} disabled={busy || !valid.every(Boolean)}>{busy ? "…" : "Créer la machine"}</Button>}
          </div>
        </footer>
      </div>
    </div>
  );
}
