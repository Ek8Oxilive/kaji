import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AdminSessionPanel } from "../components/AdminSessionPanel";
import { UserWriteDialog } from "../components/UserWriteDialog";
import { Button, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import type { AccessAcl, AccessGroup, AccessRealm, AccessRole, AccessUser, Feature, Fix } from "../lib/types/acces";
import type { AdminSessionState } from "../lib/types/admin-session";

import { tr, locale } from "../lib/i18n";
const when = (s: number | null) => (s ? new Date(s * 1000).toLocaleDateString(locale()) : tr("jamais"));

const STATUS = {
  ok: { icon: "✓", get label() { return tr("Disponible"); }, cls: "text-ok" },
  missing: { icon: "✗", get label() { return tr("Droit manquant"); }, cls: "text-danger" },
  unknown: { icon: "?", get label() { return tr("Inconnu"); }, cls: "text-warn" },
} as const;

/** Une requête de lecture + son squelette et son erreur ; `children` reçoit les données. */
function Block<T>({ title, count, hint, q, children }: {
  title: string; count?: (d: T) => number; hint?: string;
  q: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown }; children: (d: T) => ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{title}{q.data && count && <span className="ml-2 text-sm font-normal text-muted">({count(q.data)})</span>}</h2>
      {q.isLoading ? <div className="panel h-20 animate-pulse" />
        : q.error ? <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>{tr("réessayer")}</button></Notice>
        : q.data ? children(q.data) : null}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </section>
  );
}

/** Commandes à copier : Kaji n'exécute rien, tu les lances toi-même sur un nœud. */
function FixBox({ fix }: { fix: Fix }) {
  const [copied, setCopied] = useState(false);
  const text = fix.commands.join("\n");
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* le texte reste sélectionnable */ }
  };
  return (
    <div className="mt-2 space-y-2 rounded-xl border border-line bg-surface2 p-3">
      {fix.error ? <p className="text-xs text-warn">{fix.error}</p> : <>
        <p className="text-xs text-muted">{tr("À lancer")}{" "}<strong className="text-fg">{tr("en root, dans le shell d'un nœud Proxmox")}</strong>{tr(". Kaji n'exécute rien.")}</p>
        <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-[var(--code-bg)] p-2 font-mono text-xs" aria-label={tr("Commandes pour : {label}", { label: tr(fix.label) })}>{text}</pre>
        <Button variant="ghost" onClick={copy} className="!px-3 !py-1 text-xs">{copied ? tr("Copié ✓") : tr("Copier")}</Button>
      </>}
    </div>
  );
}

const Empty = ({ children }: { children: ReactNode }) => <div className="rounded-xl border border-line bg-surface2 p-6 text-muted">{children}</div>;
const th = "px-4 py-2 font-normal";

