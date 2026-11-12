import { TemplateCatalogDialog } from "./TemplateCatalogDialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Bridge, type LxcCreateBody, type LxcTemplates, type NodeInfo, type StorageInfo } from "../lib/api";
import { bytes } from "../lib/format";
import { LONG_TASK_SECONDS, runTask, WARN_SUFFIX } from "../lib/tasks";
import { useSubmit } from "./HardwareDialogs";
import { PoolField } from "./PoolField";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

import { tr, T } from "../lib/i18n";
const STEPS = [T("Général"), T("Modèle et ressources"), T("Réseau et accès"), T("Récapitulatif")];
const MEM = [128, 256, 512, 1024, 2048, 4096];

const Select = ({ label, hint, children, ...p }: { label: string; hint?: string; children: ReactNode } & React.SelectHTMLAttributes<HTMLSelectElement>) => (
  <label className="block space-y-1.5"><span className="text-sm text-muted">{label}</span><select {...p} className="field">{children}</select>{hint && <span className="block text-xs text-muted">{hint}</span>}</label>
);
const Check = ({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) => (
  <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={checked} onChange={(e) => onChange(e.target.checked)} /><span>{children}</span></label>
);

type Form = {
  node: string; hostname: string; vmid: string; pool: string; description: string;
  template: string; cores: string; memory: string; swap: string; storage: string; size: string; unprivileged: boolean; nesting: boolean;
  noNet: boolean; bridge: string; tag: string; firewall: boolean; ipMode: "dhcp" | "static" | "none"; ip: string; gw: string;
  password: string; password2: string; sshKeys: string; start: boolean;
};

export function CreateLxcWizard({ connId, nodes, onClose }: { connId: number; nodes: NodeInfo[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [f, setF] = useState<Form>({
    node: nodes[0]?.node ?? "", hostname: "", vmid: "", pool: "", description: "", template: "", cores: "1", memory: "512", swap: "512",
    storage: "", size: "4", unprivileged: true, nesting: false, noNet: false, bridge: "", tag: "", firewall: false, ipMode: "dhcp", ip: "", gw: "",
    password: "", password2: "", sshKeys: "", start: false,
  });
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const { busy, error, run } = useSubmit(onClose);
  const base = `/api/connections/${connId}`;
  const q = { staleTime: 30_000, retry: false } as const;

  const nextId = useQuery({ queryKey: ["nextid", connId], queryFn: () => api<{ vmid: number }>(`${base}/nextid`), ...q, staleTime: 0 });
  const tpls = useQuery({ queryKey: ["lxc-templates", connId, f.node], queryFn: () => api<LxcTemplates>(`${base}/nodes/${f.node}/templates`), enabled: !!f.node, ...q });
  const stores = useQuery({ queryKey: ["storages", connId, f.node, "rootdir"], queryFn: () => api<StorageInfo[]>(`${base}/nodes/${f.node}/storages?content=rootdir`), enabled: !!f.node, ...q });
  const bridges = useQuery({ queryKey: ["bridges", connId, f.node], queryFn: () => api<Bridge[]>(`${base}/nodes/${f.node}/bridges`), enabled: !!f.node, ...q });

  useEffect(() => { if (nextId.data && !f.vmid) set("vmid", String(nextId.data.vmid)); }, [nextId.data]);                                                                  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (tpls.data?.local.length && !tpls.data.local.some((t) => t.volid === f.template)) set("template", tpls.data.local[0].volid); }, [tpls.data]);        // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (stores.data?.length && !stores.data.some((s) => s.storage === f.storage)) set("storage", stores.data[0].storage); }, [stores.data]);                // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (bridges.data?.length && !bridges.data.some((b) => b.name === f.bridge)) set("bridge", bridges.data[0].name); }, [bridges.data]);                   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const int = (v: string) => (v.trim() === "" ? NaN : Number(v));
  const keysOk = f.sshKeys.trim() === "" || f.sshKeys.trim().split(/\r?\n/).filter(Boolean).every((l) => /^(ssh-|ecdsa-|sk-)\S+ \S{20,}/.test(l.trim()));
  const pwOk = f.password === "" || (f.password.length >= 8 && f.password === f.password2);
  const valid = [
    /^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$/.test(f.hostname) && !!f.node && Number.isInteger(int(f.vmid)) && int(f.vmid) >= 100,
    !!f.template && int(f.cores) >= 1 && int(f.memory) >= 16 && int(f.swap) >= 0 && !!f.storage && int(f.size) >= 1 && int(f.size) <= 65536,
    (f.noNet || (/^[A-Za-z0-9_.-]{1,15}$/.test(f.bridge) && (f.tag.trim() === "" || (int(f.tag) >= 1 && int(f.tag) <= 4094))
      && (f.ipMode !== "static" || (/^[0-9a-fA-F:.]+\/\d{1,3}$/.test(f.ip) && (f.gw === "" || /^[0-9a-fA-F:.]+$/.test(f.gw)))))) && pwOk && keysOk,
    true,
  ];

  const body = (): LxcCreateBody => ({
    hostname: f.hostname, vmid: int(f.vmid), template: f.template, memory: int(f.memory), swap: int(f.swap), cores: int(f.cores),
    disk: { storage: f.storage, size_gb: int(f.size) },
    ...(f.noNet ? {} : { net: { bridge: f.bridge, firewall: f.firewall, ...(f.tag.trim() ? { tag: int(f.tag) } : {}),
      ...(f.ipMode === "dhcp" ? { ip: "dhcp" } : f.ipMode === "static" ? { ip: f.ip, ...(f.gw ? { gateway: f.gw } : {}) } : {}) } }),
    ...(f.password ? { password: f.password } : {}), ...(f.sshKeys.trim() ? { ssh_public_keys: f.sshKeys.trim() } : {}),
    unprivileged: f.unprivileged, nesting: f.nesting, ...(f.pool ? { pool: f.pool } : {}), start: f.start, description: f.description,
  });

  const create = () => run(async () => {
    const t = await runTask(connId, f.node, () => api(`${base}/nodes/${f.node}/lxc`, { method: "POST", body: body() }), tr("Création"), LONG_TASK_SECONDS);
    toast("ok", tr("Conteneur « {hostname} » créé (#{vmid}){p}", { hostname: f.hostname, vmid: f.vmid, p: t.warnings ? tr(WARN_SUFFIX) : "" }));
    await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] });
  });

  const [catalog, setCatalog] = useState(false);
  const noTemplate = tpls.isSuccess && tpls.data.local.length === 0;
  const lbl = (b: Bridge) => `${b.name}${b.zone ? ` · zone ${b.zone}` : ""}${b.detail ? ` · ${b.detail}` : ""}`;

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4">
      <div role="dialog" aria-modal="true" aria-label={tr("Créer un conteneur LXC")} className="panel rise flex max-h-[92vh] w-full max-w-2xl flex-col">
        <header className="space-y-4 border-b border-line p-6 pb-4">
          <h2 className="text-xl font-semibold tracking-tight">{tr("Nouveau conteneur LXC")}</h2>
          <ol className="flex gap-2 text-sm" aria-label={tr("Étapes")}>
            {STEPS.map((s, i) => (
              <li key={s} aria-current={i === step ? "step" : undefined} className={`flex flex-1 items-center gap-2 rounded-lg px-2 py-1.5 ${i === step ? "bg-accent text-accentfg font-medium" : i < step ? "text-ok" : "text-muted"}`}>
                <span className="grid size-5 shrink-0 place-items-center rounded-full border border-current text-xs">{i < step ? "✓" : i + 1}</span><span className="hidden truncate md:inline">{tr(s)}</span>
              </li>
            ))}
          </ol>
        </header>

        <div className="space-y-4 overflow-y-auto p-6">
          {step === 0 && <>
            <Select label={tr("Nœud")} value={f.node} onChange={(e) => set("node", e.target.value)}>{nodes.map((n) => <option key={n.node} value={n.node}>{n.node}</option>)}</Select>
            <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
              <Field label={tr("Nom d'hôte")} value={f.hostname} onChange={(e) => set("hostname", e.target.value)} placeholder={tr("mon-conteneur")} hint={tr("Lettres, chiffres, - et . (sans espace)")} autoFocus />
              <Field label={tr("Identifiant")} type="number" min={100} value={f.vmid} onChange={(e) => set("vmid", e.target.value)} hint={nextId.data ? tr("Libre : {vmid}", { vmid: nextId.data.vmid }) : undefined} />
            </div>
            <PoolField connId={connId} value={f.pool} onChange={(v) => set("pool", v)} />
            {!f.pool && <Notice kind="error">{tr("Aucun pool choisi : le conteneur sera créé hors de tout pool.")}</Notice>}
            <Field label={tr("Description (facultatif)")} value={f.description} onChange={(e) => set("description", e.target.value)} maxLength={200} />
          </>}

          {step === 1 && <>
            <Select label={tr("Modèle")} value={f.template} onChange={(e) => set("template", e.target.value)} hint={tpls.isError ? tr("Liste indisponible") : undefined}>
              {tpls.data?.local.map((t) => <option key={t.volid} value={t.volid}>{t.name}{t.size ? ` · ${bytes(t.size)}` : ""}</option>)}
            </Select>
            {noTemplate && <Notice kind="error">{tr("Aucun modèle de conteneur sur ce nœud. Télécharges-en un depuis le catalogue officiel.")}</Notice>}
            <div><Button variant="ghost" onClick={() => setCatalog(true)} className="!px-3 !py-1.5" disabled={!f.node}>{tr("Télécharger un modèle…")}</Button></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label={tr("Cœurs")} type="number" min={1} max={512} value={f.cores} onChange={(e) => set("cores", e.target.value)} />
              <Field label={tr("Swap (Mo)")} type="number" min={0} step={128} value={f.swap} onChange={(e) => set("swap", e.target.value)} />
            </div>
            <div className="space-y-2">
              <Field label={tr("Mémoire (Mo)")} type="number" min={16} step={64} value={f.memory} onChange={(e) => set("memory", e.target.value)} />
              <div className="flex flex-wrap gap-1.5">{MEM.map((m) => <button key={m} type="button" onClick={() => set("memory", String(m))} className={`rounded-lg border px-2.5 py-1 text-xs transition ${f.memory === String(m) ? "border-accent text-accent" : "border-line text-muted hover:text-fg"}`}>{m >= 1024 ? `${m / 1024} Go` : `${m} Mo`}</button>)}</div>
            </div>
            <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
              <Select label={tr("Stockage du disque")} value={f.storage} onChange={(e) => set("storage", e.target.value)} hint={stores.isError ? tr("Liste indisponible") : undefined}>
                {stores.data?.map((s) => <option key={s.storage} value={s.storage} disabled={!s.active}>{s.storage}{s.type ? ` (${s.type})` : ""}{s.avail ? ` · ${bytes(s.avail)} libres` : ""}</option>)}
              </Select>
              <Field label={tr("Taille (Go)")} type="number" min={1} max={65536} value={f.size} onChange={(e) => set("size", e.target.value)} />
            </div>
            <Check checked={f.unprivileged} onChange={(v) => set("unprivileged", v)}>{tr("Conteneur non privilégié")}{" "}<span className="block text-xs text-muted">{tr("Recommandé : l'utilisateur root du conteneur n'est pas root sur l'hôte. Décocher pour un conteneur privilégié, nettement moins sûr.")}</span></Check>
            {!f.unprivileged && <Notice kind="error">{tr("Un conteneur privilégié partage les droits root de l'hôte : une faille dedans peut compromettre le nœud.")}</Notice>}
            <Check checked={f.nesting} onChange={(v) => set("nesting", v)}>{tr("Autoriser l'imbrication")}{" "}<span className="block text-xs text-muted">{tr("Nécessaire pour faire tourner Docker ou LXC dans le conteneur. Les modèles récents (Debian 12, Ubuntu 22.04 et plus) peuvent aussi le réclamer : Proxmox le signale par un avertissement « Systemd détecté » à la création, sans que ce soit une erreur.")}</span></Check>
          </>}

          {step === 2 && <>
            <Check checked={!f.noNet} onChange={(v) => set("noNet", !v)}>{tr("Ajouter une carte réseau")}</Check>
            {!f.noNet && <>
              <Select label={tr("Réseau (bridge ou VNet SDN)")} value={f.bridge} onChange={(e) => set("bridge", e.target.value)}>
                <optgroup label={tr("Bridges")}>{bridges.data?.filter((b) => b.kind === "bridge").map((b) => <option key={b.name} value={b.name}>{lbl(b)}</option>)}</optgroup>
                {bridges.data?.some((b) => b.kind === "vnet") && <optgroup label={tr("VNets SDN")}>{bridges.data.filter((b) => b.kind === "vnet").map((b) => <option key={b.name} value={b.name}>{lbl(b)}</option>)}</optgroup>}
              </Select>
              <div className="grid gap-4 sm:grid-cols-2">
                <Select label={tr("Adresse IP")} value={f.ipMode} onChange={(e) => set("ipMode", e.target.value as Form["ipMode"])}><option value="dhcp">{tr("DHCP")}</option><option value="static">{tr("Statique")}</option><option value="none">{tr("Aucune")}</option></Select>
                <Field label={tr("Étiquette VLAN")} type="number" min={1} max={4094} value={f.tag} onChange={(e) => set("tag", e.target.value)} placeholder={tr("aucun")} />
              </div>
              {f.ipMode === "static" && <div className="grid gap-4 sm:grid-cols-2">
                <Field label={tr("Adresse (CIDR)")} value={f.ip} onChange={(e) => set("ip", e.target.value)} placeholder="192.168.1.50/24" hint={tr("Avec le masque")} />
                <Field label={tr("Passerelle (facultatif)")} value={f.gw} onChange={(e) => set("gw", e.target.value)} placeholder="192.168.1.1" />
              </div>}
              <Check checked={f.firewall} onChange={(v) => set("firewall", v)}>{tr("Firewall Proxmox activé")}</Check>
            </>}
            <fieldset className="space-y-3 rounded-xl border border-line p-4">
              <legend className="px-1 text-sm text-muted">{tr("Accès root")}</legend>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={tr("Mot de passe (facultatif)")} type="password" value={f.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" hint={tr("8 caractères minimum")} />
                <Field label={tr("Confirmer")} type="password" value={f.password2} onChange={(e) => set("password2", e.target.value)} autoComplete="new-password" />
              </div>
              {f.password && f.password.length < 8 && <p className="text-sm text-danger">{tr("Le mot de passe doit faire au moins 8 caractères.")}</p>}
              {f.password && f.password2 && f.password !== f.password2 && <p className="text-sm text-danger">{tr("Les deux mots de passe ne correspondent pas.")}</p>}
              <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Clés SSH publiques (facultatif, une par ligne)")}</span>
                <textarea className="field min-h-20 font-mono text-xs" value={f.sshKeys} onChange={(e) => set("sshKeys", e.target.value)} placeholder={tr("ssh-ed25519 AAAA… moi@machine")} spellCheck={false} /></label>
              {!keysOk && <p className="text-sm text-danger">{tr("Une des clés n'a pas un format valide.")}</p>}
              {!f.password && !f.sshKeys.trim() && <p className="text-xs text-muted">{tr("Sans mot de passe ni clé, on ne pourra entrer dans le conteneur que depuis le nœud (")}<code>{tr("pct enter")}</code>).</p>}
            </fieldset>
          </>}

          {step === 3 && <>
            <dl className="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-2 text-sm">
              {([
                [tr("Nom"), `${f.hostname} (#${f.vmid})`], [tr("Nœud"), f.node], [tr("Pool"), f.pool || "aucun"], [tr("Modèle"), f.template.replace(/^.*vztmpl\//, "")],
                [tr("Processeur"), tr("{cores} cœur{p}", { cores: f.cores, p: int(f.cores) > 1 ? "s" : "" })], [tr("Mémoire"), `${f.memory} Mo (swap ${f.swap} Mo)`], [tr("Disque"), tr("{size} Go sur {storage}", { size: f.size, storage: f.storage })],
                [tr("Type"), f.unprivileged ? tr("non privilégié") : tr("PRIVILÉGIÉ")], [tr("Imbrication"), f.nesting ? "oui" : "non"],
                [tr("Réseau"), f.noNet ? tr("aucune carte") : `${f.bridge} · ${f.ipMode === "dhcp" ? "DHCP" : f.ipMode === "static" ? f.ip : tr("sans IP")}${f.tag ? ` · VLAN ${f.tag}` : ""}${f.firewall ? " · firewall" : ""}`],
                [tr("Accès root"), [f.password && tr("mot de passe"), f.sshKeys.trim() && tr("clé SSH")].filter(Boolean).join(" + ") || "aucun"],
              ] as const).map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="break-words">{v}</dd></div>)}
            </dl>
            {!f.pool && <Notice kind="error">{tr("Ce conteneur sera créé hors de tout pool.")}</Notice>}
            {!f.unprivileged && <Notice kind="error">{tr("Conteneur privilégié : réservé aux cas qui l'exigent.")}</Notice>}
            <Check checked={f.start} onChange={(v) => set("start", v)}>{tr("Démarrer le conteneur après sa création")}</Check>
            {busy && <p className="text-sm text-muted">{tr("Création en cours, la fenêtre reste ouverte jusqu'à la fin…")}</p>}
          </>}

          {error && <Notice kind="error">{error}</Notice>}
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-line p-4 px-6">
          <Button variant="ghost" onClick={onClose} disabled={busy}>{tr("Annuler")}</Button>
          <div className="flex gap-2">
            {step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={busy}>{tr("Précédent")}</Button>}
            {step < 3 ? <Button onClick={() => setStep(step + 1)} disabled={!valid[step]}>{tr("Suivant")}</Button>
              : <Button onClick={create} disabled={busy || !valid.every(Boolean)}>{busy ? "…" : tr("Créer le conteneur")}</Button>}
          </div>
        </footer>
      </div>
    {catalog && <TemplateCatalogDialog connId={connId} node={f.node} onClose={() => setCatalog(false)} />}
    </div>
  );
}
