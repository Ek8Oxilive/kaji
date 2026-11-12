import type { NodeInfo } from "../lib/api";
import { bytes, pct, uptime } from "../lib/format";
import { nodeHash } from "../lib/route";
import { Gauge } from "./Gauge";

import { tr } from "../lib/i18n";
export function NodeCard({ node, ip, index, onOpen }: { node: NodeInfo; ip?: string | null; index: number; onOpen: () => void }) {
  const online = node.status === "online";
  return (
    // Un clic sur la carte (hors lien) ouvre la page du nœud ; le nom est un vrai lien, pour le clavier.
    <article className="panel card-hover rise cursor-pointer space-y-4 p-5" style={{ animationDelay: `${index * 50}ms` }}
      onClick={(e) => { if (!(e.target as HTMLElement).closest("a, button")) onOpen(); }}>
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold"><a href={nodeHash(node.node)} className="hover:underline focus-visible:underline">{node.node}</a></h3>
          <p className="text-xs text-muted">{tr("{p} · actif depuis {p2}", { p: ip ?? "—", p2: uptime(node.uptime) })}</p>
        </div>
        <span className={`flex items-center gap-1.5 text-xs ${online ? "text-ok" : "text-danger"}`}>
          <span className={`size-2 rounded-full ${online ? "bg-ok dot-live" : "bg-danger"}`} />{online ? tr("En ligne") : tr("Hors ligne")}
        </span>
      </div>
      <Gauge label={tr("CPU · {p} cœurs", { p: node.maxcpu ?? "?" })} value={(node.cpu ?? 0) * 100} />
      <Gauge label={tr("RAM")} value={pct(node.mem, node.maxmem)} detail={`${bytes(node.mem)} / ${bytes(node.maxmem)}`} />
      <Gauge label={tr("Disque")} value={pct(node.disk, node.maxdisk)} detail={`${bytes(node.disk)} / ${bytes(node.maxdisk)}`} />
    </article>
  );
}
