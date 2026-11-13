import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { AccessGroup, AccessUser } from "../lib/types/acces";
import { tr } from "../lib/i18n";

type Props = {
  connId: number;
  kind: "users" | "groups";
  value: string;
  onChange: (v: string) => void;
  /** Realm retenu pour les utilisateurs (ex. « pve » : les écritures de Kaji ne touchent que ce realm). */
  realm?: string;
  placeholder?: string;
};

/** Liste déroulante des utilisateurs ou des groupes existants (mêmes requêtes que la page « Accès », donc en cache).
 *  Si la liste ne se charge pas (droits, réseau), on retombe sur un champ texte : on ne bloque jamais la saisie. */
export function AccountSelect({ connId, kind, value, onChange, realm, placeholder }: Props) {
  const q = useQuery({
    queryKey: ["access", connId, kind], staleTime: 15_000,
    queryFn: () => api<(AccessUser | AccessGroup)[]>(`/api/connections/${connId}/access/${kind}`),
  });
  const ids = (q.data ?? [])
    .filter((x) => kind === "groups" || !realm || (x as AccessUser).realm === realm)
    .map((x) => (kind === "groups" ? (x as AccessGroup).groupid : (x as AccessUser).userid))
    .sort((a, b) => a.localeCompare(b));
  if (q.isError || (!q.isLoading && ids.length === 0 && !value)) {
    return <input className="field" value={value} onChange={(e) => onChange(e.target.value.trim())} placeholder={placeholder} autoComplete="off" />;
  }
  return (
    <select className="field" value={value} onChange={(e) => onChange(e.target.value)} disabled={q.isLoading}>
      <option value="">{q.isLoading ? tr("Chargement…") : tr("Choisir…")}</option>
      {value && !ids.includes(value) && <option value={value}>{value}</option>}
      {ids.map((id) => <option key={id} value={id}>{id}</option>)}
    </select>
  );
}
