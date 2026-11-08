import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type Guest } from "../lib/api";
import { confirmReasons } from "../lib/confirmRisk";
import type { HotplugFeature, VmBoolKey, VmOptionKey, VmOptionsPatch, VmOptionsResponse, VmOptionsResult } from "../lib/types/options";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

const OSTYPES = ["l26", "l24", "win11", "win10", "win8", "win7", "wvista", "w2k8", "w2k3", "w2k", "wxp", "solaris", "other"];
const HOTPLUG: HotplugFeature[] = ["disk", "network", "usb", "memory", "cpu", "cloudinit"];
const HOTPLUG_DEFAULT: HotplugFeature[] = ["disk", "network", "usb"];
// `def` : valeur appliquée par Proxmox quand le réglage est absent (affichée tant qu'il n'est pas défini).
const BOOLS: { key: VmBoolKey; label: string; hint: string; def: boolean }[] = [
  { key: "onboot", label: "Démarrer au démarrage du nœud", hint: "Lance la machine quand le nœud démarre.", def: false },
  { key: "protection", label: "Protection contre la suppression", hint: "Proxmox refuse alors de supprimer la machine ou ses disques.", def: false },
  { key: "tablet", label: "Tablette USB", hint: "Pointeur absolu : utile pour la console graphique.", def: true },
  { key: "numa", label: "NUMA", hint: "Répartition de la mémoire sur plusieurs processeurs.", def: false },
  { key: "localtime", label: "Horloge en heure locale", hint: "Par défaut pour Windows.", def: false },
  { key: "acpi", label: "ACPI", hint: "Arrêt et redémarrage propres depuis Proxmox. Le désactiver est risqué.", def: true },
  { key: "kvm", label: "Virtualisation matérielle (KVM)", hint: "La désactiver rend la machine très lente.", def: true },
  { key: "freeze", label: "Geler le processeur au démarrage", hint: "La machine ne s'exécute pas tant qu'on ne la relance pas. Risqué.", def: false },
];
const num = (s: string) => (s.trim() === "" ? null : Number(s));
const intOk = (s: string, max: number) => s.trim() === "" || (/^\d+$/.test(s.trim()) && Number(s) <= max);

