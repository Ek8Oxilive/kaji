import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { TYPE_LABEL, type MetricsPreview, type MetricsRow, type MetricsServer, type MetricsType } from "../lib/types/metrics";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

type Mode = { kind: "new" } | { kind: "edit"; row: MetricsRow } | { kind: "delete"; row: MetricsRow };
type F = Record<string, string>;
const num = (s: string) => (s.trim() === "" ? undefined : Number(s));

/** Datacenter → Metric Server : InfluxDB, Graphite, OpenTelemetry. Secrets jamais relus : champ vide = inchangé, case « retirer » pour les enlever. */
export function MetricsServers({ connId }: { connId: number }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const q = useQuery({ queryKey: ["metrics-servers", connId], queryFn: () => api<MetricsRow[]>(`/api/connections/${connId}/metrics/servers`) });
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Serveurs de métriques</h2><Button variant="ghost" onClick={() => setMode({ kind: "new" })}>Ajouter un serveur…</Button></div>
      {q.error ? <Notice kind="error">{(q.error as Error).message}</Notice> : (q.data ?? []).length === 0 ? <p className="text-sm text-muted">Aucun serveur de métriques : Proxmox n'envoie ses métriques nulle part.</p> : (
        <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[32rem] text-sm">
          <thead><tr className="border-b border-line text-left text-xs text-muted">{["Nom", "Type", "Serveur", "État", ""].map((h) => <th key={h} scope="col" className="px-4 py-2 font-normal">{h}</th>)}</tr></thead>
          <tbody>{(q.data ?? []).map((r) => (
            <tr key={r.id} className={`border-b border-line/60 last:border-0 ${r.disable ? "opacity-60" : ""}`}>
              <td className="px-4 py-2 font-mono">{r.id}</td><td className="px-4 py-2 text-muted">{TYPE_LABEL[r.type]}</td><td className="px-4 py-2 font-mono text-muted">{r.server ?? "?"}:{r.port ?? "?"}</td>
              <td className="px-4 py-2 text-muted">{r.disable ? "désactivé" : "actif"}</td>
              <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right text-xs"><button className="underline" onClick={() => setMode({ kind: "edit", row: r })}>Modifier</button><button className="text-danger underline" onClick={() => setMode({ kind: "delete", row: r })}>Supprimer</button></td>
            </tr>))}</tbody></table></div>)}
      {mode && <MetricsDialog connId={connId} mode={mode} onClose={() => setMode(null)} />}
    </section>
  );
}

