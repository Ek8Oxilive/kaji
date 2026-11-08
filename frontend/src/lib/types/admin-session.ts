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
