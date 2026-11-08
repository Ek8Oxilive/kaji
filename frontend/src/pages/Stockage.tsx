import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Gauge } from "../components/Gauge";
import { UploadDialog, UrlDownloadDialog } from "../components/FileTransferDialogs";
import { AddStorageDialog, DeleteStorageDialog, EditStorageDialog } from "../components/StorageConfigDialogs";
import { Button, Notice } from "../components/ui";
import { api, type Connection } from "../lib/api";
import { bytes, pct } from "../lib/format";
import type { StorageRow, StorageVolume } from "../lib/types/stockage";
import type { StorageConfig } from "../lib/types/stockage-config";

const CONN_KEY = "kaji-connection";   // même clé que le tableau de bord : le cluster choisi est partagé
const readConn = () => { try { return Number(localStorage.getItem(CONN_KEY)) || null; } catch { return null; } };

const CONTENT_LABEL: Record<string, string> = {
  images: "Disques de VM", rootdir: "Disques de conteneur", iso: "ISO", vztmpl: "Modèles", backup: "Sauvegardes", snippets: "Snippets",
};
const label = (c: string | null) => (c ? CONTENT_LABEL[c] ?? c : "–");
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "–");

/** Une carte par stockage. Un stockage partagé n'en fait qu'une ; deux stockages locaux de même nom sur deux nœuds en font deux. */
type Card = { key: string; row: StorageRow; where: string };

function toCards(rows: StorageRow[]): Card[] {
  const out = new Map<string, Card>();
  for (const r of rows) {
    const key = r.shared ? r.storage : `${r.storage}@${r.node ?? ""}`;
    const seen = out.get(key);
    if (!seen) out.set(key, { key, row: r, where: r.shared ? r.nodes.join(", ") : r.node ?? "–" });
    else if (!seen.row.active && r.active) seen.row = r;     // partagé : on lit le contenu depuis une entrée active
  }
  return [...out.values()];
}

const Skeleton = ({ n, h }: { n: number; h: string }) => <>{Array.from({ length: n }, (_, i) => <div key={i} className={`panel animate-pulse ${h}`} />)}</>;

function Space({ row }: { row: StorageRow }) {
  const known = row.used != null && row.total != null && row.total > 0;
  return known
    ? <>
        <Gauge label="Espace utilisé" value={pct(row.used, row.total)} detail={`${bytes(row.used)} / ${bytes(row.total)}`} />
        <p className="text-xs text-muted">Libre : {bytes(row.free)}</p>
      </>
    : <p className="text-xs text-muted">Espace : information indisponible</p>;
}