function MetricsDialog({ connId, mode, onClose }: { connId: number; mode: Mode; onClose: () => void }) {
  const qc = useQueryClient();
  const k = mode.kind, row = mode.kind === "new" ? null : mode.row;
  const detail = useQuery({ queryKey: ["metrics-server", connId, row?.id], queryFn: () => api<MetricsServer>(`/api/connections/${connId}/metrics/servers/${row!.id}`), enabled: k === "edit" });
  const d = detail.data;
  const [id, setId] = useState(""), [type, setType] = useState<MetricsType>("influxdb");
  const [f, setF] = useState<F>({}), [disable, setDisable] = useState(false), [vssl, setVssl] = useState<"" | "yes" | "no">(""), [clearSecret, setClearSecret] = useState(false);
  const [preview, setPreview] = useState<MetricsPreview | null>(null), [ack, setAck] = useState(false), [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [done, setDone] = useState(false), [err, setErr] = useState<string | null>(null);
  const t: MetricsType = k === "edit" ? (row!.type) : type;
  useEffect(() => {
    if (!d) return;
    setF({ server: d.server ?? "", port: d.port?.toString() ?? "", influxdbproto: d.influxdbproto ?? "", organization: d.organization ?? "", bucket: d.bucket ?? "", max_body_size: d.max_body_size?.toString() ?? "", mtu: d.mtu?.toString() ?? "",
      api_path_prefix: d.api_path_prefix ?? "", proto: d.proto ?? "", path: d.path ?? "", timeout: d.timeout?.toString() ?? "", otel_protocol: d.otel_protocol ?? "", otel_path: d.otel_path ?? "", otel_timeout: d.otel_timeout?.toString() ?? "",
      otel_compression: d.otel_compression ?? "", otel_max_body_size: d.otel_max_body_size?.toString() ?? "" });
    setDisable(d.disable); setVssl(((t === "influxdb" ? d.verify_certificate : d.otel_verify_ssl) ?? null) === null ? "" : (t === "influxdb" ? d.verify_certificate : d.otel_verify_ssl) ? "yes" : "no");
  }, [d, t]);
  useEffect(() => { setPreview(null); setAck(false); setErr(null); }, [id, type, f, disable, vssl, clearSecret, typed]);
  const set = (key: string) => (v: string) => setF((cur) => ({ ...cur, [key]: v }));
  const txt = (label: string, key: string, hint?: string, kind: "text" | "number" | "password" = "text") => (
    <Field label={label} type={kind} value={f[key] ?? ""} onChange={(e) => set(key)(e.target.value)} hint={hint} autoComplete="off" />);
  const sel = (label: string, key: string, opts: string[]) => (
    <label className="block space-y-1.5 text-sm"><span className="text-muted">{label}</span><select className="field" value={f[key] ?? ""} onChange={(e) => set(key)(e.target.value)}><option value="">Défaut de Proxmox</option>{opts.map((o) => <option key={o}>{o}</option>)}</select></label>);

  /** Corps : à la création tout ce qui est rempli ; en modification seulement ce qui a changé (secrets : seulement s'ils sont saisis). */
  const body = (extra: Record<string, unknown>) => {
    const b: Record<string, unknown> = {}, clear: string[] = [];
    const cur = (key: string) => (d ? ((d as unknown as Record<string, unknown>)[key]?.toString() ?? "") : "");
    const field = (key: string, asNum = false) => {
      const v = f[key] ?? "";
      if (k === "edit" && v === cur(key)) return;
      if (v !== "") b[key] = asNum ? num(v) : v; else if (k === "edit" && cur(key) !== "" && key !== "server" && key !== "port") clear.push(key);
    };
    field("server"); field("port", true);
    if (t === "influxdb") { field("influxdbproto"); field("organization"); field("bucket"); field("max_body_size", true); field("mtu", true); field("api_path_prefix"); if (f.token) b.token = f.token; else if (clearSecret) clear.push("token"); }
    if (t === "graphite") { field("proto"); field("path"); field("mtu", true); field("timeout", true); }
    if (t === "opentelemetry") { field("otel_protocol"); field("otel_path"); field("otel_timeout", true); field("otel_compression"); field("otel_max_body_size", true); if (f.otel_headers) b.otel_headers = f.otel_headers; else if (clearSecret) clear.push("otel_headers"); if (f.otel_resource_attributes) b.otel_resource_attributes = f.otel_resource_attributes; }
    if (vssl) b[t === "influxdb" ? "verify_certificate" : "otel_verify_ssl"] = vssl === "yes";
    if (k === "new" || disable !== d?.disable) b.disable = disable;
    return { ...b, ...(clear.length ? { clear } : {}), ...(k === "new" ? { id, type } : {}), ...extra };
  };
  const base = `/api/connections/${connId}/metrics/servers`;
  const request = (extra: Record<string, unknown>) => k === "new" ? { path: base, init: { method: "POST", body: body(extra) } }
    : k === "edit" ? { path: `${base}/${row!.id}`, init: { method: "PUT", body: { ...body(extra), digest: d?.digest ?? undefined } } }
    : { path: `${base}/${row!.id}?${new URLSearchParams({ ...(extra.dry_run ? { dry_run: "true" } : { confirm: "true", type_name: typed }) })}`, init: { method: "DELETE" } };
  const look = async () => { setErr(null); try { const r = request({ dry_run: true }); setPreview(await api<MetricsPreview>(r.path, r.init)); } catch (e) { setErr((e as Error).message); } };
  const run = async () => {
    setBusy(true); setErr(null);
    try { const r = request({ confirm: true }); await api(r.path, r.init); await qc.invalidateQueries({ queryKey: ["metrics-servers", connId] }); setDone(true); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const needs = !!preview?.needs_confirm;
  const ready = !!preview && (k !== "delete" || typed === row?.id) && (!needs || ack);
  const readyToLook = k === "new" ? id !== "" && (f.server ?? "") !== "" && (f.port ?? "") !== "" : k === "edit" ? !!d : true;

  if (done) return <Modal title="Fait" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit><Notice kind="ok">{k === "delete" ? "Serveur supprimé." : "Enregistré, relu chez Proxmox."}</Notice></Modal>;
  return (
    <Modal title={k === "new" ? "Ajouter un serveur de métriques" : k === "edit" ? `Modifier ${row!.id}` : `Supprimer ${row!.id}`} subtitle="L'aperçu dit ce qui sera envoyé ; les secrets ne sont jamais affichés." onClose={busy ? () => {} : onClose}
      onSubmit={run} submitLabel={k === "delete" ? "Supprimer" : "Appliquer"} danger={k === "delete" || needs} busy={busy} error={err} canSubmit={ready} wide>
      {k === "delete" ? <>
        <Notice kind="error">Les métriques cessent de partir vers <code>{row!.server}:{row!.port}</code>. Retape <code>{row!.id}</code> pour confirmer.<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-2" /></Notice>
      </> : k === "edit" && !d ? <p className="text-sm text-muted">Chargement…</p> : <>
        {k === "new" && <div className="grid gap-4 sm:grid-cols-2"><Field label="Nom" value={id} onChange={(e) => setId(e.target.value)} maxLength={64} hint="Lettre puis lettres, chiffres, _ ou -" autoComplete="off" />
          <label className="block space-y-1.5 text-sm"><span className="text-muted">Type</span><select className="field" value={type} onChange={(e) => { setType(e.target.value as MetricsType); setVssl(""); }}>{(Object.keys(TYPE_LABEL) as MetricsType[]).map((x) => <option key={x} value={x}>{TYPE_LABEL[x]}</option>)}</select></label></div>}
        <div className="grid gap-4 sm:grid-cols-2">{txt("Serveur (nom ou adresse IP)", "server", "Adresses locales (127.x, localhost…) refusées")}{txt("Port", "port", "1 à 65535", "number")}</div>
        {t === "influxdb" && <><div className="grid gap-4 sm:grid-cols-3">{sel("Protocole", "influxdbproto", ["udp", "http", "https"])}{txt("Organisation", "organization")}{txt("Bucket", "bucket")}</div>
          <div className="grid gap-4 sm:grid-cols-3">{txt("Taille max. du corps (octets)", "max_body_size", undefined, "number")}{txt("MTU (UDP)", "mtu", "512 à 65536", "number")}{txt("Préfixe de chemin d'API", "api_path_prefix")}</div>
          {txt(k === "edit" ? "Jeton d'accès (jamais relu : laisser vide pour conserver l'actuel)" : "Jeton d'accès", "token", "Écriture seule : Proxmox ne le renvoie jamais", "password")}
          {k === "edit" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={clearSecret} onChange={(e) => setClearSecret(e.target.checked)} />Retirer le jeton</label>}</>}
        {t === "graphite" && <div className="grid gap-4 sm:grid-cols-4">{sel("Protocole", "proto", ["udp", "tcp"])}{txt("Chemin racine", "path", "ex. proxmox.moncluster")}{txt("MTU (UDP)", "mtu", "512 à 65536", "number")}{txt("Délai TCP (s)", "timeout", undefined, "number")}</div>}
        {t === "opentelemetry" && <><div className="grid gap-4 sm:grid-cols-3">{sel("Protocole", "otel_protocol", ["http", "https"])}{txt("Chemin OTLP", "otel_path", "ex. /v1/metrics")}{txt("Délai (s)", "otel_timeout", "1 à 10", "number")}</div>
          <div className="grid gap-4 sm:grid-cols-2">{sel("Compression", "otel_compression", ["none", "gzip"])}{txt("Taille max. du corps (octets)", "otel_max_body_size", "1024 minimum", "number")}</div>
          {txt(k === "edit" ? "En-têtes HTTP (jamais relus : laisser vide pour conserver les actuels)" : "En-têtes HTTP (JSON encodé en base64)", "otel_headers", "Écriture seule : Proxmox ne les renvoie jamais", "password")}
          {k === "edit" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={clearSecret} onChange={(e) => setClearSecret(e.target.checked)} />Retirer les en-têtes</label>}
          {txt("Attributs de ressource (JSON encodé en base64)", "otel_resource_attributes")}</>}
        {t !== "graphite" && <label className="block space-y-1.5 text-sm"><span className="text-muted">Vérifier le certificat</span><select className="field" value={vssl} onChange={(e) => setVssl(e.target.value as typeof vssl)}><option value="">Défaut de Proxmox (oui)</option><option value="yes">Oui</option><option value="no">Non</option></select></label>}
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={disable} onChange={(e) => setDisable(e.target.checked)} /><span><b>Désactivé</b> : la configuration existe mais rien n'est envoyé</span></label>
      </>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!readyToLook} onClick={look}>Aperçu</button>
      {preview && <div className="space-y-3 text-sm">
        {k === "delete" ? <Notice kind="ok">Sera supprimé : <code>{row!.id}</code>.</Notice> : <Notice kind="ok">Sera envoyé : <code>{Object.entries(preview.params).map(([a, b]) => `${a}=${b}`).join(", ") || "rien"}</code>{preview.remove?.length ? <> · retiré : <code>{preview.remove.join(", ")}</code></> : null}</Notice>}
        {needs && <Notice kind="error">Les métriques de <b>tout le cluster</b> partiront vers ce serveur.<label className="mt-2 flex gap-2"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>Je comprends, c'est le serveur voulu</span></label></Notice>}
      </div>}
    </Modal>
  );
}
