// Double authentification (TOTP) pour se connecter à Kaji (`docs/api/totp-kaji.md`).
export type TotpStatus = { enabled: boolean; pending: boolean; recovery_remaining: number };
export type TotpSetup = { secret: string; uri: string };
/** Réponse de la première étape de connexion quand le compte a le TOTP : un défi, pas une session. */
export type LoginStep = { username?: string; totp_required?: boolean; challenge?: string };
