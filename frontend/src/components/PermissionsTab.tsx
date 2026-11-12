import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type { Guest } from "../lib/api";
import type { AccessAcl } from "../lib/types/acces";
import { AclWriteDialog } from "./AclWriteDialog";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
/**
 * Onglet « Permissions » d'une machine (M6) : les entrées d'ACL qui s'appliquent à cette machine (sur la machine, sur `/vms` et sur `/`, ces deux
 * dernières par héritage). Lecture seule ; ajouter ou retirer un droit sur `/vms/<id>` passe par la même fenêtre et la même session administrateur
 * que la page « Accès ». Proxmox ne montre au token de Kaji que les entrées qui le concernent : la liste peut être incomplète.
 */
export function PermissionsTab({ connId, guest }: { connId: number; guest: Guest }) {
  const [open, setOpen] = useState(false);
  const acl = useQuery({ queryKey: ["access", connId, "acl"], queryFn: () => api<AccessAcl[]>(`/api/connections/${connId}/access/acl`), staleTime: 10_000 });
  const own = `/vms/${guest.vmid}`;
  const scope = (a: AccessAcl) => (a.path === own ? tr("cette machine") : a.path === "/vms" ? tr("toutes les machines (hérité)") : a.path === "/" ? tr("tout le cluster (hérité)") : "");
  const rows = (acl.data ?? []).filter((a) => a.path === own || (a.propagate && (a.path === "/vms" || a.path === "/")))
    .sort((a, b) => (a.path === own ? 0 : a.path === "/vms" ? 1 : 2) - (b.path === own ? 0 : b.path === "/vms" ? 1 : 2) || a.ugid.localeCompare(b.ugid));
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">{tr("Qui peut faire quoi sur cette machine. Un droit posé sur la machine s'ajoute à ceux hérités de")}{" "}<code>{tr("/vms")}</code>{" "}{tr("et de")}{" "}<code>/</code>.</p>
        <Button onClick={() => setOpen(true)} className="shrink-0">{tr("Modifier une ACL…")}</Button>
      </div>
      {acl.error ? <Notice kind="error">{(acl.error as Error).message}</Notice>
        : acl.isLoading ? <p className="text-sm text-muted">{tr("Chargement…")}</p>
        : rows.length === 0 ? <p className="rounded-xl border border-line p-4 text-sm text-muted">{tr("Aucune entrée d'ACL visible pour cette machine. Proxmox ne montre au token de Kaji que les entrées qui le concernent.")}</p>
        : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted"><tr>{[tr("Pour"), tr("Type"), tr("Rôle"), tr("Chemin"), tr("S'applique à")].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{rows.map((a, i) => (
                <tr key={`${a.path}-${a.ugid}-${a.roleid}-${i}`} className="border-t border-line/60">
                  <td className="px-4 py-2 font-mono">{a.ugid}</td>
                  <td className="px-4 py-2 text-muted">{{ user: tr("utilisateur"), group: tr("groupe"), token: "token" }[a.type ?? ""] ?? a.type ?? "—"}</td>
                  <td className="px-4 py-2">{a.roleid}</td>
                  <td className="px-4 py-2 font-mono text-muted">{a.path}</td>
                  <td className="px-4 py-2 text-muted">{scope(a)}</td>
                </tr>))}</tbody>
            </table>
          </div>)}
      {open && <AclWriteDialog connId={connId} presetPath={own} onClose={() => setOpen(false)} />}
    </div>
  );
}
