import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import { Modal } from "./Modal";
import { Notice } from "./ui";

import { tr } from "../lib/i18n";
type Act = "alias-create" | "alias-update" | "alias-delete" | "ipset-create" | "ipset-delete" | "entry-add" | "entry-remove" | "group-create" | "group-delete";
const LABEL: Record<Act, string> = {
  get "alias-create"() { return tr("Créer un alias"); }, get "alias-update"() { return tr("Modifier un alias"); }, get "alias-delete"() { return tr("Supprimer un alias"); }, get "ipset-create"() { return tr("Créer un IPSet"); }, get "ipset-delete"() { return tr("Supprimer un IPSet"); },
  get "entry-add"() { return tr("Ajouter une entrée à un IPSet"); }, get "entry-remove"() { return tr("Retirer une entrée d'un IPSet"); }, get "group-create"() { return tr("Créer un groupe de sécurité"); }, get "group-delete"() { return tr("Supprimer un groupe de sécurité"); },
};
const NAME = /^[A-Za-z][A-Za-z0-9_-]{1,63}$/, GROUP = /^[A-Za-z][A-Za-z0-9_-]{1,17}$/;
const ADDR = /^[0-9A-Fa-f:.]+(\/[0-9]{1,3})?$|^(dc\/|guest\/)?[A-Za-z][A-Za-z0-9_-]{1,63}$/;

