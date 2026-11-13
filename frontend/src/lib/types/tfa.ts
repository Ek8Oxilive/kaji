/** Double authentification (`docs/api/tfa.md`). */
export type TfaEntry = { id: string; type: "totp" | "u2f" | "webauthn" | "recovery" | "yubico"; description: string | null; created: number | null; enabled: boolean };
export type TfaUser = { userid: string; entries: TfaEntry[]; locked: boolean };
export type TotpSetup = { secret: string; uri: string };
export const TFA_PHRASE = "COUPURE POSSIBLE";
export const USERID = /^[A-Za-z0-9._-]{1,64}@[A-Za-z][A-Za-z0-9._-]{1,31}$/;
export const ENTRY_ID = /^[A-Za-z0-9._-]{1,64}$/;
