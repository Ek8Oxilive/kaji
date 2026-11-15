// Périmètre d'un compte de Kaji (`docs/api/roles-perimetre.md`) : les machines (par connexion) qu'il voit et touche.
export type ScopeState = { restricted: boolean; entries: { conn_id: number; vmids: number[] }[] };
