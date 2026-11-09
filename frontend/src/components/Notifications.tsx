import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { NOTIF_LABEL, NOTIF_TYPES, ORIGIN_LABEL, endpointSummary, matcherSummary, type NotifEndpoint, type NotifEndpoints, type NotifMatcher } from "../lib/types/notifications";
import { Notice } from "./ui";

const Th = ({ children }: { children?: string }) => <th scope="col" className="px-4 py-2 font-normal">{children}</th>;

/** Datacenter → Notifications : les CIBLES (sendmail, SMTP, Gotify, webhook) et les RÈGLES qui décident quoi envoyer où. Lecture seule : aucun secret n'est renvoyé par le serveur. */
export function Notifications({ connId }: { connId: number }) {
  const ep = useQuery({ queryKey: ["notif-endpoints", connId], queryFn: () => api<NotifEndpoints>(`/api/connections/${connId}/notifications/endpoints`), retry: false });
  const mt = useQuery({ queryKey: ["notif-matchers", connId], queryFn: () => api<NotifMatcher[]>(`/api/connections/${connId}/notifications/matchers`), retry: false });
  const rows: NotifEndpoint[] = ep.data ? NOTIF_TYPES.flatMap((t) => ep.data.endpoints[t] ?? []).sort((a, b) => a.name.localeCompare(b.name)) : [];
  const badge = (o: string | null) => (o ? <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[0.65rem] text-muted">{ORIGIN_LABEL[o] ?? o}</span> : null);
  return (
    <section className="space-y-5" aria-label="Notifications">
      <div>
        <h2 className="text-lg font-semibold">Notifications</h2>
        <p className="text-sm text-muted">Les cibles reçoivent les messages (échec d'une sauvegarde, mises à jour disponibles…) ; les règles décident lesquels partent vers quelle cible. Lecture seule : aucun mot de passe ni jeton n'est affiché.</p>
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-medium">Cibles</h3>
        {ep.error ? <Notice kind="error">{(ep.error as Error).message}</Notice> : ep.isLoading ? <div className="panel h-16 animate-pulse" /> : (
          <>
            {(ep.data?.unavailable.length ?? 0) > 0 && <Notice kind="error">Types illisibles (droits ou version de Proxmox) : {ep.data!.unavailable.map((t) => NOTIF_LABEL[t]).join(", ")}.</Notice>}
            {rows.length === 0 ? <p className="text-sm text-muted">Aucune cible de notification.</p> : (
              <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[34rem] text-sm">
                <thead><tr className="border-b border-line text-left text-xs text-muted"><Th>Nom</Th><Th>Type</Th><Th>Destination</Th><Th>État</Th></tr></thead>
                <tbody>{rows.map((e) => (
                  <tr key={`${e.type}:${e.name}`} className={`border-b border-line/60 last:border-0 ${e.disable ? "opacity-60" : ""}`}>
                    <td className="px-4 py-2 font-mono">{e.name}{badge(e.origin)}{e.comment && <span className="block font-sans text-xs text-muted">{e.comment}</span>}</td>
                    <td className="px-4 py-2 text-muted">{NOTIF_LABEL[e.type]}</td>
                    <td className="break-all px-4 py-2 text-muted">{endpointSummary(e)}</td>
                    <td className="px-4 py-2 text-muted">{e.disable ? "désactivée" : "active"}</td>
                  </tr>))}</tbody></table></div>)}
          </>)}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-medium">Règles</h3>
        {mt.error ? <Notice kind="error">{(mt.error as Error).message}</Notice> : mt.isLoading ? <div className="panel h-16 animate-pulse" /> : (mt.data ?? []).length === 0 ? <p className="text-sm text-muted">Aucune règle : rien n'est envoyé.</p> : (
          <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[34rem] text-sm">
            <thead><tr className="border-b border-line text-left text-xs text-muted"><Th>Nom</Th><Th>Quand</Th><Th>Envoyer vers</Th><Th>État</Th></tr></thead>
            <tbody>{(mt.data ?? []).map((m) => (
              <tr key={m.name} className={`border-b border-line/60 last:border-0 ${m.disable ? "opacity-60" : ""}`}>
                <td className="px-4 py-2 font-mono">{m.name}{badge(m.origin)}{m.comment && <span className="block font-sans text-xs text-muted">{m.comment}</span>}</td>
                <td className="px-4 py-2 text-muted">{matcherSummary(m)}</td>
                <td className="px-4 py-2 font-mono text-muted">{m.target.length ? m.target.join(", ") : "—"}</td>
                <td className="px-4 py-2 text-muted">{m.disable ? "désactivée" : "active"}</td>
              </tr>))}</tbody></table></div>)}
      </div>
    </section>
  );
}
