import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type Guest } from "../lib/api";
import { confirmReasons } from "../lib/confirmRisk";
import type { LxcMount, LxcOptionKey, LxcOptionsPatch, LxcOptionsResponse, VmOptionsResult } from "../lib/types/options";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

const OSTYPES = ["debian", "ubuntu", "alpine", "archlinux", "centos", "fedora", "opensuse", "devuan", "gentoo", "nixos", "unmanaged"];
const CMODES = ["tty", "console", "shell"];
const num = (s: string) => (s.trim() === "" ? null : Number(s));
const intOk = (s: string, max: number) => s.trim() === "" || (/^\d+$/.test(s.trim()) && Number(s) <= max);
const TZ = /^(host|[A-Za-z0-9_+-]{1,32}(\/[A-Za-z0-9_+-]{1,32}){0,2})$/;

const ROOT_ONLY = "Modifiable seulement dans Proxmox (droit root@pam).";

export function LxcOptionsTab({ connId, guest }: { connId: number; guest: Guest }) {
  const base = `/api/connections/${connId}/guests/${guest.node}/lxc/${guest.vmid}/options`;
  const qk = ["options", connId, guest.node, guest.vmid];
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading, refetch } = useQuery({ queryKey: qk, queryFn: () => api<LxcOptionsResponse>(base), staleTime: 0 });
  const [onboot, setOnboot] = useState(false); const [protection, setProtection] = useState(false); const [consoleOn, setConsoleOn] = useState(true);
  const [order, setOrder] = useState(""); const [up, setUp] = useState(""); const [down, setDown] = useState("");
  const [nesting, setNesting] = useState(false); const [fuse, setFuse] = useState(false); const [keyctl, setKeyctl] = useState(false); const [mount, setMount] = useState<LxcMount[]>([]);
  const [ostype, setOstype] = useState(""); const [cmode, setCmode] = useState(""); const [tty, setTty] = useState(""); const [tz, setTz] = useState(""); const [desc, setDesc] = useState("");
  const [cleared, setCleared] = useState<Set<LxcOptionKey>>(new Set());
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const [risk, setRisk] = useState<string[] | null>(null);

  // Remplit le formulaire avec l'état réel relu chez Proxmox.
  useEffect(() => {
    if (!data) return;
    const o = data.options;
    setOnboot(o.onboot ?? false); setProtection(o.protection ?? false); setConsoleOn(o.console ?? true);
    setOrder(o.startup?.order?.toString() ?? ""); setUp(o.startup?.up?.toString() ?? ""); setDown(o.startup?.down?.toString() ?? "");
    setNesting(o.features?.nesting ?? false); setFuse(o.features?.fuse ?? false); setKeyctl(o.features?.keyctl ?? false); setMount(o.features?.mount ?? []);
    setOstype(o.ostype ?? ""); setCmode(o.cmode ?? ""); setTty(o.tty?.toString() ?? ""); setTz(o.timezone ?? ""); setDesc(o.description ?? "");
    setCleared(new Set()); setRisk(null);
  }, [data]);

  const toggleClear = (k: LxcOptionKey) => setCleared((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const valid = intOk(order, 9999) && intOk(up, 86400) && intOk(down, 86400) && intOk(tty, 6) && (tz === "" || TZ.test(tz)) && desc.length <= 8192;

  /** Ne contient que ce qui a changé : le serveur ignore de toute façon ce qui est identique. */
  const patch = useMemo((): LxcOptionsPatch | null => {
    if (!data) return null;
    const o = data.options; const p: LxcOptionsPatch = {}; const clear: LxcOptionKey[] = [...cleared];
    if (!cleared.has("onboot") && onboot !== (o.onboot ?? false)) p.onboot = onboot;
    if (!cleared.has("protection") && protection !== (o.protection ?? false)) p.protection = protection;
    if (!cleared.has("console") && consoleOn !== (o.console ?? true)) p.console = consoleOn;
    const st = { order: num(order), up: num(up), down: num(down) }; const cur = o.startup;
    if (!cleared.has("startup") && (st.order !== (cur?.order ?? null) || st.up !== (cur?.up ?? null) || st.down !== (cur?.down ?? null))) {
      const s = Object.fromEntries(Object.entries(st).filter(([, v]) => v !== null)) as { order?: number; up?: number; down?: number };
      if (Object.keys(s).length) p.startup = s;
    }
    if (!cleared.has("features")) {
      const f: { nesting?: boolean; fuse?: boolean; keyctl?: boolean; mount?: LxcMount[] } = {}; const cf = o.features;
      if (nesting !== (cf?.nesting ?? false)) f.nesting = nesting;
      if (fuse !== (cf?.fuse ?? false)) f.fuse = fuse;
      if (keyctl !== (cf?.keyctl ?? false)) f.keyctl = keyctl;
      if ([...mount].sort().join() !== [...(cf?.mount ?? [])].sort().join()) f.mount = mount;
      if (Object.keys(f).length) p.features = f;
    }
    if (!cleared.has("ostype") && ostype && ostype !== o.ostype) p.ostype = ostype;
    if (!cleared.has("cmode") && cmode && cmode !== o.cmode) p.cmode = cmode;
    if (!cleared.has("tty") && tty.trim() !== "" && num(tty) !== o.tty) p.tty = Number(tty);
    if (!cleared.has("timezone") && tz && tz !== o.timezone) p.timezone = tz;
    if (!cleared.has("description") && desc !== (o.description ?? "")) { if (desc === "") { if (o.description !== null) clear.push("description"); } else p.description = desc; }
    if (clear.length) p.clear = clear;
    return Object.keys(p).length ? p : null;
  }, [data, onboot, protection, consoleOn, order, up, down, nesting, fuse, keyctl, mount, ostype, cmode, tty, tz, desc, cleared]);
  // Une confirmation ne vaut que pour la demande qui l'a provoquée : si un champ change, les raisons ne sont plus celles-là.
  const patchKey = JSON.stringify(patch);
  useEffect(() => { setRisk(null); }, [patchKey]);

  const save = async (confirm: boolean) => {
    if (!patch) return setErr("Aucune modification.");
    setBusy(true); setErr(null);
    try {
      await api<VmOptionsResult>(base, { method: "PATCH", body: { ...patch, ...(confirm ? { confirm: true } : {}) } });
      toast("ok", "Enregistré : certains réglages ne s'appliquent qu'au prochain démarrage du conteneur");
      await qc.invalidateQueries({ queryKey: qk });
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setRisk(reasons); else setErr((e as Error).message);
    } finally { setBusy(false); }
  };

  if (isLoading) return <div className="panel h-40 animate-pulse" />;
  if (error || !data) return <Notice kind="error">{(error as Error | null)?.message ?? "Options illisibles"} — <button className="underline" onClick={() => refetch()}>réessayer</button></Notice>;
  const o = data.options;
  const defBtn = (k: LxcOptionKey, isSet: boolean) => isSet
    ? <button type="button" className="text-xs text-muted underline" onClick={() => toggleClear(k)}>{cleared.has(k) ? "Annuler" : "Valeur par défaut"}</button> : null;
  const box = "mt-0.5 size-4 accent-[var(--accent)]";
  const check = (label: string, hint: string, v: boolean, set: (b: boolean) => void, off: boolean) => (
    <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={v} disabled={off} onChange={(e) => set(e.target.checked)} />
      <span>{label}<span className="block text-xs text-muted">{hint}</span></span></label>
  );

  return (
    <div className="space-y-5">
      {data.pending.length > 0 && <Notice kind="ok">Changements en attente (appliqués au prochain démarrage) : {data.pending.map((p) => p.key).join(", ")}.</Notice>}
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">Démarrage et protection</h3>
        <div className="flex items-start justify-between gap-3">{check("Démarrer au démarrage du nœud", "Lance le conteneur quand le nœud démarre.", onboot, setOnboot, cleared.has("onboot"))}{defBtn("onboot", o.onboot !== null)}</div>
        <div className="flex items-start justify-between gap-3">{check("Protection contre la suppression", "Proxmox refuse alors de supprimer le conteneur ou ses disques.", protection, setProtection, cleared.has("protection"))}{defBtn("protection", o.protection !== null)}</div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Ordre" value={order} onChange={(e) => setOrder(e.target.value)} inputMode="numeric" placeholder="ex. 1" disabled={cleared.has("startup")} aria-invalid={!intOk(order, 9999)} hint="0 à 9999" />
          <Field label="Attente après démarrage (s)" value={up} onChange={(e) => setUp(e.target.value)} inputMode="numeric" disabled={cleared.has("startup")} aria-invalid={!intOk(up, 86400)} />
          <Field label="Attente à l'arrêt (s)" value={down} onChange={(e) => setDown(e.target.value)} inputMode="numeric" disabled={cleared.has("startup")} aria-invalid={!intOk(down, 86400)} />
        </div>
        {defBtn("startup", o.startup !== null)}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">Fonctionnalités</h3>
        {data.unprivileged === false && <Notice kind="error">Conteneur privilégié : il a un accès étendu à l'hôte. Son mode ne peut pas être changé ici.</Notice>}
        {check("Nesting", "Permet de lancer des conteneurs ou Docker dedans. Conseillé pour les Debian 12 récents.", nesting, setNesting, cleared.has("features"))}
        {check("FUSE", "Systèmes de fichiers en espace utilisateur. " + ROOT_ONLY, fuse, setFuse, true)}
        {check("keyctl", "Trousseau de clés du noyau (nécessaire à certains conteneurs applicatifs). " + ROOT_ONLY, keyctl, setKeyctl, true)}
        <div className="flex flex-wrap gap-4 text-sm"><span className="text-muted">Montages autorisés :</span>
          {(["nfs", "cifs"] as LxcMount[]).map((m) => <label key={m} className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-[var(--accent)]" checked={mount.includes(m)} disabled={true}
            onChange={(e) => setMount((s) => e.target.checked ? [...s, m] : s.filter((x) => x !== m))} />{m}</label>)}</div>
        <p className="text-xs text-muted">Montages : {ROOT_ONLY}</p>
        {defBtn("features", o.features !== null && !(o.features.fuse || o.features.keyctl || o.features.mount.length > 0))}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">Système et console</h3>
        <label className="block space-y-1.5"><span className="text-sm text-muted">Système invité</span>
          <select className="field" value={ostype} onChange={(e) => setOstype(e.target.value)} disabled={cleared.has("ostype")}><option value="">Non défini</option>{OSTYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
        {defBtn("ostype", o.ostype !== null)}
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="block space-y-1.5"><span className="text-sm text-muted">Mode de console</span>
            <select className="field" value={cmode} onChange={(e) => setCmode(e.target.value)} disabled={cleared.has("cmode")}><option value="">Non défini</option>{CMODES.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
          <Field label="Nombre de terminaux (tty)" value={tty} onChange={(e) => setTty(e.target.value)} inputMode="numeric" placeholder="2" disabled={cleared.has("tty")} aria-invalid={!intOk(tty, 6)} hint="0 à 6" />
          <Field label="Fuseau horaire" value={tz} onChange={(e) => setTz(e.target.value)} placeholder="host ou Europe/Paris" disabled={cleared.has("timezone")} aria-invalid={tz !== "" && !TZ.test(tz)} />
        </div>
        <div className="flex flex-wrap gap-4">{defBtn("cmode", o.cmode !== null)}{defBtn("tty", o.tty !== null)}{defBtn("timezone", o.timezone !== null)}</div>
        <div className="flex items-start justify-between gap-3">{check("Périphérique /dev/console", "Attache une console au conteneur.", consoleOn, setConsoleOn, cleared.has("console"))}{defBtn("console", o.console !== null)}</div>
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
