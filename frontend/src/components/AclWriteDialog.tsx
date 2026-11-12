import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type { AccessRole } from "../lib/types/acces";
import type { AclChange, AclPreview } from "../lib/types/admin-session";
import { Modal } from "./Modal";
import { Notice } from "./ui";

const PATH = /^(\/pool\/[A-Za-z0-9][A-Za-z0-9_-]{0,39}|\/vms\/[0-9]{3,9}|\/storage\/[A-Za-z0-9][A-Za-z0-9_-]{0,39}|\/nodes\/[A-Za-z0-9][A-Za-z0-9-]{0,62})$/;
const USER = /^[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}$/;
const GROUP = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const TOKEN = /^[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}![A-Za-z][A-Za-z0-9._-]{1,63}$/;
const DANGEROUS = ["Permissions.Modify", "User.Modify", "Group.Allocate", "Realm.Allocate", "Realm.AllocateUser"];
const KIND_HINT = { user: "ex. bob@pve", group: "ex. staff", token: "ex. bob@pve!ci" } as const;

/** Écrire UNE entrée d'ACL : aperçu, puis application avec l'identifiant retapé. Le serveur revérifie tous les interdits (chemins, rôles, identités protégées). */
export function AclWriteDialog({ connId, presetPath, onClose }: { connId: number; presetPath?: string; onClose: () => void }) {
  const qc = useQueryClient();
  const roles = useQuery({ queryKey: ["access", connId, "roles"], queryFn: () => api<AccessRole[]>(`/api/connections/${connId}/access/roles`), staleTime: 60_000 });
  const [f, setF] = useState<AclChange>({ action: "add", path: presetPath ?? "", kind: "user", ugid: "", role: "", propagate: true });
  const [preview, setPreview] = useState<AclPreview | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null), [done, setDone] = useState(false);

  const set = (patch: Partial<AclChange>) => { setF((v) => ({ ...v, ...patch })); setPreview(null); setTyped(""); setErr(null); };
  const idOk = f.kind === "user" ? USER.test(f.ugid) : f.kind === "group" ? GROUP.test(f.ugid) : TOKEN.test(f.ugid);
  const valid = PATH.test(f.path) && idOk && !!f.role;
  const safeRoles = (roles.data ?? []).filter((r) => f.action === "remove" || (r.roleid !== "Administrator" && !r.privs.some((p) => DANGEROUS.includes(p))));

  const look = async () => {
    setLoading(true); setErr(null);
    try { setPreview(await api<AclPreview>(`/api/connections/${connId}/access/acl/preview`, { method: "POST", body: f })); }
    catch (e) { setErr((e as Error).message); }
    setLoading(false);
  };
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      await api(`/api/connections/${connId}/access/acl`, { method: "PUT", body: { ...f, confirm: true, type_name: typed } });
      await qc.invalidateQueries({ queryKey: ["access", connId] });
      setDone(true); setBusy(false);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const ready = !!preview && preview.allowed && preview.would_change && typed === f.ugid;

  if (done) return (
    <Modal title="Droit enregistré" onClose={onClose} onSubmit={onClose} submitLabel="Fermer" canSubmit>
      <Notice kind="ok">{f.action === "add" ? "Entrée ajoutée" : "Entrée retirée"} : <code>{f.role}</code> pour <code>{f.ugid}</code> sur <code>{f.path}</code>. Elle est relue chez Proxmox et visible dans la liste des ACL.</Notice>
    </Modal>
  );
  return (
    <Modal title="Modifier une ACL" subtitle="Une entrée à la fois, avec l'identité de la session administrateur." onClose={busy ? () => {} : onClose} onSubmit={run}
      submitLabel={f.action === "add" ? "Ajouter le droit" : "Retirer le droit"} danger busy={busy} error={err} canSubmit={ready} wide>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block space-y-1 text-sm"><span className="text-muted">Action</span>
          <select className="field" value={f.action} onChange={(e) => set({ action: e.target.value as AclChange["action"], role: "" })}><option value="add">Ajouter un droit</option><option value="remove">Retirer un droit</option></select></label>
        <label className="block space-y-1 text-sm"><span className="text-muted">Pour</span>
          <select className="field" value={f.kind} onChange={(e) => set({ kind: e.target.value as AclChange["kind"], ugid: "" })}><option value="user">un utilisateur</option><option value="group">un groupe</option><option value="token">un token</option></select></label>
      </div>
      <label className="block space-y-1 text-sm"><span className="text-muted">Identifiant</span>
        <input className="field" value={f.ugid} onChange={(e) => set({ ugid: e.target.value.trim() })} placeholder={KIND_HINT[f.kind]} autoComplete="off" /></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">Chemin</span>
        <input className="field" value={f.path} onChange={(e) => set({ path: e.target.value.trim() })} placeholder="/pool/kaji-test" autoComplete="off" />
        <span className="block text-xs text-muted">Un pool, une VM, un stockage ou un nœud : <code>/pool/…</code>, <code>/vms/115</code>, <code>/storage/…</code>, <code>/nodes/…</code>. Jamais <code>/</code> ni <code>/access</code>.</span></label>
      <label className="block space-y-1 text-sm"><span className="text-muted">Rôle</span>
        <select className="field" value={f.role} onChange={(e) => set({ role: e.target.value })}><option value="">Choisir…</option>{safeRoles.map((r) => <option key={r.roleid} value={r.roleid}>{r.roleid}</option>)}</select>
        <span className="block text-xs text-muted">Les rôles qui permettent de modifier les droits (Administrator…) ne sont pas proposés et sont refusés par le serveur.</span></label>
      {f.action === "add" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={f.propagate} onChange={(e) => set({ propagate: e.target.checked })} /><span>Hériter vers les éléments en dessous</span></label>}
      <button type="button" className="rounded-xl border border-line bg-surface2 px-4 py-2 text-sm disabled:opacity-50" disabled={!valid || loading || busy} onClick={look}>{loading ? "Calcul…" : "Aperçu"}</button>
      {preview && (
        <div className="space-y-3 text-sm">
          {!preview.allowed && <Notice kind="error">{preview.reason}</Notice>}
          {preview.allowed && !preview.would_change && <Notice kind="error">{f.action === "add" ? "Cette entrée existe déjà." : "Cette entrée n'existe pas."}</Notice>}
          {preview.allowed && <>
            <p><b>Droits du rôle {f.role}</b> : <span className="text-muted">{preview.role_privs?.join(", ") || "aucun"}</span></p>
            {preview.effective_before && <p><b>Droits actuels de {f.ugid} sur {f.path}</b> : <span className="text-muted">{preview.effective_before.join(", ") || "aucun"}</span></p>}
            {preview.estimate_after && <p><b>Estimation après ajout</b> : <span className="text-muted">{preview.estimate_after.join(", ")}</span></p>}
            {preview.existing_entries.length > 0 && <p><b>Entrées existantes</b> : <span className="text-muted">{preview.existing_entries.map((e) => e.roleid).join(", ")}</span></p>}
            <p className="text-xs text-muted">{preview.note}</p>
            {preview.would_change && (
              <label className="block text-xs text-muted">Retape <code>{f.ugid}</code> pour confirmer
                <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="field mt-1" /></label>
            )}
          </>}
        </div>
      )}
    </Modal>
  );
}
