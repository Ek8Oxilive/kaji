import type { NodeInfo } from "../lib/api";
import { bytes, pct, uptime } from "../lib/format";
import { Gauge } from "./Gauge";

export function NodeCard({ node, ip, index }: { node: NodeInfo; ip?: string | null; index: number }) {
  const online = node.status === "online";
  return (
    <article className="panel card-hover rise space-y-4 p-5" style={{ animationDelay: `${index * 50}ms` }}>
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold">{node.node}</h3>
          <p className="text-xs text-muted">{ip ?? "—"} · actif depuis {uptime(node.uptime)}</p>
        </div>
        <span className={`flex items-center gap-1.5 text-xs ${online ? "text-ok" : "text-danger"}`}>
          <span className={`size-2 rounded-full ${online ? "bg-ok dot-live" : "bg-danger"}`} />{online ? "En ligne" : "Hors ligne"}
        </span>
      </div>
      <Gauge label={`CPU · ${node.maxcpu ?? "?"} cœurs`} value={(node.cpu ?? 0) * 100} />
      <Gauge label="RAM" value={pct(node.mem, node.maxmem)} detail={`${bytes(node.mem)} / ${bytes(node.maxmem)}`} />
      <Gauge label="Disque" value={pct(node.disk, node.maxdisk)} detail={`${bytes(node.disk)} / ${bytes(node.maxdisk)}`} />
    </article>
  );
}
