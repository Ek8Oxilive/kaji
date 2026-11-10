import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { CloneDialog } from "../components/CloneDialog";
import { CommandPalette, type Command } from "../components/CommandPalette";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CreateLxcWizard } from "../components/CreateLxcWizard";
import { CreateVmWizard } from "../components/CreateVmWizard";
import { GuestCard } from "../components/GuestCard";
import { NewMachineChooser } from "../components/NewMachineChooser";
import { NodeCard } from "../components/NodeCard";
import { Helm } from "../components/Logo";
import { Button, Notice } from "../components/ui";
import { api, type Connection, type Guest, type GuestAction } from "../lib/api";
import { bytes } from "../lib/format";
import { THEMES, useTheme } from "../lib/theme";
import { CONFIRM } from "../lib/guestConfirm";
import { guestKey, useCluster, useGuestActions } from "../lib/useCluster";

const CONN_KEY = "kaji-connection";
const readConn = () => { try { return Number(localStorage.getItem(CONN_KEY)) || null; } catch { return null; } };

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="panel rise p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
      {sub && <p className="text-xs text-muted">{sub}</p>}
    </div>
  );
}

const Skeleton = ({ n, h = "h-40" }: { n: number; h?: string }) => <>{Array.from({ length: n }, (_, i) => <div key={i} className={`panel animate-pulse ${h}`} />)}</>;

type GroupBy = "none" | "node" | "pool" | "tag" | "type" | "storage";
const GROUPS: GroupBy[] = ["none", "node", "pool", "tag", "type", "storage"];
type GuestStorages = { by_vmid: Record<string, string[]>; storages: string[]; errors: number };
const readGroupBy = (): GroupBy => { try { const v = localStorage.getItem("kaji.groupBy"); return GROUPS.includes(v as GroupBy) ? (v as GroupBy) : "none"; } catch { return "none"; } };

/** Regroupe les machines. Une machine à plusieurs étiquettes (ou plusieurs stockages) apparaît dans chacun de ses groupes ; sans valeur : « Sans … » en dernier. */
function groupGuests(list: Guest[], by: GroupBy, stores?: Record<string, string[]>): { key: string; label: string; items: Guest[] }[] {
  if (by === "none") return [{ key: "all", label: "", items: list }];
  const keyOf = (g: Guest): string[] => by === "node" ? [g.node] : by === "pool" ? [g.pool ?? ""] : by === "type" ? [g.template ? "template" : g.type] : by === "storage" ? (stores?.[String(g.vmid)]?.length ? stores[String(g.vmid)] : [""]) : ((g.tags ?? []).length ? g.tags! : [""]);
  const empty = by === "pool" ? "Sans pool" : by === "storage" ? "Sans disque identifié" : "Sans étiquette";
  const label = (k: string) => k === "" ? empty : by === "type" ? (k === "template" ? "Modèles" : k === "qemu" ? "Machines virtuelles" : "Conteneurs LXC") : by === "node" ? `Nœud ${k}` : by === "storage" ? `Stockage ${k}` : k;
  const map = new Map<string, Guest[]>();
  for (const g of list) for (const k of keyOf(g)) map.set(k, [...(map.get(k) ?? []), g]);
  return [...map.entries()].sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b, "fr"))).map(([k, items]) => ({ key: k || "_", label: label(k), items }));
}