export function Acces({ onGoConnections }: { onGoConnections: () => void }) {
  const { conns, active, id } = useActiveConnection();
  const get = <T,>(what: string) => ({ queryKey: ["access", id, what], enabled: id !== null, staleTime: 15_000, queryFn: () => api<T>(`/api/connections/${id}/access/${what}`) });
  const features = useQuery(get<Feature[]>("features"));
  const users = useQuery(get<AccessUser[]>("users"));
  const groups = useQuery(get<AccessGroup[]>("groups"));
  const roles = useQuery(get<AccessRole[]>("roles"));
  const acl = useQuery(get<AccessAcl[]>("acl"));
  const realms = useQuery(get<AccessRealm[]>("realms"));
  const anyMissing = (features.data ?? []).some((x) => x.status === "missing");
  const fixes = useQuery({ ...get<Fix[]>("fixes"), enabled: id !== null && anyMissing });
  const [openFix, setOpenFix] = useState<string | null>(null);
  const adm = useQuery({ queryKey: ["admin-session", id], enabled: id !== null, refetchInterval: 30_000, queryFn: () => api<AdminSessionState>(`/api/connections/${id}/admin-session`) });
  const adminActive = !!adm.data && adm.data.active;                     // même requête que le panneau : on propose la suppression seulement avec une session ouverte
  const [delUser, setDelUser] = useState<string | null>(null);

  if (conns.isLoading) return <div className="mx-auto max-w-5xl space-y-3">{[0, 1, 2].map((i) => <div key={i} className="panel h-14 animate-pulse" />)}</div>;
  if (!active || id === null) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <h1 className="text-2xl font-semibold tracking-tight">{tr("Aucun cluster connecté")}</h1>
        <p className="text-muted">{tr("Ajoute ton cluster Proxmox pour voir les droits de Kaji.")}</p>
        <Button onClick={onGoConnections}>{tr("Ajouter un cluster")}</Button>
      </div>
    </div>
  );

  const refetch = () => [features, users, groups, roles, acl, realms].forEach((q) => q.refetch());
  const fetching = [features, users, groups, roles, acl, realms].some((q) => q.isFetching);
  const f = features.data ?? [];
  const okN = f.filter((x) => x.status === "ok").length;

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{tr("Accès")}</h1>
          <p className="text-muted">{tr("{name} · Kaji se connecte en tant que", { name: active.name })}{" "}<span className="font-mono text-fg">{active.user}!{active.token_id}</span></p>
        </div>
        <Button variant="ghost" onClick={refetch} disabled={fetching} className="!px-3 !py-1.5">
          <span className={fetching ? "inline-block animate-spin" : ""}>↻</span>{" "}{tr("Actualiser")}</Button>
      </header>

      <Notice kind="ok">{tr("Lecture seule : cette page n'écrit encore aucun droit dans Proxmox. La session administrateur ci-dessous est le socle des prochaines écritures ; en attendant, les droits se gèrent dans l'interface de Proxmox.")}</Notice>

      <AdminSessionPanel connId={id} />

      <Block<Feature[]> title={tr("Droits de Kaji")} q={features}
        count={(d) => d.length}
        hint={tr("Indicatif : privilèges attendus d'après la documentation de Proxmox (calculés par Proxmox pour ce token, héritage compris). « Disponible » veut dire que les privilèges attendus sont là, pas que chaque opération réussira.")}>
        {(d) => d.length === 0 ? <Empty>{tr("Aucune fonction évaluée.")}</Empty> : <>
          <p className="text-sm text-muted">{okN > 1 ? tr("{okN} fonctions sur {length} disponibles", { okN, length: d.length }) : tr("{okN} fonction sur {length} disponible", { okN, length: d.length })}{d.length - okN > 0 ? <> · <span className="text-warn">{tr("{p} à vérifier", { p: d.length - okN })}</span></> : null}</p>
          <ul className="panel divide-y divide-line/60">
            {d.map((x) => {
              const s = STATUS[x.status];
              return (
                <li key={x.id} className="flex items-start gap-3 px-4 py-3">
                  <span className={`mt-0.5 w-5 shrink-0 text-center font-semibold ${s.cls}`} aria-hidden>{s.icon}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">{tr(x.label)}<span className="sr-only"> : {s.label}</span></p>
                    {x.missing.length > 0 && <p className="text-xs text-danger">{tr("Manque : {p}", { p: x.missing.map((m) => `${m.privilege} sur ${m.path}`).join(", ") })}</p>}
                    {x.status === "unknown" && <p className="text-xs text-warn">{tr("Proxmox n'a pas pu confirmer ce droit.")}</p>}
                    {x.status === "missing" && (() => {
                      const fix = fixes.data?.find((f) => f.id === x.id);
                      return <>
                        <button className="mt-1 text-xs underline" onClick={() => setOpenFix(openFix === x.id ? null : x.id)} aria-expanded={openFix === x.id}
                          disabled={!fix}>{fixes.isLoading ? tr("Chargement…") : openFix === x.id ? tr("Masquer la commande") : tr("Voir la commande")}</button>
                        {openFix === x.id && fix && <FixBox fix={fix} />}
                        {fixes.error && <p className="text-xs text-warn">{tr("Commandes indisponibles : {message}", { message: (fixes.error as Error).message })}</p>}
                      </>;
                    })()}
                  </div>
                  <span className={`shrink-0 text-xs ${s.cls}`}>{s.label}</span>
                </li>
              );
            })}
          </ul>
        </>}
      </Block>

      <Block<AccessUser[]> title={tr("Utilisateurs")} q={users} count={(d) => d.length} hint={tr("Seuls les comptes que le token a le droit de voir sont listés.")}>
        {(d) => d.length === 0 ? <Empty>{tr("Aucun utilisateur visible.")}</Empty> : (
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[30rem] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th scope="col" className={th}>{tr("Utilisateur")}</th><th scope="col" className={th}>{tr("Realm")}</th><th scope="col" className={th}>{tr("État")}</th><th scope="col" className={th}>{tr("Expire")}</th>{adminActive && <th scope="col" className={th}><span className="sr-only">{tr("Actions")}</span></th>}</tr></thead>
              <tbody>
                {d.map((u) => (
                  <tr key={u.userid} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-medium">{u.userid}{u.userid === active.user && <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[0.7rem] font-normal text-muted">{tr("Kaji")}</span>}</td>
                    <td className="px-4 py-2 text-muted">{u.realm_type ?? u.realm ?? "–"}</td>
                    <td className="px-4 py-2"><span className={u.enabled ? "text-ok" : "text-danger"}>{u.enabled ? tr("Actif") : tr("Désactivé")}</span></td>
                    <td className="px-4 py-2 text-muted">{when(u.expire)}</td>
                    {adminActive && <td className="px-4 py-2 text-right">
                      {u.realm === "pve" && u.userid !== active.user && u.userid !== "root@pam"
                        ? <Button variant="danger" onClick={() => setDelUser(u.userid)} className="!px-3 !py-1 text-xs" title={tr("Supprimer l'utilisateur {u}", { u: u.userid })}>{tr("Supprimer…")}</Button>
                        : <span className="text-xs text-muted" title={tr("Seuls les utilisateurs du realm pve se suppriment ici ; Kaji et root sont protégés")}>–</span>}
                    </td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      <Block<AccessGroup[]> title={tr("Groupes")} q={groups} count={(d) => d.length}>
        {(d) => d.length === 0 ? <Empty>{tr("Aucun groupe.")}</Empty> : (
          <div className="panel divide-y divide-line/60">
            {d.map((g) => <div key={g.groupid} className="px-4 py-3 text-sm"><span className="font-medium">{g.groupid}</span>{g.comment && <span className="ml-2 text-muted">{g.comment}</span>}<p className="text-xs text-muted">{g.users.length ? g.users.join(", ") : tr("aucun membre")}</p></div>)}
          </div>
        )}
      </Block>

      <Block<AccessAcl[]> title={tr("Droits attribués (ACL)")} q={acl} count={(d) => d.length}
        hint={tr("Proxmox ne montre que les entrées qui concernent ce token. Une entrée posée sur un chemin précis remplace celle héritée du parent pour le même utilisateur : elle ne s'y ajoute pas.")}>
        {(d) => d.length === 0 ? <Empty>{tr("Aucune entrée visible.")}</Empty> : (
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th scope="col" className={th}>{tr("Chemin")}</th><th scope="col" className={th}>{tr("Pour")}</th><th scope="col" className={th}>{tr("Rôle")}</th><th scope="col" className={th}>{tr("Hérité")}</th></tr></thead>
              <tbody>
                {d.map((a) => (
                  <tr key={`${a.path}|${a.ugid}|${a.roleid}`} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-mono text-xs">{a.path}</td>
                    <td className="px-4 py-2">{a.ugid}<span className="ml-2 text-xs text-muted">{a.type ?? ""}</span></td>
                    <td className="px-4 py-2">{a.roleid}</td>
                    <td className="px-4 py-2 text-muted">{a.propagate ? tr("oui") : tr("non")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      <Block<AccessRole[]> title={tr("Rôles")} q={roles} count={(d) => d.length} hint={tr("Un rôle est un ensemble de privilèges. Clique sur un rôle pour voir lesquels.")}>
        {(d) => d.length === 0 ? <Empty>{tr("Aucun rôle visible.")}</Empty> : (
          <div className="panel divide-y divide-line/60">
            {d.map((r) => (
              <details key={r.roleid} className="group px-4 py-2.5">
                <summary className="flex cursor-pointer list-none items-center gap-3 text-sm marker:hidden">
                  <span className="text-muted transition group-open:rotate-90" aria-hidden>›</span>
                  <span className="font-medium">{r.roleid}</span>
                  {r.special && <span className="rounded-md border border-line px-1.5 py-0.5 text-[0.7rem] text-muted">{tr("intégré")}</span>}
                  <span className="ml-auto text-xs text-muted">{tr("{length} privilège{p}", { length: r.privs.length, p: r.privs.length > 1 ? "s" : "" })}</span>
                </summary>
                <p className="mt-2 flex flex-wrap gap-1.5 pl-6">
                  {r.privs.length === 0 ? <span className="text-xs text-muted">{tr("Aucun privilège.")}</span>
                    : r.privs.map((p) => <span key={p} className="rounded-full border border-line bg-surface2 px-2 py-0.5 font-mono text-xs text-muted">{p}</span>)}
                </p>
              </details>
            ))}
          </div>
        )}
      </Block>

      <Block<AccessRealm[]> title={tr("Realms")} q={realms} count={(d) => d.length}>
        {(d) => d.length === 0 ? <Empty>{tr("Aucun realm.")}</Empty> : (
          <div className="panel divide-y divide-line/60">
            {d.map((r) => <div key={r.realm} className="px-4 py-3 text-sm"><span className="font-medium">{r.realm}</span><span className="ml-2 text-xs text-muted">{r.type ?? ""}{r.comment ? ` · ${r.comment}` : ""}</span></div>)}
          </div>
        )}
      </Block>

      {delUser && <UserWriteDialog connId={id} preset={{ act: "delete-user", id: delUser }} onClose={() => setDelUser(null)} />}
    </div>
  );
}
