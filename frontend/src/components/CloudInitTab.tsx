import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type CloudInit, type Guest, type StorageInfo } from "../lib/api";
import { bytes } from "../lib/format";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

type Mode = "unset" | "dhcp" | "static" | "none";

export function CloudInitTab({ connId, guest }: { connId: number; guest: Guest }) {
  const base = `/api/connections/${connId}/guests/${guest.node}/qemu/${guest.vmid}/cloudinit`;
  const qk = ["cloudinit", connId, guest.node, guest.vmid];
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading, refetch } = useQuery({ queryKey: qk, queryFn: () => api<CloudInit>(base), staleTime: 0 });
  const stores = useQuery({ queryKey: ["storages", connId, guest.node, "images"], retry: false, staleTime: 30_000,
    queryFn: () => api<StorageInfo[]>(`/api/connections/${connId}/nodes/${guest.node}/storages?content=images`) });

  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [dropPassword, setDropPassword] = useState(false);
  const [keys, setKeys] = useState("");
  const [mode, setMode] = useState<Mode>("unset");
  const [ip, setIp] = useState("");
  const [gw, setGw] = useState("");
  const [dns, setDns] = useState("");
  const [domain, setDomain] = useState("");
  const [upgrade, setUpgrade] = useState(true);
  const [storage, setStorage] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmDrop, setConfirmDrop] = useState(false);

  // Remplit le formulaire avec l'état réel. Le mot de passe n'est jamais lu : seul son état « défini » l'est.
  useEffect(() => {
    if (!data) return;
    const c = data.ipconfig["ipconfig0"];
    setUser(data.user ?? ""); setKeys(data.ssh_keys ?? ""); setDns(data.nameserver ?? ""); setDomain(data.searchdomain ?? "");
    setUpgrade(data.upgrade ?? true); setMode(c ? c.mode : "unset"); setIp(c?.ip ?? ""); setGw(c?.gateway ?? "");
    setPassword(""); setDropPassword(false);
  }, [data]);

  const chosen = storage || stores.data?.[0]?.storage || "";
  const send = async (body: object) => {
    setBusy(true); setErr(null);
    try { await api(base, { method: "PATCH", body }); toast("ok", "Enregistré : pris en compte au prochain démarrage de la VM"); await qc.invalidateQueries({ queryKey: qk }); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  function save() {
    if (!data) return;
    const body: Record<string, unknown> = {}; const clear: string[] = [];
    const diff = (cur: string | null, now: string, key: string, field: string) => {
      if (now.trim() === (cur ?? "")) return;
      if (now.trim() === "") clear.push(field); else body[key] = now.trim();
    };
    diff(data.user, user, "user", "user"); diff(data.ssh_keys, keys, "ssh_keys", "ssh_keys");
    diff(data.nameserver, dns, "nameserver", "nameserver"); diff(data.searchdomain, domain, "searchdomain", "searchdomain");
    if (password) body.password = password; else if (dropPassword && data.password_set) clear.push("password");
    if (upgrade !== (data.upgrade ?? true)) body.upgrade = upgrade;
    const cur = data.ipconfig["ipconfig0"];
    if (mode === "unset") { if (cur) clear.push("ipconfig0"); }
    else if (!cur || cur.mode !== mode || (mode === "static" && (cur.ip !== ip || (cur.gateway ?? "") !== gw)))
      body.ipconfig = { ipconfig0: { mode, ...(mode === "static" ? { ip, ...(gw ? { gateway: gw } : {}) } : {}) } };
    if (clear.length) body.clear = clear;
    if (Object.keys(body).length === 0) return setErr("Aucune modification.");
    send(body).then(() => { setPassword(""); });
  }

  const addDrive = async () => {
    setBusy(true); setErr(null);
    try { await api(`${base}/drive`, { method: "POST", body: { storage: chosen } }); toast("ok", "Lecteur cloud-init ajouté"); await qc.invalidateQueries({ queryKey: qk }); await qc.invalidateQueries({ queryKey: ["hw", connId, guest.node, guest.type, guest.vmid] }); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const dropDrive = async () => {
    setBusy(true); setErr(null);
    try { await api(`${base}/drive?confirm=true`, { method: "DELETE" }); toast("ok", "Lecteur cloud-init retiré (les réglages sont conservés)"); setConfirmDrop(false); await qc.invalidateQueries({ queryKey: qk }); await qc.invalidateQueries({ queryKey: ["hw", connId, guest.node, guest.type, guest.vmid] }); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const ipOk = mode !== "static" || /^[0-9a-fA-F:.]+\/\d{1,3}$/.test(ip);
  if (isLoading) return <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-surface2" />)}</div>;
  if (error) return <Notice kind="error">{(error as Error).message} — <button className="underline" onClick={() => refetch()}>réessayer</button></Notice>;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">Cloud-init configure une VM au démarrage : utilisateur, clé SSH, réseau. L'image de la VM doit le supporter (images « cloud »). Les changements sont pris en compte au prochain démarrage.</p>

      {!data.has_drive ? (
        <div className="space-y-3 rounded-xl border border-line p-4">
          <p className="text-sm">Cette VM n'a pas de <strong>lecteur cloud-init</strong> : sans lui, les réglages n'ont aucun effet.</p>
          <label className="block space-y-1.5"><span className="text-sm text-muted">Stockage du lecteur</span>
            <select className="field" value={chosen} onChange={(e) => setStorage(e.target.value)}>{stores.data?.map((s) => <option key={s.storage} value={s.storage}>{s.storage}{s.avail ? ` · ${bytes(s.avail)} libres` : ""}</option>)}</select></label>
          <Button onClick={addDrive} disabled={busy || !chosen}>Ajouter le lecteur cloud-init</Button>
        </div>
      ) : <>
        <Field label="Utilisateur" value={user} onChange={(e) => setUser(e.target.value)} placeholder="par défaut selon l'image" hint="Minuscules, chiffres, - et _" autoComplete="off" />
        <div className="space-y-1.5">
          <Field label={data.password_set ? "Nouveau mot de passe (un mot de passe est défini)" : "Mot de passe (facultatif)"} type="password" value={password} onChange={(e) => { setPassword(e.target.value); setDropPassword(false); }} autoComplete="new-password" placeholder={data.password_set ? "inchangé" : ""} hint="8 caractères minimum. Il n'est jamais relu ni affiché." />
          {data.password_set && <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-[var(--accent)]" checked={dropPassword} disabled={!!password} onChange={(e) => setDropPassword(e.target.checked)} /> Supprimer le mot de passe défini</label>}
        </div>
        <label className="block space-y-1.5"><span className="text-sm text-muted">Clés SSH publiques (une par ligne)</span>
          <textarea className="field min-h-20 font-mono text-xs" value={keys} onChange={(e) => setKeys(e.target.value)} placeholder="ssh-ed25519 AAAA… moi@machine" spellCheck={false} /></label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5"><span className="text-sm text-muted">Adresse IP (carte net0)</span>
            <select className="field" value={mode} onChange={(e) => setMode(e.target.value as Mode)}><option value="unset">Non définie</option><option value="dhcp">DHCP</option><option value="static">Statique</option><option value="none">Aucune</option></select></label>
          <Field label="Serveurs DNS" value={dns} onChange={(e) => setDns(e.target.value)} placeholder="1.1.1.1 9.9.9.9" hint="Séparés par des espaces" />
        </div>
        {mode === "static" && <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Adresse (CIDR)" value={ip} onChange={(e) => setIp(e.target.value)} placeholder="192.168.1.50/24" />
          <Field label="Passerelle (facultatif)" value={gw} onChange={(e) => setGw(e.target.value)} placeholder="192.168.1.1" />
        </div>}
        <Field label="Domaine de recherche" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="lab.local" />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-[var(--accent)]" checked={upgrade} onChange={(e) => setUpgrade(e.target.checked)} /> Mettre à jour les paquets au premier démarrage</label>
        {err && <Notice kind="error">{err}</Notice>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button onClick={save} disabled={busy || !ipOk}>{busy ? "…" : "Enregistrer"}</Button>
          {confirmDrop
            ? <div className="flex gap-2"><Button variant="danger" onClick={dropDrive} disabled={busy}>Confirmer le retrait</Button><Button variant="ghost" onClick={() => setConfirmDrop(false)}>Annuler</Button></div>
            : <Button variant="ghost" onClick={() => setConfirmDrop(true)} disabled={busy}>Retirer le lecteur cloud-init</Button>}
        </div>
      </>}
      {!data.has_drive && err && <Notice kind="error">{err}</Notice>}
    </div>
  );
}