export function Dashboard({ onGoConnections, onOpenGuest, onOpenNode }: { onGoConnections: () => void; onOpenGuest: (g: Guest) => void; onOpenNode: (node: string) => void }) {
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/api/connections") });
  const [connId, setConnId] = useState<number | null>(readConn);
  const list = conns.data;
  const active = list?.find((c) => c.id === connId) ?? list?.[0] ?? null;
  const id = active?.id ?? null;
  useEffect(() => { try { if (id) localStorage.setItem(CONN_KEY, String(id)); } catch { /* ignoré */ } }, [id]);

  const { status, nodes, guests, live, problem } = useCluster(id);
  const { setTheme } = useTheme();
  const { run, busy, effectiveStatus } = useGuestActions(id);
  const [pending, setPending] = useState<{ guest: Guest; action: Exclude<GuestAction, "start"> } | null>(null);
  const [palette, setPalette] = useState(false);
  const [wizard, setWizard] = useState<null | "choose" | "vm" | "lxc">(null);
  const [clone, setClone] = useState<Guest | null>(null);

  const [q, setQ] = useState(""), [state, setState] = useState("all"), [kind, setKind] = useState("all"), [node, setNode] = useState("all");
  const [pool, setPool] = useState("all"), [tag, setTag] = useState("all"), [groupBy, setGroupBy] = useState<GroupBy>(readGroupBy);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const visible = useMemo(() => (guests.data ?? []).filter((g) =>
    (state === "all" || effectiveStatus(g) === state) && (kind === "all" || g.type === kind) && (node === "all" || g.node === node) &&
    (pool === "all" || (pool === "none" ? !g.pool : g.pool === pool)) && (tag === "all" || (tag === "none" ? !(g.tags ?? []).length : (g.tags ?? []).includes(tag))) &&
    (!q || `${g.name ?? ""} ${g.vmid}`.toLowerCase().includes(q.toLowerCase()))),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [guests.data, state, kind, node, pool, tag, q, busy, now]);
  const pools = useMemo(() => [...new Set((guests.data ?? []).map((g) => g.pool).filter((p): p is string => !!p))].sort(), [guests.data]);
  const tagList = useMemo(() => [...new Set((guests.data ?? []).flatMap((g) => g.tags ?? []))].sort(), [guests.data]);
  const gstore = useQuery({ queryKey: ["guest-storages", id], queryFn: () => api<GuestStorages>(`/api/connections/${id}/guest-storages`), enabled: id !== null && groupBy === "storage", staleTime: 30_000 });
  const groups = useMemo(() => groupGuests(visible, groupBy, gstore.data?.by_vmid), [visible, groupBy, gstore.data]);

  if (conns.isLoading) return <div className="mx-auto grid max-w-6xl gap-4 sm:grid-cols-2 lg:grid-cols-4"><Skeleton n={4} h="h-24" /></div>;
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <Helm className="mx-auto size-10 text-accent" />
        <h1 className="text-2xl font-semibold tracking-tight">Aucun cluster connecté</h1>
        <p className="text-muted">Ajoute ton cluster Proxmox pour voir tes nœuds et tes machines.</p>
        <Button onClick={onGoConnections}>Ajouter un cluster</Button>
      </div>
    </div>
  );

  const err = status.error ?? nodes.error ?? guests.error;
  const g = guests.data ?? [], n = nodes.data ?? [];
  const real = g.filter((x) => !x.template);
  const running = real.filter((x) => effectiveStatus(x) === "running").length;
  const online = n.filter((x) => x.status === "online").length;
  const ramUsed = n.reduce((s, x) => s + (x.mem ?? 0), 0), ramMax = n.reduce((s, x) => s + (x.maxmem ?? 0), 0);
  const age = guests.dataUpdatedAt ? Math.max(0, Math.round((now - guests.dataUpdatedAt) / 1000)) : null;
  const refreshing = guests.isFetching || nodes.isFetching;
  const sel = "field !w-auto !py-1.5 text-sm";
  const commands: Command[] = [
    ...real.flatMap((x): Command[] => {
      const name = x.name ?? String(x.vmid), st = effectiveStatus(x);
      const hint = `#${x.vmid} · ${x.type === "qemu" ? "VM" : "LXC"} · ${x.node}`;
      const c = (a: string, label: string, run: () => void): Command => ({ id: `${a}-${guestKey(x)}`, group: "Machines", label: `${label} ${name}`, hint, run });
      return [
        c("open", "Ouvrir", () => onOpenGuest(x)),
        c("clone", "Cloner", () => setClone(x)),
        ...(st === "stopped" ? [c("start", "Démarrer", () => run(x, "start"))] : []),
        ...(st === "running" ? [
          c("reboot", "Redémarrer", () => setPending({ guest: x, action: "reboot" })),
          c("shutdown", "Éteindre", () => setPending({ guest: x, action: "shutdown" })),
        ] : []),
        ...(st === "running" || st === "paused" ? [c("stop", "Forcer l'arrêt de", () => setPending({ guest: x, action: "stop" }))] : []),
      ];
    }),
    ...n.map((x): Command => ({ id: `node-${x.node}`, group: "Navigation", label: `Ouvrir le nœud ${x.node}`, keywords: "serveur hôte", run: () => onOpenNode(x.node) })),
    { id: "new-vm", group: "Machines", label: "Créer une machine virtuelle", keywords: "nouvelle vm ajouter", run: () => setWizard("vm") },
    { id: "new-lxc", group: "Machines", label: "Créer un conteneur LXC", keywords: "nouveau conteneur lxc ct ajouter", run: () => setWizard("lxc") },
    { id: "go-conn", group: "Navigation", label: "Aller aux connexions", keywords: "cluster token", run: onGoConnections },
    { id: "refresh", group: "Navigation", label: "Actualiser les données", run: () => { status.refetch(); nodes.refetch(); guests.refetch(); } },
    ...THEMES.map((t): Command => ({ id: `theme-${t.id}`, group: "Thème", label: `Thème ${t.label}`, keywords: "apparence couleur", run: () => setTheme(t.id) })),
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{status.data?.name ?? active.name}</h1>
          <p className="text-muted">{active.name} · {active.host}</p>
        </div>
        <div className="flex items-center gap-3">
          {(list?.length ?? 0) > 1 && (
            <select aria-label="Cluster" className={sel} value={id ?? ""} onChange={(e) => setConnId(Number(e.target.value))}>
              {list!.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <Button onClick={() => setWizard("choose")} className="!px-3 !py-1.5">+ Nouvelle machine</Button>
          <button onClick={() => setPalette(true)} className="hidden items-center gap-2 rounded-xl border border-line bg-surface2 px-3 py-1.5 text-sm text-muted transition hover:text-fg sm:flex" aria-label="Ouvrir la palette de commandes">
            Rechercher <kbd className="rounded border border-line px-1.5 text-xs">Ctrl K</kbd>
          </button>
          {live
            ? <span className="flex items-center gap-1.5 text-xs text-ok" title="Mises à jour en temps réel"><span className="size-2 rounded-full bg-ok dot-live" />En direct</span>
            : <span className="text-xs text-muted" aria-live="off" title="Flux temps réel indisponible : rafraîchissement toutes les 10 s">{age === null ? "" : age < 2 ? "À l'instant" : `Mis à jour il y a ${age} s`}</span>}
          <Button variant="ghost" onClick={() => { status.refetch(); nodes.refetch(); guests.refetch(); }} disabled={refreshing} className="!px-3 !py-1.5">
            <span className={refreshing ? "inline-block animate-spin" : ""}>↻</span> Actualiser
          </Button>
        </div>
      </header>

      {problem && <Notice kind="error">Proxmox ne répond pas ({problem}). Les dernières données connues restent affichées ; la reprise est automatique.</Notice>}
      {err && !problem && <Notice kind="error">{(err as Error).message} — <button className="underline" onClick={() => { status.refetch(); nodes.refetch(); guests.refetch(); }}>réessayer</button></Notice>}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Résumé">
        {status.isLoading || guests.isLoading ? <Skeleton n={4} h="h-24" /> : <>
          <Tile label="Nœuds en ligne" value={`${online} / ${n.length}`} sub={status.data?.quorate == null ? undefined : status.data.quorate ? "Quorum OK" : "Quorum perdu"} />
          <Tile label="Machines actives" value={`${running} / ${real.length}`} sub={`${real.filter((x) => x.type === "qemu").length} VM · ${real.filter((x) => x.type === "lxc").length} LXC`} />
          <Tile label="RAM du cluster" value={ramMax ? `${Math.round((ramUsed / ramMax) * 100)} %` : "–"} sub={`${bytes(ramUsed)} / ${bytes(ramMax)}`} />
          <Tile label="Machines arrêtées" value={String(real.length - running)} />
        </>}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Nœuds</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {nodes.isLoading ? <Skeleton n={2} h="h-52" /> : n.map((x, i) => <NodeCard key={x.node} node={x} index={i} onOpen={() => onOpenNode(x.node)} ip={status.data?.nodes.find((s) => s.name === x.node)?.ip} />)}
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Machines <span className="text-sm font-normal text-muted">({visible.length})</span></h2>
          <div className="flex flex-wrap gap-2">
            <input className={`${sel} min-w-44`} placeholder="Rechercher…" aria-label="Rechercher une machine" value={q} onChange={(e) => setQ(e.target.value)} />
            <select className={sel} aria-label="État" value={state} onChange={(e) => setState(e.target.value)}><option value="all">Tous les états</option><option value="running">En marche</option><option value="paused">En pause</option><option value="stopped">Arrêtées</option></select>
            <select className={sel} aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value)}><option value="all">VM + LXC</option><option value="qemu">VM</option><option value="lxc">LXC</option></select>
            <select className={sel} aria-label="Nœud" value={node} onChange={(e) => setNode(e.target.value)}><option value="all">Tous les nœuds</option>{n.map((x) => <option key={x.node} value={x.node}>{x.node}</option>)}</select>
            {pools.length > 0 && <select className={sel} aria-label="Pool" value={pool} onChange={(e) => setPool(e.target.value)}><option value="all">Tous les pools</option><option value="none">Sans pool</option>{pools.map((p) => <option key={p} value={p}>{p}</option>)}</select>}
            {tagList.length > 0 && <select className={sel} aria-label="Étiquette" value={tag} onChange={(e) => setTag(e.target.value)}><option value="all">Toutes les étiquettes</option><option value="none">Sans étiquette</option>{tagList.map((t) => <option key={t} value={t}>{t}</option>)}</select>}
            <select className={sel} aria-label="Regrouper par" value={groupBy} onChange={(e) => { const v = e.target.value as GroupBy; setGroupBy(v); try { localStorage.setItem("kaji.groupBy", v); } catch { /* stockage indisponible */ } }}>
              <option value="none">Sans regroupement</option><option value="node">Regrouper par nœud</option><option value="pool">Regrouper par pool</option><option value="tag">Regrouper par étiquette</option><option value="type">Regrouper par type</option><option value="storage">Regrouper par stockage</option>
            </select>
          </div>
        </div>
        {groupBy === "storage" && (gstore.isLoading ? <p className="text-xs text-muted">Lecture des stockages…</p> : gstore.error ? <Notice kind="error">{(gstore.error as Error).message}</Notice>
          : (gstore.data?.errors ?? 0) > 0 ? <p className="text-xs text-muted">{gstore.data!.errors} stockage(s) illisible(s) : certaines machines peuvent apparaître sans disque identifié.</p> : null)}
        {guests.isLoading ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"><Skeleton n={6} h="h-52" /></div> : visible.length === 0
          ? <div className="panel p-6 text-muted">Aucune machine ne correspond aux filtres.</div>
          : groups.map((grp) => (
            <div key={grp.key} className="space-y-3">
              {groupBy !== "none" && <h3 className="flex items-baseline gap-2 border-b border-line pb-1 text-sm font-semibold">{grp.label}<span className="font-normal text-muted">({grp.items.length})</span></h3>}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {grp.items.map((x, i) => (
                  <GuestCard key={`${grp.key}/${guestKey(x)}`} guest={x} index={i} status={effectiveStatus(x)} busyLabel={busy[guestKey(x)]}
                    onOpen={() => onOpenGuest(x)} onClone={() => setClone(x)}
                    onAction={(a) => a === "start" ? run(x, "start") : setPending({ guest: x, action: a })} />
                ))}
              </div>
            </div>
          ))}
      </section>

      {clone && id && <CloneDialog connId={id} guest={clone} nodes={n} onClose={() => setClone(null)} />}

      {wizard === "choose" && <NewMachineChooser onPick={(k) => setWizard(k)} onClose={() => setWizard(null)} />}
      {wizard === "vm" && id && <CreateVmWizard connId={id} nodes={n} onClose={() => setWizard(null)} />}
      {wizard === "lxc" && id && <CreateLxcWizard connId={id} nodes={n} onClose={() => setWizard(null)} />}

      {palette && <CommandPalette commands={commands} onClose={() => setPalette(false)} />}

      {pending && (
        <ConfirmDialog title={`${CONFIRM[pending.action].title} « ${pending.guest.name ?? pending.guest.vmid} » ?`} confirmLabel={CONFIRM[pending.action].verb}
          danger={pending.action !== "reboot"} onCancel={() => setPending(null)}
          onConfirm={() => { const p = pending; setPending(null); run(p.guest, p.action); }}>
          {CONFIRM[pending.action].text}
        </ConfirmDialog>
      )}
    </div>
  );
}
