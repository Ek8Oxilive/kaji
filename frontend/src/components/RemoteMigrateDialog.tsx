import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { LONG_TASK_SECONDS, runTask } from "../lib/tasks";
import { Modal } from "./Modal";
import { Notice } from "./ui";

type Dry = { dry_run: true; target: { host: string; port: number | null; token_id: string; fingerprint: string }; params: Record<string, string | number>; running: boolean; name: string;
  locks: { delete: boolean; cut: boolean; running: boolean } };
const PHRASE = "COUPURE POSSIBLE";
const FP = /^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$/;
const TOKEN = /^[A-Za-z0-9._-]{1,64}@[A-Za-z][A-Za-z0-9._-]{1,31}![A-Za-z][A-Za-z0-9._-]{1,63}$/;
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/** Migrer une machine vers un AUTRE cluster (`remote_migrate`, expérimental chez Proxmox, jamais essayé en réel). Le jeton du cluster distant s'écrit ici, n'est jamais gardé, relu ni affiché ;
 *  l'empreinte de son certificat est obligatoire ; « supprimer l'original » exige le nom de la machine et la phrase. L'aperçu ne migre rien. */
export function RemoteMigrateDialog({ connId, node, gtype, vmid, name, running, onClose }: { connId: number; node: string; gtype: "qemu" | "lxc"; vmid: number; name: string; running: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const lxc = gtype === "lxc";
  const [f, setF] = useState({ host: "", port: "", token: "", secret: "", fp: "", storage: "", bridge: "", vmid: "", bw: "" });
  const [live, setLive] = useState(false), [del, setDel] = useState(false), [typed, setTyped] = useState(""), [ack, setAck] = useState(false), [phrase, setPhrase] = useState(""), [sure, setSure] = useState(false);
  const [dry, setDry] = useState<Dry | null>(null), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (v: string) => { setF((c) => ({ ...c, [k]: v })); setDry(null); };
  useEffect(() => { setDry(null); }, [live, del]);
  const base = `/api/connections/${connId}/guests/${node}/${gtype}/${vmid}/remote-migrate`;

  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));
  const body = () => ({
    target_host: f.host.trim(), ...(f.port.trim() ? { target_port: Number(f.port) } : {}), target_token_id: f.token.trim(), target_secret: f.secret.trim(), target_fingerprint: f.fp.trim(),
    target_storage: f.storage.trim(), target_bridge: f.bridge.trim(), ...(num(f.vmid) !== undefined ? { target_vmid: num(f.vmid) } : {}), ...(num(f.bw) !== undefined ? { bwlimit: num(f.bw) } : {}),
    ...(running ? (lxc ? { restart: !live, online: live } : { online: true }) : {}), ...(del ? { delete: true } : {}),
  });
  const valid = f.host.trim() !== "" && TOKEN.test(f.token.trim()) && UUID.test(f.secret.trim()) && FP.test(f.fp.trim()) && f.storage.trim() !== "" && f.bridge.trim() !== ""
    && (f.port.trim() === "" || /^[0-9]{1,5}$/.test(f.port)) && (f.vmid.trim() === "" || /^[0-9]{3,9}$/.test(f.vmid)) && (f.bw.trim() === "" || /^[0-9]{1,10}$/.test(f.bw));
  const canRun = valid && dry !== null && sure && (!del || (typed === name && ack && phrase === PHRASE));

  const preview = async () => {
    setBusy(true); setErr(null);
    try { setDry(await api<Dry>(base, { method: "POST", body: { ...body(), dry_run: true } })); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      await runTask(connId, node, () => api(base, { method: "POST", body: { ...body(), confirm: true, ...(del ? { type_name: typed, acknowledge_cut_access: true, phrase } : {}) } }), tr("Migration vers un autre cluster"), LONG_TASK_SECONDS);
      setF((c) => ({ ...c, secret: "" }));
      await qc.invalidateQueries({ queryKey: ["cluster", connId, "guests"] });
      onClose();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const field = (k: keyof typeof f, label: string, opts: { type?: string; ph?: string; hint?: string } = {}) => (
    <label className="block space-y-1 text-sm"><span className="text-muted">{label}</span>
      <input className="field" type={opts.type ?? "text"} value={f[k]} onChange={(e) => set(k)(e.target.value)} placeholder={opts.ph} autoComplete={opts.type === "password" ? "new-password" : "off"} />
      {opts.hint && <span className="block text-xs text-muted">{opts.hint}</span>}</label>);

  return (
    <Modal title={tr("Migrer « {name} » vers un autre cluster", { name })} subtitle={tr("Fonction expérimentale de Proxmox, jamais essayée par Kaji sur un vrai cluster. Le jeton du cluster distant n'est ni gardé ni affiché.")}
      onClose={busy ? () => {} : onClose} onSubmit={dry ? run : preview} submitLabel={dry ? tr("Migrer") : tr("Aperçu")} danger={del} busy={busy} error={err} canSubmit={dry ? canRun : valid} wide>
      <div className="grid gap-3 sm:grid-cols-2">
        {field("host", tr("Nœud du cluster distant"), { ph: "pve.autre.example.org", hint: tr("Nom ou adresse IP ; les adresses locales sont refusées") })}
        {field("port", tr("Port (facultatif)"), { ph: "8006" })}
        {field("token", tr("Jeton d'API du cluster distant"), { ph: "migrate@pve!kaji", hint: tr("utilisateur@realm!nom ; droits d'allocation de VM et de stockage sur le cluster distant") })}
        {field("secret", tr("Secret du jeton"), { type: "password", hint: tr("Écriture seule : jamais relu ni affiché, vidé après l'envoi.") })}
        {field("fp", tr("Empreinte SHA-256 du certificat distant"), { ph: "AA:BB:…", hint: tr("Obligatoire : Kaji ne se connecte jamais sans vérifier le certificat. Lis-la sur le cluster distant.") })}
        {field("vmid", tr("Identifiant sur le cluster distant (facultatif)"), { ph: String(vmid) })}
        {field("storage", tr("Stockage de destination"), { ph: "local-lvm", hint: tr("Un identifiant, 1 (même nom), ou source:cible,source:cible") })}
        {field("bridge", tr("Pont de destination"), { ph: "vmbr0", hint: tr("Un identifiant, 1 (même nom), ou source:cible,source:cible") })}
        {field("bw", tr("Limite de débit en Kio/s (facultatif)"), { ph: "0" })}
      </div>
      {running && <p className="text-sm text-muted">{lxc ? tr("Le conteneur est en marche.") : tr("La VM est en marche : migration à chaud.")}</p>}
      {running && lxc && <label className="flex gap-2 text-sm"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /><span>{tr("Migration à chaud (expérimental) au lieu d'un redémarrage")}</span></label>}
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={del} onChange={(e) => setDel(e.target.checked)} /><span>{tr("Supprimer la machine d'origine après la migration")}</span></label>
      {del && <Notice kind="error">{tr("Si la migration échoue ou si la copie est incomplète, les données seront perdues. Par défaut, l'original est gardé arrêté.")}</Notice>}
      {dry && <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
        <p>{tr("Aperçu : rien n'a été migré. Cible {host} avec le jeton {token}, empreinte {fp}.", { host: dry.target.host, token: dry.target.token_id, fp: dry.target.fingerprint.slice(0, 11) + "…" })}</p>
        <dl className="text-xs">{Object.entries(dry.params).map(([k, v]) => <div key={k} className="flex justify-between gap-4 py-0.5"><dt className="text-muted">{k}</dt><dd className="break-all font-mono">{String(v)}</dd></div>)}</dl>
        <label className="flex gap-2"><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} /><span>{tr("Je comprends que cette migration est expérimentale")}</span></label>
        {del && <>
          <label className="flex gap-2"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{tr("J'accepte la perte de l'original si la copie est incomplète")}</span></label>
          <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{dry.name}</code>{" "}{tr("pour confirmer")}<input className="field mt-1" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" /></label>
          <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{PHRASE}</code>{" "}{tr("pour confirmer")}<input className="field mt-1" value={phrase} onChange={(e) => setPhrase(e.target.value)} autoComplete="off" /></label>
        </>}
      </div>}
    </Modal>
  );
}
