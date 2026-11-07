/** Types de la page « Accès » : forme des réponses de `docs/api/acces.md` (lecture seule). */

export type FeatureStatus = "ok" | "missing" | "unknown";
export type Feature = { id: string; label: string; status: FeatureStatus; missing: { path: string; privilege: string }[] };

export type AccessUser = { userid: string; realm: string | null; realm_type: string | null; enabled: boolean; expire: number | null };
export type AccessGroup = { groupid: string; comment: string | null; users: string[] };
export type AccessRole = { roleid: string; special: boolean; privs: string[] };
export type AccessAcl = { path: string; type: string | null; ugid: string; roleid: string; propagate: boolean };
export type AccessRealm = { realm: string; type: string | null; comment: string | null };

/** `GET …/access/fixes` : commandes `pveum` à copier (Kaji n'exécute rien). */
export type Fix = { id: string; label: string; commands: string[]; error: string | null };
