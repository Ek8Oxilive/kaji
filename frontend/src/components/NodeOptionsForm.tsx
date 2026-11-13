import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { Button, Notice } from "./ui";

type Opts = { wakeonlan: { mac: string | null; bind_interface: string | null; broadcast_address: string | null } | null; wakeonlan_readable: boolean;
  startall_onboot_delay: number | null; ballooning_target: number | null; digest: string | null; empty: boolean };
const field = "mt-1 w-full rounded border border-line bg-surface2 px-2 py-1 text-sm text-fg";

/** Options du nœud : réveil à distance (MAC), délai de démarrage des machines, cible du ballooning. Seules les options modifiées partent ; le serveur vérifie tout. */
export function NodeOptionsForm({ base }: { base: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["node-options", base], staleTime: 0, gcTime: 0, queryFn: () => api<Opts>(`${base}/options`) });
  const [mac, setMac] = useState(""), [iface, setIface] = useState(""), [bcast, setBcast] = useState(""), [delay, setDelay] = useState(""), [balloon, setBalloon] = useState("");
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const d = q.data;
  useEffect(() => {
    if (!d) return;
    setMac(d.wakeonlan?.mac ?? ""); setIface(d.wakeonlan?.bind_interface ?? ""); setBcast(d.wakeonlan?.broadcast_address ?? "");
    setDelay(d.startall_onboot_delay === null ? "" : String(d.startall_onboot_delay)); setBalloon(d.ballooning_target === null ? "" : String(d.ballooning_target));
  }, [d]);

  const body = (): Record<string, unknown> => {
    if (!d) return {};
    const b: Record<string, unknown> = {}, clear: string[] = [];
    const cur = d.wakeonlan;
    if (d.wakeonlan_readable) {
      if (mac === "" && cur) clear.push("wakeonlan");
      else if (mac !== "") {
        if (mac !== (cur?.mac ?? "")) b.wakeonlan_mac = mac;
        if (iface !== (cur?.bind_interface ?? "") && iface !== "") b.wakeonlan_bind_interface = iface;
        if (bcast !== (cur?.broadcast_address ?? "") && bcast !== "") b.wakeonlan_broadcast_address = bcast;
      }
    }
    if (delay === "" && d.startall_onboot_delay !== null) clear.push("startall-onboot-delay");
    else if (delay !== "" && Number(delay) !== d.startall_onboot_delay) b.startall_onboot_delay = Number(delay);
    if (balloon === "" && d.ballooning_target !== null) clear.push("ballooning-target");
    else if (balloon !== "" && Number(balloon) !== d.ballooning_target) b.ballooning_target = Number(balloon);
    return { ...b, ...(clear.length ? { clear } : {}) };
  };
  const payload = body();
  const changed = Object.keys(payload).length > 0;
  const numbersOk = (delay === "" || (/^[0-9]{1,3}$/.test(delay) && Number(delay) <= 300)) && (balloon === "" || (/^[0-9]{1,3}$/.test(balloon) && Number(balloon) <= 100));

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      await api(`${base}/options`, { method: "PUT", body: { ...payload, digest: d?.digest ?? undefined, confirm: true } });
      setMsg({ kind: "ok", text: tr("Options du nœud enregistrées. Relues chez Proxmox.") });
      await qc.invalidateQueries({ queryKey: ["node-options", base] });
    } catch (e) { setMsg({ kind: "error", text: (e as Error).message }); }
    setBusy(false);
  };

  if (q.isLoading) return <div className="h-24 animate-pulse rounded bg-surface2" />;
  if (q.error || !d) return <Notice kind="error">{tr("Lecture des options du nœud impossible.")}</Notice>;
  return (
    <form className="space-y-3 text-sm" onSubmit={(e) => { e.preventDefault(); if (changed && numbersOk) void save(); }}>
      <p className="text-xs text-muted">{tr("Un champ vide retire le réglage (Proxmox reprend sa valeur par défaut). Les notes du nœud et l'ACME ne sont pas touchés ici.")}</p>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="block text-xs text-muted">{tr("Réveil à distance : adresse MAC")}<input value={mac} onChange={(e) => setMac(e.target.value.trim())} placeholder="aa:bb:cc:dd:ee:ff" disabled={!d.wakeonlan_readable} className={field} autoComplete="off" /></label>
        <label className="block text-xs text-muted">{tr("Interface d'envoi (facultatif)")}<input value={iface} onChange={(e) => setIface(e.target.value.trim())} placeholder="vmbr0" disabled={!d.wakeonlan_readable} className={field} autoComplete="off" /></label>
        <label className="block text-xs text-muted">{tr("Adresse de diffusion IPv4 (facultatif)")}<input value={bcast} onChange={(e) => setBcast(e.target.value.trim())} placeholder="255.255.255.255" disabled={!d.wakeonlan_readable} className={field} autoComplete="off" /></label>
      </div>
      {!d.wakeonlan_readable && <Notice kind="error">{tr("Le réglage de réveil actuel n'est pas lisible par Kaji : il n'est pas modifiable ici.")}</Notice>}
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs text-muted">{tr("Délai avant de démarrer les machines au boot (secondes, 0 à 300)")}<input inputMode="numeric" value={delay} onChange={(e) => setDelay(e.target.value.trim())} placeholder="0" className={field} autoComplete="off" /></label>
        <label className="block text-xs text-muted">{tr("Cible du ballooning (% de la RAM, 0 à 100)")}<input inputMode="numeric" value={balloon} onChange={(e) => setBalloon(e.target.value.trim())} placeholder="80" className={field} autoComplete="off" /></label>
      </div>
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      <Button type="submit" disabled={busy || !changed || !numbersOk}>{tr("Enregistrer les options")}</Button>
    </form>
  );
}