function StorageCard({ card, index, onOpen }: { card: Card; index: number; onOpen: () => void }) {
  const r = card.row;
  return (
    <button type="button" onClick={onOpen} disabled={!r.active} aria-haspopup="dialog"
      title={r.active ? "Ouvrir le contenu" : "Stockage inactif : contenu indisponible"}
      className="panel card-hover rise block w-full space-y-4 p-5 text-left disabled:cursor-not-allowed disabled:opacity-60"
      style={{ animationDelay: `${index * 50}ms` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{r.storage}</h3>
          <p className="truncate text-xs text-muted">{r.type ?? "type inconnu"} · {r.shared ? "partagé" : "local"} · {card.where}</p>
        </div>
        <span className={`flex shrink-0 items-center gap-1.5 text-xs ${r.active ? "text-ok" : "text-danger"}`}>
          <span className={`size-2 rounded-full ${r.active ? "bg-ok" : "bg-danger"}`} />{r.active ? "Actif" : "Inactif"}
        </span>
      </div>
      <Space row={r} />
      <div className="flex flex-wrap gap-1.5">
        {r.contents.length === 0 && <span className="text-xs text-muted">Aucun contenu déclaré</span>}
        {r.contents.map((c) => <span key={c} className="rounded-full border border-line bg-surface2 px-2 py-0.5 text-xs text-muted">{label(c)}</span>)}
      </div>
    </button>
  );
}

/** Tiroir latéral (comme le panneau « Matériel ») : le contenu du stockage s'ouvre par-dessus la page, qui ne bouge pas. */
function StorageDrawer({ connId, card, config, onClose, onEdit, onDelete }: { connId: number; card: Card; config: StorageConfig | null; onClose: () => void; onEdit: () => void; onDelete: () => void }) {
  const { node, storage } = card.row;
  const fileKinds = card.row.contents.filter((c): c is "iso" | "vztmpl" => c === "iso" || c === "vztmpl");
  const [transfer, setTransfer] = useState<"upload" | "url" | null>(null);
  const vols = useQuery({
    queryKey: ["storage-content", connId, node, storage],
    queryFn: () => api<StorageVolume[]>(`/api/connections/${connId}/nodes/${encodeURIComponent(node ?? "")}/storage/${encodeURIComponent(storage)}/content`),
    enabled: !!node, staleTime: 15_000,
  });
  const [kind, setKind] = useState("all"), [q, setQ] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const data = vols.data ?? [];
  const kinds = useMemo(() => {
    const n = new Map<string, number>();
    for (const v of data) n.set(v.content ?? "", (n.get(v.content ?? "") ?? 0) + 1);
    return [...n.entries()];
  }, [data]);
  const shown = data.filter((v) => (kind === "all" || (v.content ?? "") === kind)
    && (!q || `${v.name} ${v.vmid ?? ""} ${v.notes ?? ""}`.toLowerCase().includes(q.toLowerCase())));
  const chip = (active: boolean) => `rounded-full border px-3 py-1 text-xs transition ${active ? "border-accent bg-accent text-accentfg" : "border-line bg-surface2 text-muted hover:text-fg"}`;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label={`Contenu de ${storage}`} onClick={(e) => e.stopPropagation()}
        className="panel rise h-full w-[min(56rem,100vw)] space-y-5 overflow-y-auto !rounded-none !rounded-l-2xl p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold">{storage}</h2>
            <p className="truncate text-sm text-muted">{card.row.type ?? "type inconnu"} · {card.row.shared ? "partagé" : "local"} · {card.where}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {config?.managed && <Button variant="ghost" onClick={onEdit} className="!px-3 !py-1">Modifier</Button>}
            {config && <Button variant="danger" onClick={onDelete} className="!px-3 !py-1">Retirer</Button>}
            <Button variant="ghost" onClick={onClose} aria-label="Fermer" className="!px-3 !py-1" autoFocus>✕</Button>
          </div>
        </div>
        {config && !config.managed && <p className="text-xs text-muted">Type « {config.type} » : Kaji ne le modifie pas encore, il peut seulement le retirer.</p>}

        <div className="max-w-sm space-y-2"><Space row={card.row} /></div>

        {fileKinds.length > 0 && node && (
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={() => setTransfer("upload")} className="!px-3 !py-1.5">Téléverser un fichier</Button>
            <Button variant="ghost" onClick={() => setTransfer("url")} className="!px-3 !py-1.5">Télécharger depuis une URL</Button>
          </div>
        )}
        {transfer === "upload" && node && <UploadDialog connId={connId} node={node} storage={storage} kinds={fileKinds} onClose={() => setTransfer(null)} />}
        {transfer === "url" && node && <UrlDownloadDialog connId={connId} node={node} storage={storage} kinds={fileKinds} onClose={() => setTransfer(null)} />}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-semibold">Contenu <span className="text-sm font-normal text-muted">({shown.length})</span></h3>
          <input className="field !w-auto min-w-52 !py-1.5 text-sm" placeholder="Rechercher…" aria-label="Rechercher un volume" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {kinds.length > 1 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrer par type">
            <button type="button" className={chip(kind === "all")} aria-pressed={kind === "all"} onClick={() => setKind("all")}>Tous ({data.length})</button>
            {kinds.map(([k, n]) => (
              <button key={k} type="button" className={chip(kind === k)} aria-pressed={kind === k} onClick={() => setKind(k)}>{label(k || null)} ({n})</button>
            ))}
          </div>
        )}
        {vols.isLoading ? <div className="space-y-2"><Skeleton n={4} h="h-10" /></div>
          : vols.error ? <Notice kind="error">{(vols.error as Error).message} — <button className="underline" onClick={() => vols.refetch()}>réessayer</button></Notice>
          : shown.length === 0 ? <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{data.length === 0 ? "Ce stockage ne contient aucun volume." : "Aucun volume ne correspond aux filtres."}</div>
          : (
            <div className="overflow-x-auto rounded-xl border border-line">
              <table className="w-full min-w-[40rem] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    <th scope="col" className="px-4 py-2 font-normal">Nom</th><th scope="col" className="px-4 py-2 font-normal">Type</th>
                    <th scope="col" className="px-4 py-2 font-normal">Format</th><th scope="col" className="px-4 py-2 text-right font-normal">Taille</th>
                    <th scope="col" className="px-4 py-2 font-normal">Date</th><th scope="col" className="px-4 py-2 font-normal">Machine</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((v) => (
                    <tr key={v.volid} className="border-b border-line/60 last:border-0">
                      <td className="max-w-xs px-4 py-2">
                        <span className="block truncate" title={v.volid}>{v.name}</span>
                        {(v.notes || v.protected || v.verification || v.encrypted) && (
                          <span className="block truncate text-xs text-muted">
                            {[v.protected ? "Protégé" : null, v.encrypted ? "Chiffrée" : null,
                              v.verification === "ok" ? "Vérifiée" : v.verification === "failed" ? "Vérification échouée" : v.verification === "none" ? "Non vérifiée" : null,
                              v.notes].filter(Boolean).join(" · ")}
                          </span>)}
                      </td>
                      <td className="px-4 py-2 text-muted">{label(v.content)}</td>
                      <td className="px-4 py-2 text-muted">{v.format ?? "–"}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{bytes(v.size)}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-muted">{when(v.date)}</td>
                      <td className="px-4 py-2 tabular-nums text-muted">{v.vmid ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </aside>
    </div>
  );
}

export function Stockage({ onGoConnections }: { onGoConnections: () => void }) {
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/api/connections") });
  const [connId, setConnId] = useState<number | null>(readConn);
  const list = conns.data;
  const active = list?.find((c) => c.id === connId) ?? list?.[0] ?? null;
  const id = active?.id ?? null;
  useEffect(() => { try { if (id) localStorage.setItem(CONN_KEY, String(id)); } catch { /* ignoré */ } }, [id]);

  const rows = useQuery({
    queryKey: ["storages", id], queryFn: () => api<StorageRow[]>(`/api/connections/${id}/storages`),
    enabled: id !== null, staleTime: 15_000,
  });
  const cards = useMemo(() => toCards(rows.data ?? []), [rows.data]);
  const [opened, setOpened] = useState<string | null>(null);
  useEffect(() => { setOpened(null); }, [id]);
  const current = cards.find((c) => c.key === opened) ?? null;
  const configs = useQuery({
    queryKey: ["storage-config", id], queryFn: () => api<StorageConfig[]>(`/api/connections/${id}/storage-config`),
    enabled: id !== null, staleTime: 15_000,
  });
  const [dialog, setDialog] = useState<"add" | "edit" | "delete" | null>(null);
  const currentConfig = configs.data?.find((c) => c.storage === current?.row.storage) ?? null;

  if (conns.isLoading) return <div className="mx-auto grid max-w-6xl gap-4 sm:grid-cols-2 lg:grid-cols-3"><Skeleton n={3} h="h-44" /></div>;
  if (!active) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <h1 className="text-2xl font-semibold tracking-tight">Aucun cluster connecté</h1>
        <p className="text-muted">Ajoute ton cluster Proxmox pour voir ses stockages.</p>
        <Button onClick={onGoConnections}>Ajouter un cluster</Button>
      </div>
    </div>
  );

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Stockage</h1>
          <p className="text-muted">{active.name} · {active.host}</p>
        </div>
        <div className="flex items-center gap-3">
          {(list?.length ?? 0) > 1 && (
            <select aria-label="Cluster" className="field !w-auto !py-1.5 text-sm" value={id ?? ""} onChange={(e) => setConnId(Number(e.target.value))}>
              {list!.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <Button onClick={() => setDialog("add")} className="!px-3 !py-1.5">+ Ajouter un stockage</Button>
          <Button variant="ghost" onClick={() => rows.refetch()} disabled={rows.isFetching} className="!px-3 !py-1.5">
            <span className={rows.isFetching ? "inline-block animate-spin" : ""}>↻</span> Actualiser
          </Button>
        </div>
      </header>

      {rows.error && <Notice kind="error">{(rows.error as Error).message} — <button className="underline" onClick={() => rows.refetch()}>réessayer</button></Notice>}

      <section className="space-y-3" aria-label="Stockages">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {rows.isLoading ? <Skeleton n={3} h="h-44" /> : cards.map((c, i) => <StorageCard key={c.key} card={c} index={i} onOpen={() => setOpened(c.key)} />)}
          {!rows.isLoading && !rows.error && cards.length === 0 && <div className="panel p-6 text-muted sm:col-span-2 lg:col-span-3">Aucun stockage trouvé sur ce cluster.</div>}
        </div>
        {cards.length > 0 && <p className="text-sm text-muted">Clique sur un stockage pour ouvrir son contenu.</p>}
      </section>

      {current && id && <StorageDrawer connId={id} card={current} config={currentConfig} onClose={() => setOpened(null)}
        onEdit={() => setDialog("edit")} onDelete={() => setDialog("delete")} />}
      {id && dialog === "add" && <AddStorageDialog connId={id} onClose={() => setDialog(null)} />}
      {id && dialog === "edit" && currentConfig && <EditStorageDialog connId={id} cfg={currentConfig} onClose={() => setDialog(null)} />}
      {id && dialog === "delete" && current && <DeleteStorageDialog connId={id} storage={current.row.storage}
        onClose={() => { setDialog(null); setOpened(null); }} />}
    </div>
  );
}