/** Alias, IPSets et groupes du datacenter. Un objet utilisé par un pare-feu ACTIF est verrouillé : le serveur le refuse tant que tu ne reconnais pas le risque. */
export function FwObjectsDialog({ connId, onClose, guest }: { connId: number; onClose: () => void; guest?: { node: string; gtype: "qemu" | "lxc"; vmid: number } }) {
  const qc = useQueryClient();
  const [act, setAct] = useState<Act>("alias-create");
  const [name, setName] = useState(""), [cidr, setCidr] = useState(""), [comment, setComment] = useState(""), [typed, setTyped] = useState("");
  const [nomatch, setNomatch] = useState(false), [members, setMembers] = useState(false), [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false), [done, setDone] = useState(false), [err, setErr] = useState<string | null>(null), [locked, setLocked] = useState<string | null>(null);
  const base = guest ? `/api/connections/${connId}/firewall/guests/${encodeURIComponent(guest.node)}/${guest.gtype}/${guest.vmid}` : `/api/connections/${connId}/firewall/cluster`;
  const acts = (Object.keys(LABEL) as Act[]).filter((a) => !guest || !a.startsWith("group"));       // les groupes de sécurité n'existent qu'au datacenter
  const isGroup = act.startsWith("group"), needsCidr = ["alias-create", "alias-update", "entry-add", "entry-remove"].includes(act);
  const destructive = ["alias-delete", "ipset-delete", "entry-remove", "group-delete"].includes(act);
  const retype = act === "entry-remove" ? cidr : (act === "alias-update" || destructive) ? name : "";
  const fieldsOk = (isGroup ? GROUP : NAME).test(name) && (!needsCidr || ADDR.test(cidr));
  const valid = fieldsOk && (retype === "" || typed === retype);                      // le champ « Retape… » s'affiche dès que le nom est valide (avant, il exigeait d'avoir déjà retapé : jamais affiché)

  useEffect(() => { setLocked(null); setAck(false); setErr(null); setTyped(""); }, [act, name, cidr]);
  const reset = (a: Act) => { setAct(a); setName(""); setCidr(""); setComment(""); setNomatch(false); setMembers(false); };

  const run = async () => {
    setBusy(true); setErr(null);
    const q = (extra: Record<string, string> = {}) => new URLSearchParams({ confirm: "true", typed, ...(ack ? { acknowledge_live: "true" } : {}), ...extra }).toString();
    const live = ack ? { acknowledge_live: true } : {};
    try {
      if (act === "alias-create") await api(`${base}/aliases`, { method: "POST", body: { name, cidr, ...(comment ? { comment } : {}), confirm: true } });
      else if (act === "alias-update") await api(`${base}/aliases/${name}`, { method: "PUT", body: { cidr, ...(comment ? { comment } : {}), confirm: true, type_name: name, ...live } });
      else if (act === "alias-delete") await api(`${base}/aliases/${name}?${q()}`, { method: "DELETE" });
      else if (act === "ipset-create") await api(`${base}/ipsets`, { method: "POST", body: { name, ...(comment ? { comment } : {}), confirm: true } });
      else if (act === "ipset-delete") await api(`${base}/ipsets/${name}?${q(members ? { delete_members: "true" } : {})}`, { method: "DELETE" });
      else if (act === "entry-add") await api(`${base}/ipsets/${name}/entries`, { method: "POST", body: { cidr, ...(comment ? { comment } : {}), nomatch, confirm: true, ...live } });
      else if (act === "entry-remove") await api(`${base}/ipsets/${name}/entries?${q({ cidr })}`, { method: "DELETE" });
      else if (act === "group-create") await api(`${base}/groups`, { method: "POST", body: { name, ...(comment ? { comment } : {}), confirm: true } });
      else await api(`${base}/groups/${name}?${q()}`, { method: "DELETE" });
      await qc.invalidateQueries({ queryKey: ["fw-cluster", connId] }); await qc.invalidateQueries({ queryKey: ["fw-guest", connId] });
      setDone(true);
    } catch (e) {
      const m = (e as Error).message;
      if (e instanceof ApiError && e.status === 409 && m.includes("acknowledge_live")) setLocked(m); else setErr(m);
    }
    setBusy(false);
  };

  if (done) return <Modal title={tr("Fait")} onClose={onClose} onSubmit={onClose} submitLabel={tr("Fermer")} canSubmit><Notice kind="ok">{LABEL[act]} : <code>{name}</code>{tr(". Relu chez Proxmox.")}</Notice></Modal>;
  return (
    <Modal title={tr("Objets du pare-feu")} subtitle={tr("{p}. Une écriture à la fois ; Proxmox est relu après chaque écriture.", { p: guest ? `Machine ${guest.gtype === "qemu" ? "VM" : "LXC"} ${guest.vmid}` : tr("Datacenter") })} onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={tr("Appliquer")} danger={destructive || !!locked} busy={busy} error={err} canSubmit={valid && (!locked || ack)}>
      <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Action")}</span>
        <select className="field" value={act} onChange={(e) => reset(e.target.value as Act)}>{acts.map((a) => <option key={a} value={a}>{LABEL[a]}</option>)}</select></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">{isGroup ? tr("Nom du groupe (18 caractères au plus)") : act.startsWith("entry") ? "IPSet" : tr("Nom")}</span>
        <input className="field" value={name} onChange={(e) => setName(e.target.value.trim())} autoComplete="off" /></label>
      {needsCidr && <label className="block space-y-1 text-sm"><span className="text-muted">{act.startsWith("entry") ? tr("Adresse, réseau ou alias") : tr("Adresse ou réseau")}</span>
        <input className="field" value={cidr} onChange={(e) => setCidr(e.target.value.trim())} placeholder="192.168.1.0/24" autoComplete="off" /></label>}
      {(act === "alias-create" || act === "alias-update" || act === "ipset-create" || act === "group-create" || act === "entry-add") && <label className="block space-y-1 text-sm"><span className="text-muted">{tr("Commentaire (facultatif)")}</span>
        <input className="field" value={comment} maxLength={100} onChange={(e) => setComment(e.target.value)} autoComplete="off" /></label>}
      {act === "entry-add" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={nomatch} onChange={(e) => setNomatch(e.target.checked)} /><span>{tr("Exclure (nomatch)")}</span></label>}
      {act === "ipset-delete" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={members} onChange={(e) => setMembers(e.target.checked)} /><span>{tr("Supprimer aussi ses entrées s'il n'est pas vide")}</span></label>}
      {fieldsOk && retype !== "" && <label className="block text-xs text-muted">{tr("Retape")}{" "}<code>{retype}</code>{" "}{tr("pour confirmer")}<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>}
      {locked && <Notice kind="error">{locked}
        <label className="mt-2 flex gap-2 text-sm"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{tr("Je comprends que cela peut couper l'accès et je veux continuer")}</span></label></Notice>}
    </Modal>
  );
}
