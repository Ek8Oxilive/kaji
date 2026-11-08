/** Types de la session administrateur : forme des réponses de `docs/api/admin-session.md`. Jamais de secret. */

export type AdminSessionState =
  | { active: false }
  | {
      active: true;
      user: string;                 // compte Proxmox du token, ex. admin@pve
      token_id: string;
      seconds_left: number;
      expires_at: string;
      renewals: number;
      can_modify_permissions?: boolean;   // seulement à l'ouverture et pour « whoami »
      modify_paths?: string[];            // chemins où le token peut modifier les droits
    };

export const SESSION_MINUTES = 30;
export const MAX_HOURS = 4;

/** `POST …/access/acl/preview` : ce que ferait l'écriture d'une entrée d'ACL (n'écrit rien). */
export type AclPreview = {
  allowed: boolean;
  reason: string | null;
  entry_exists: boolean;
  would_change: boolean;
  existing_entries: { path: string; type: string | null; ugid: string; roleid: string; propagate: boolean }[];
  role_privs: string[] | null;
  effective_before: string[] | null;
  estimate_after: string[] | null;
  note: string;
};
export type AclChange = { action: "add" | "remove"; path: string; kind: "user" | "group" | "token"; ugid: string; role: string; propagate: boolean };