export function OptionsTab({ connId, guest }: { connId: number; guest: Guest }) {
  const base = `/api/connections/${connId}/guests/${guest.node}/qemu/${guest.vmid}/options`;
  const qk = ["options", connId, guest.node, guest.vmid];
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading, refetch } = useQuery({ queryKey: qk, queryFn: () => api<VmOptionsResponse>(base), staleTime: 0 });
  const [bools, setBools] = useState<Record<string, boolean>>({});
  const [order, setOrder] = useState(""); const [up, setUp] = useState(""); const [down, setDown] = useState("");
  const [ostype, setOstype] = useState(""); const [desc, setDesc] = useState("");
  const [agent, setAgent] = useState(false); const [fstrim, setFstrim] = useState(false);
  const [hot, setHot] = useState<HotplugFeature[]>([]);
  const [cleared, setCleared] = useState<Set<VmOptionKey>>(new Set());
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const [risk, setRisk] = useState<string[] | null>(null);

  // Remplit le formulaire avec l'état réel relu chez Proxmox.
  useEffect(() => {
    if (!data) return;
    const o = data.options;
    setBools(Object.fromEntries(BOOLS.map((b) => [b.key, o[b.key] ?? b.def])));
    setOrder(o.startup?.order?.toString() ?? ""); setUp(o.startup?.up?.toString() ?? ""); setDown(o.startup?.down?.toString() ?? "");
    setOstype(o.ostype ?? ""); setDesc(o.description ?? ""); setAgent(o.agent?.enabled ?? false); setFstrim(o.agent?.fstrim_cloned_disks ?? false);
    setHot(o.hotplug ?? HOTPLUG_DEFAULT); setCleared(new Set()); setRisk(null);
  }, [data]);

  const toggleClear = (k: VmOptionKey) => setCleared((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const valid = intOk(order, 9999) && intOk(up, 86400) && intOk(down, 86400) && desc.length <= 8192;

  /** Ne contient que ce qui a changé : le serveur ignore de toute façon ce qui est identique. */
  const patch = useMemo((): VmOptionsPatch | null => {
    if (!data) return null;
    const o = data.options; const p: VmOptionsPatch = {}; const clear: VmOptionKey[] = [...cleared];
    for (const b of BOOLS) if (!cleared.has(b.key) && bools[b.key] !== (o[b.key] ?? b.def)) p[b.key] = bools[b.key];
    const st = { order: num(order), up: num(up), down: num(down) }; const cur = o.startup;
    if (!cleared.has("startup") && (st.order !== (cur?.order ?? null) || st.up !== (cur?.up ?? null) || st.down !== (cur?.down ?? null))) {
      const s = Object.fromEntries(Object.entries(st).filter(([, v]) => v !== null)) as { order?: number; up?: number; down?: number };
      if (Object.keys(s).length) p.startup = s;
    }
    if (!cleared.has("ostype") && ostype && ostype !== o.ostype) p.ostype = ostype;
    if (!cleared.has("description") && desc !== (o.description ?? "")) { if (desc === "") { if (o.description !== null) clear.push("description"); } else p.description = desc; }
    if (!cleared.has("agent") && (agent !== (o.agent?.enabled ?? false) || fstrim !== (o.agent?.fstrim_cloned_disks ?? false))) {
      const a: { enabled?: boolean; fstrim_cloned_disks?: boolean } = {};
      if (agent !== (o.agent?.enabled ?? false)) a.enabled = agent;
      if (fstrim !== (o.agent?.fstrim_cloned_disks ?? false)) a.fstrim_cloned_disks = fstrim;
      p.agent = a;
    }
    if (!cleared.has("hotplug") && [...hot].sort().join() !== [...(o.hotplug ?? HOTPLUG_DEFAULT)].sort().join()) p.hotplug = hot;
    if (clear.length) p.clear = clear;
    return Object.keys(p).length ? p : null;
  }, [data, bools, order, up, down, ostype, desc, agent, fstrim, hot, cleared]);
  // Une confirmation ne vaut que pour la demande qui l'a provoquée : si un champ change, les raisons ne sont plus celles-là.
  const patchKey = JSON.stringify(patch);
  useEffect(() => { setRisk(null); }, [patchKey]);

  const save = async (confirm: boolean) => {
    if (!patch) return setErr("Aucune modification.");
    setBusy(true); setErr(null);
    try {
      await api<VmOptionsResult>(base, { method: "PATCH", body: { ...patch, ...(confirm ? { confirm: true } : {}) } });
      toast("ok", "Enregistré : certains réglages ne s'appliquent qu'au prochain démarrage de la VM");
      await qc.invalidateQueries({ queryKey: qk });
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setRisk(reasons); else setErr((e as Error).message);
    } finally { setBusy(false); }
  };

  if (isLoading) return <div className="panel h-40 animate-pulse" />;
  if (error || !data) return <Notice kind="error">{(error as Error | null)?.message ?? "Options illisibles"} — <button className="underline" onClick={() => refetch()}>réessayer</button></Notice>;
  const o = data.options;
  const defBtn = (k: VmOptionKey, isSet: boolean) => isSet
    ? <button type="button" className="text-xs text-muted underline" onClick={() => toggleClear(k)}>{cleared.has(k) ? "Annuler" : "Valeur par défaut"}</button> : null;
  const box = "mt-0.5 size-4 accent-[var(--accent)]";

  return (
    <div className="space-y-5">
      {data.pending.length > 0 && <Notice kind="ok">Changements en attente (appliqués au prochain démarrage) : {data.pending.map((p) => p.key).join(", ")}.</Notice>}
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">Démarrage</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Ordre" value={order} onChange={(e) => setOrder(e.target.value)} inputMode="numeric" placeholder="ex. 1" disabled={cleared.has("startup")} aria-invalid={!intOk(order, 9999)} hint="0 à 9999" />
          <Field label="Attente après démarrage (s)" value={up} onChange={(e) => setUp(e.target.value)} inputMode="numeric" disabled={cleared.has("startup")} aria-invalid={!intOk(up, 86400)} />
          <Field label="Attente à l'arrêt (s)" value={down} onChange={(e) => setDown(e.target.value)} inputMode="numeric" disabled={cleared.has("startup")} aria-invalid={!intOk(down, 86400)} />
        </div>
        {defBtn("startup", o.startup !== null)}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">Réglages</h3>
        {BOOLS.map((b) => (
          <div key={b.key} className="flex items-start justify-between gap-3">
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={bools[b.key] ?? b.def} disabled={cleared.has(b.key)}
              onChange={(e) => setBools((s) => ({ ...s, [b.key]: e.target.checked }))} />
              <span>{b.label}<span className="block text-xs text-muted">{b.hint}</span></span></label>
            {defBtn(b.key, o[b.key] !== null)}
          </div>
        ))}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">Système et agent</h3>
        <label className="block space-y-1.5"><span className="text-sm text-muted">Système invité</span>
          <select className="field" value={ostype} onChange={(e) => setOstype(e.target.value)} disabled={cleared.has("ostype")}>
            <option value="">Non défini</option>{OSTYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
        {defBtn("ostype", o.ostype !== null)}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={agent} disabled={cleared.has("agent")} onChange={(e) => setAgent(e.target.checked)} />
          <span>Agent QEMU activé<span className="block text-xs text-muted">Le paquet qemu-guest-agent doit être installé dans la machine.</span></span></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={fstrim} disabled={cleared.has("agent")} onChange={(e) => setFstrim(e.target.checked)} />
          <span>Lancer fstrim sur les disques clonés</span></label>
        {defBtn("agent", o.agent !== null)}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">Hotplug</h3>
        <div className="flex flex-wrap gap-4">
          {HOTPLUG.map((h) => <label key={h} className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-[var(--accent)]" checked={hot.includes(h)} disabled={cleared.has("hotplug")}
            onChange={(e) => setHot((s) => e.target.checked ? [...s, h] : s.filter((x) => x !== h))} />{h}</label>)}
        </div>
        {defBtn("hotplug", o.hotplug !== null)}
      </div>
      <div className="panel space-y-3 p-5">
        <label className="block space-y-1.5"><span className="text-sm text-muted">Description</span>
          <textarea className="field min-h-24" value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={8192} disabled={cleared.has("description")} /></label>
      </div>
      {risk && (
        <div className="space-y-2 rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn" role="alert">
          <p className="font-medium">Confirmation requise</p>
          <ul className="list-disc space-y-1 pl-5">{risk.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      {err && <Notice kind="error">{err}</Notice>}
      <Button variant={risk ? "danger" : "primary"} onClick={() => save(!!risk)} disabled={busy || !patch || !valid}>{busy ? "…" : risk ? "Confirmer et enregistrer" : "Enregistrer"}</Button>
    </div>
  );
}
