import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Button, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useActiveConnection } from "../lib/connection";
import type { AccessAcl, AccessGroup, AccessRealm, AccessRole, AccessUser, Feature } from "../lib/types/acces";

const when = (s: number | null) => (s ? new Date(s * 1000).toLocaleDateString("fr-FR") : "jamais");

const STATUS = {
  ok: { icon: "✓", label: "Disponible", cls: "text-ok" },
  missing: { icon: "✗", label: "Droit manquant", cls: "text-danger" },
  unknown: { icon: "?", label: "Inconnu", cls: "text-warn" },
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
        : q.error ? <Notice kind="error">{(q.error as Error).message} — <button className="underline" onClick={() => q.refetch()}>réessayer</button></Notice>
        : q.data ? children(q.data) : null}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </section>
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

  if (conns.isLoading) return <div className="mx-auto max-w-5xl space-y-3">{[0, 1, 2].map((i) => <div key={i} className="panel h-14 animate-pulse" />)}</div>;
  if (!active || id === null) return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <h1 className="text-2xl font-semibold tracking-tight">Aucun cluster connecté</h1>
        <p className="text-muted">Ajoute ton cluster Proxmox pour voir les droits de Kaji.</p>
        <Button onClick={onGoConnections}>Ajouter un cluster</Button>
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
          <h1 className="text-2xl font-semibold tracking-tight">Accès</h1>
          <p className="text-muted">{active.name} · Kaji se connecte en tant que <span className="font-mono text-fg">{active.user}!{active.token_id}</span></p>
        </div>
        <Button variant="ghost" onClick={refetch} disabled={fetching} className="!px-3 !py-1.5">
          <span className={fetching ? "inline-block animate-spin" : ""}>↻</span> Actualiser
        </Button>
      </header>

      <Notice kind="ok">Lecture seule : cette page n'écrit rien dans Proxmox. Les droits se gèrent dans l'interface de Proxmox.</Notice>

      <Block<Feature[]> title="Droits de Kaji" q={features}
        count={(d) => d.length}
        hint="Indicatif : privilèges attendus d'après la documentation de Proxmox (calculés par Proxmox pour ce token, héritage compris). « Disponible » veut dire que les privilèges attendus sont là, pas que chaque opération réussira.">
        {(d) => d.length === 0 ? <Empty>Aucune fonction évaluée.</Empty> : <>
          <p className="text-sm text-muted">{okN} fonction{okN > 1 ? "s" : ""} sur {d.length} disponible{okN > 1 ? "s" : ""}{d.length - okN > 0 ? <> · <span className="text-warn">{d.length - okN} à vérifier</span></> : null}</p>
          <ul className="panel divide-y divide-line/60">
            {d.map((x) => {
              const s = STATUS[x.status];
              return (
                <li key={x.id} className="flex items-start gap-3 px-4 py-3">
                  <span className={`mt-0.5 w-5 shrink-0 text-center font-semibold ${s.cls}`} aria-hidden>{s.icon}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">{x.label}<span className="sr-only"> : {s.label}</span></p>
                    {x.missing.length > 0 && <p className="text-xs text-danger">Manque : {x.missing.map((m) => `${m.privilege} sur ${m.path}`).join(", ")}</p>}
                    {x.status === "unknown" && <p className="text-xs text-warn">Proxmox n'a pas pu confirmer ce droit.</p>}
                  </div>
                  <span className={`shrink-0 text-xs ${s.cls}`}>{s.label}</span>
                </li>
              );
            })}
          </ul>
        </>}
      </Block>

      <Block<AccessUser[]> title="Utilisateurs" q={users} count={(d) => d.length} hint="Seuls les comptes que le token a le droit de voir sont listés.">
        {(d) => d.length === 0 ? <Empty>Aucun utilisateur visible.</Empty> : (
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[30rem] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th scope="col" className={th}>Utilisateur</th><th scope="col" className={th}>Realm</th><th scope="col" className={th}>État</th><th scope="col" className={th}>Expire</th></tr></thead>
              <tbody>
                {d.map((u) => (
                  <tr key={u.userid} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-medium">{u.userid}{u.userid === active.user && <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[0.7rem] font-normal text-muted">Kaji</span>}</td>
                    <td className="px-4 py-2 text-muted">{u.realm_type ?? u.realm ?? "–"}</td>
                    <td className="px-4 py-2"><span className={u.enabled ? "text-ok" : "text-danger"}>{u.enabled ? "Actif" : "Désactivé"}</span></td>
                    <td className="px-4 py-2 text-muted">{when(u.expire)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      <Block<AccessGroup[]> title="Groupes" q={groups} count={(d) => d.length}>
        {(d) => d.length === 0 ? <Empty>Aucun groupe.</Empty> : (
          <div className="panel divide-y divide-line/60">
            {d.map((g) => <div key={g.groupid} className="px-4 py-3 text-sm"><span className="font-medium">{g.groupid}</span>{g.comment && <span className="ml-2 text-muted">{g.comment}</span>}<p className="text-xs text-muted">{g.users.length ? g.users.join(", ") : "aucun membre"}</p></div>)}
          </div>
        )}
      </Block>

      <Block<AccessAcl[]> title="Droits attribués (ACL)" q={acl} count={(d) => d.length}
        hint="Proxmox ne montre que les entrées qui concernent ce token. Une entrée posée sur un chemin précis remplace celle héritée du parent pour le même utilisateur : elle ne s'y ajoute pas.">
        {(d) => d.length === 0 ? <Empty>Aucune entrée visible.</Empty> : (
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm">
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th scope="col" className={th}>Chemin</th><th scope="col" className={th}>Pour</th><th scope="col" className={th}>Rôle</th><th scope="col" className={th}>Hérité</th></tr></thead>
              <tbody>
                {d.map((a) => (
                  <tr key={`${a.path}|${a.ugid}|${a.roleid}`} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-mono text-xs">{a.path}</td>
                    <td className="px-4 py-2">{a.ugid}<span className="ml-2 text-xs text-muted">{a.type ?? ""}</span></td>
                    <td className="px-4 py-2">{a.roleid}</td>
                    <td className="px-4 py-2 text-muted">{a.propagate ? "oui" : "non"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      <Block<AccessRole[]> title="Rôles" q={roles} count={(d) => d.length} hint="Un rôle est un ensemble de privilèges. Clique sur un rôle pour voir lesquels.">
        {(d) => d.length === 0 ? <Empty>Aucun rôle visible.</Empty> : (
          <div className="panel divide-y divide-line/60">
            {d.map((r) => (
              <details key={r.roleid} className="group px-4 py-2.5">
                <summary className="flex cursor-pointer list-none items-center gap-3 text-sm marker:hidden">
                  <span className="text-muted transition group-open:rotate-90" aria-hidden>›</span>
                  <span className="font-medium">{r.roleid}</span>
                  {r.special && <span className="rounded-md border border-line px-1.5 py-0.5 text-[0.7rem] text-muted">intégré</span>}
                  <span className="ml-auto text-xs text-muted">{r.privs.length} privilège{r.privs.length > 1 ? "s" : ""}</span>
                </summary>
                <p className="mt-2 flex flex-wrap gap-1.5 pl-6">
                  {r.privs.length === 0 ? <span className="text-xs text-muted">Aucun privilège.</span>
                    : r.privs.map((p) => <span key={p} className="rounded-full border border-line bg-surface2 px-2 py-0.5 font-mono text-xs text-muted">{p}</span>)}
                </p>
              </details>
            ))}
          </div>
        )}
      </Block>

      <Block<AccessRealm[]> title="Realms" q={realms} count={(d) => d.length}>
        {(d) => d.length === 0 ? <Empty>Aucun realm.</Empty> : (
          <div className="panel divide-y divide-line/60">
            {d.map((r) => <div key={r.realm} className="px-4 py-3 text-sm"><span className="font-medium">{r.realm}</span><span className="ml-2 text-xs text-muted">{r.type ?? ""}{r.comment ? ` · ${r.comment}` : ""}</span></div>)}
          </div>
        )}
      </Block>
    </div>
  );
}
