/** Jeton Proxmox PERSONNEL de l'utilisateur de Kaji (`GET /api/me/proxmox-tokens`, `docs/api/jetons-utilisateur.md`). Le secret n'est jamais renvoyé par le serveur. */
export type UserTokenState = "none" | "ok" | "expiring" | "expired" | "refused";

export type UserTokenConnection = {
  conn_id: number;
  name: string;
  state: UserTokenState;
  pve_user: string | null;
  token_id: string | null;
  expires_at: string | null;
  days_left: number | null;
  privsep: boolean | null;
  /** vrai si Proxmox a confirmé les privilèges séparés et l'expiration en relisant le jeton lui-même */
  verified: boolean | null;
};

export type UserTokens = {
  /** la clé séparée KAJI_TOKEN_KEY est configurée et utilisable */
  enabled: boolean;
  problem: string | null;
  /** KAJI_REQUIRE_USER_TOKEN : sans jeton personnel, aucun accès à Proxmox */
  required: boolean;
  max_days: number;
  connections: UserTokenConnection[];
};

export type UserTokenBody = { pve_user: string; token_id: string; secret: string; expires_at?: string; privsep: boolean };
