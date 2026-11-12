import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../../lib/api";
import { bytes } from "../../lib/format";
import type { GuestPoint, Metrics, NodePoint } from "../../lib/types/mesures";
import { Notice } from "../ui";
import { TimeChart, type Series, type Timeframe } from "./TimeChart";

import { tr, T } from "../../lib/i18n";
const FRAMES: [Timeframe, string][] = [["hour", T("Heure")], ["day", T("Jour")], ["week", T("Semaine")], ["month", T("Mois")], ["year", T("Année")]];

const percent = (v: number) => `${(v * 100).toFixed(v > 0 && v < 0.1 ? 1 : 0)} %`;
const rate = (v: number) => `${bytes(v)}/s`;
const plain = (v: number) => (v >= 10 ? v.toFixed(0) : v.toFixed(2));

/** Sélecteur de période : une seule rangée au-dessus des graphiques, qui concerne tous ceux d'en dessous. */
function FramePicker({ value, onChange }: { value: Timeframe; onChange: (t: Timeframe) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label={tr("Période")}>
      {FRAMES.map(([id, label]) => (
        <button key={id} type="button" aria-pressed={value === id} onClick={() => onChange(id)}
          className={`rounded-full border px-3 py-1 text-xs transition ${value === id ? "border-accent bg-accent text-accentfg" : "border-line bg-surface2 text-muted hover:text-fg"}`}>{tr(label)}</button>
      ))}
    </div>
  );
}

function useMetrics<P>(url: string, tf: Timeframe) {
  return useQuery({
    queryKey: ["metrics", url, tf], queryFn: () => api<Metrics<P>>(`${url}?timeframe=${tf}`), placeholderData: keepPreviousData,
    staleTime: 10_000, refetchInterval: tf === "hour" ? 30_000 : tf === "day" ? 60_000 : 300_000,      // Proxmox ne change ses points qu'à leur pas
  });
}

const col = <P extends { t: number }>(pts: P[], k: keyof P) => pts.map((p) => (p[k] as number | null));
const lastOf = (v: (number | null)[]) => { for (let i = v.length - 1; i >= 0; i--) if (v[i] !== null) return v[i] as number; return undefined; };
const s = (id: string, label: string, slot: 1 | 2, values: (number | null)[]): Series => ({ id, label, slot, values });

function Shell({ tf, setTf, q, children }: { tf: Timeframe; setTf: (t: Timeframe) => void; q: { error: unknown; isFetching: boolean; isLoading: boolean; refetch: () => unknown }; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <FramePicker value={tf} onChange={setTf} />
      {q.error != null && <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>{tr("réessayer")}</button></Notice>}
      {q.isLoading ? <div className="grid grid-cols-1 gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <div key={i} className="panel h-60 animate-pulse" />)}</div>
        : <div className="grid grid-cols-1 gap-4 md:grid-cols-2">{children}</div>}
    </div>
  );
}

/** Historique d'un nœud : processeur, mémoire, réseau, charge. */
export function NodeCharts({ connId, node }: { connId: number; node: string }) {
  const [tf, setTf] = useState<Timeframe>("hour");
  const q = useMetrics<NodePoint>(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/metrics`, tf);
  const pts = q.data?.points ?? [];
  const times = useMemo(() => pts.map((p) => p.t), [pts]);
  const memTotal = lastOf(col(pts, "mem_total"));
  return (
    <Shell tf={tf} setTf={setTf} q={q}>
      <TimeChart title={tr("Processeur")} subtitle={tr("Part de la capacité du nœud")} times={times} timeframe={tf} loading={q.isFetching} format={percent} domainMax={1}
        series={[s("cpu", tr("Utilisation"), 1, col(pts, "cpu")), s("iowait", tr("Attente disque"), 2, col(pts, "iowait"))]} />
      <TimeChart title={tr("Mémoire")} subtitle={memTotal ? tr("Sur {p}", { p: bytes(memTotal) }) : undefined} times={times} timeframe={tf} loading={q.isFetching} format={bytes} bytes domainMax={memTotal}
        series={[s("mem", tr("Utilisée"), 1, col(pts, "mem_used"))]} />
      <TimeChart title={tr("Réseau")} subtitle={tr("Débit moyen")} times={times} timeframe={tf} loading={q.isFetching} format={rate} bytes
        series={[s("in", tr("Entrant"), 1, col(pts, "net_in")), s("out", tr("Sortant"), 2, col(pts, "net_out"))]} />
      <TimeChart title={tr("Charge")} subtitle={tr("Charge moyenne du système")} times={times} timeframe={tf} loading={q.isFetching} format={plain}
        series={[s("load", tr("Charge"), 1, col(pts, "load"))]} />
    </Shell>
  );
}

/** Historique d'une machine : processeur, mémoire, réseau, disque. */
export function GuestCharts({ connId, node, type, vmid }: { connId: number; node: string; type: "qemu" | "lxc"; vmid: number }) {
  const [tf, setTf] = useState<Timeframe>("hour");
  const q = useMetrics<GuestPoint>(`/api/connections/${connId}/guests/${encodeURIComponent(node)}/${type}/${vmid}/metrics`, tf);
  const pts = q.data?.points ?? [];
  const times = useMemo(() => pts.map((p) => p.t), [pts]);
  const memTotal = lastOf(col(pts, "mem_total"));
  const cpus = lastOf(col(pts, "cpus"));
  return (
    <Shell tf={tf} setTf={setTf} q={q}>
      <TimeChart title={tr("Processeur")} subtitle={cpus ? tr("{cpus} vCPU : 100 % = tous les vCPU", { cpus }) : undefined} times={times} timeframe={tf} loading={q.isFetching} format={percent} domainMax={1}
        series={[s("cpu", tr("Utilisation"), 1, col(pts, "cpu"))]} />
      <TimeChart title={tr("Mémoire")} subtitle={memTotal ? tr("Sur {p}", { p: bytes(memTotal) }) : undefined} times={times} timeframe={tf} loading={q.isFetching} format={bytes} bytes domainMax={memTotal}
        series={[s("mem", tr("Utilisée"), 1, col(pts, "mem_used"))]} />
      <TimeChart title={tr("Réseau")} subtitle={tr("Débit moyen")} times={times} timeframe={tf} loading={q.isFetching} format={rate} bytes
        series={[s("in", tr("Entrant"), 1, col(pts, "net_in")), s("out", tr("Sortant"), 2, col(pts, "net_out"))]} />
      <TimeChart title={tr("Disque")} subtitle={tr("Débit moyen")} times={times} timeframe={tf} loading={q.isFetching} format={rate} bytes
        series={[s("read", tr("Lecture"), 1, col(pts, "disk_read")), s("write", tr("Écriture"), 2, col(pts, "disk_write"))]} />
    </Shell>
  );
}
