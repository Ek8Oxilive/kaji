import { tr } from "../i18n";
/** Realms d'authentification (`docs/api/realms.md`) : champs par type, dans l'ordre d'affichage. */
export type RealmKind = "ldap" | "ad" | "openid";
export const REALM_KINDS: readonly RealmKind[] = ["ldap", "ad", "openid"];
export const KIND_LABEL: Record<RealmKind, () => string> = { ldap: () => tr("LDAP"), ad: () => tr("Active Directory"), openid: () => tr("OpenID Connect") };

export type FieldKind = "text" | "number" | "select" | "bool" | "secret";
export type FieldDef = { label: () => string; kind: FieldKind; options?: readonly string[]; hint?: () => string };

export const FIELDS: Record<string, FieldDef> = {
  server1: { label: () => tr("Serveur"), kind: "text", hint: () => tr("Nom ou adresse IP ; les adresses locales (127.x, localhost) sont refusées") },
  server2: { label: () => tr("Serveur de secours"), kind: "text" },
  port: { label: () => tr("Port"), kind: "number" },
  mode: { label: () => tr("Mode"), kind: "select", options: ["ldap", "ldaps", "ldap+starttls"] },
  base_dn: { label: () => tr("DN de base"), kind: "text" },
  bind_dn: { label: () => tr("DN de liaison"), kind: "text" },
  password: { label: () => tr("Mot de passe de liaison"), kind: "secret", hint: () => tr("Écriture seule : jamais relu ni affiché. Vide = inchangé.") },
  user_attr: { label: () => tr("Attribut de l'utilisateur"), kind: "text" },
  user_classes: { label: () => tr("Classes d'objets des utilisateurs"), kind: "text" },
  filter: { label: () => tr("Filtre des utilisateurs"), kind: "text" },
  group_dn: { label: () => tr("DN de base des groupes"), kind: "text" },
  group_filter: { label: () => tr("Filtre des groupes"), kind: "text" },
  group_classes: { label: () => tr("Classes d'objets des groupes"), kind: "text" },
  group_name_attr: { label: () => tr("Attribut du nom de groupe"), kind: "text" },
  sync_attributes: { label: () => tr("Attributs de synchronisation"), kind: "text", hint: () => tr("cle=valeur séparés par des virgules") },
  domain: { label: () => tr("Domaine Active Directory"), kind: "text" },
  verify: { label: () => tr("Vérifier le certificat du serveur"), kind: "bool" },
  sslversion: { label: () => tr("Version TLS"), kind: "select", options: ["tlsv1_2", "tlsv1_3"] },
  case_sensitive: { label: () => tr("Noms d'utilisateur sensibles à la casse"), kind: "bool" },
  check_connection: { label: () => tr("Vérifier la connexion à l'enregistrement"), kind: "bool" },
  comment: { label: () => tr("Commentaire"), kind: "text" },
  default: { label: () => tr("Realm par défaut de l'écran de connexion"), kind: "bool" },
  issuer_url: { label: () => tr("URL de l'émetteur"), kind: "text", hint: () => tr("https:// uniquement, sans identifiants") },
  client_id: { label: () => tr("Identifiant client"), kind: "text" },
  client_key: { label: () => tr("Clé client"), kind: "secret", hint: () => tr("Écriture seule : jamais relue ni affichée. Vide = inchangée.") },
  username_claim: { label: () => tr("Revendication du nom d'utilisateur"), kind: "text" },
  scopes: { label: () => tr("Portées"), kind: "text" },
  prompt: { label: () => tr("Invite d'authentification (prompt)"), kind: "text" },
  acr_values: { label: () => tr("Valeurs ACR"), kind: "text" },
  autocreate: { label: () => tr("Créer les utilisateurs à la première connexion"), kind: "bool" },
  groups_autocreate: { label: () => tr("Créer les groupes à la connexion"), kind: "bool" },
  groups_claim: { label: () => tr("Revendication des groupes"), kind: "text" },
  groups_overwrite: { label: () => tr("Écraser les groupes à chaque connexion"), kind: "bool" },
  query_userinfo: { label: () => tr("Interroger le point d'accès userinfo"), kind: "bool" },
};

const LDAP_COMMON = ["server1", "server2", "port", "mode", "bind_dn", "password", "filter", "group_filter", "sync_attributes", "verify", "sslversion", "case_sensitive", "check_connection", "comment", "default"];
export const TYPE_FIELDS: Record<string, string[]> = {
  ldap: ["server1", "server2", "port", "mode", "base_dn", "bind_dn", "password", "user_attr", "user_classes", "filter", "group_dn", "group_filter", "group_classes", "group_name_attr",
    "sync_attributes", "verify", "sslversion", "case_sensitive", "check_connection", "comment", "default"],
  ad: ["server1", "server2", "port", "mode", "domain", ...LDAP_COMMON.slice(4)],
  openid: ["issuer_url", "client_id", "client_key", "username_claim", "scopes", "prompt", "acr_values", "autocreate", "groups_autocreate", "groups_claim", "groups_overwrite", "query_userinfo", "comment", "default"],
  pam: ["comment", "default"], pve: ["comment", "default"],
};
/** Champs obligatoires à la création. */
export const REQUIRED: Record<RealmKind, string[]> = { ldap: ["server1", "base_dn", "user_attr"], ad: ["server1", "domain"], openid: ["issuer_url", "client_id"] };
export const CLEARABLE = new Set(["server2", "port", "mode", "bind_dn", "password", "filter", "group_filter", "sync_attributes", "verify", "sslversion", "case_sensitive", "check_connection", "comment",
  "default", "user_classes", "group_dn", "group_classes", "group_name_attr", "client_key", "username_claim", "scopes", "prompt", "acr_values", "autocreate", "groups_autocreate", "groups_claim",
  "groups_overwrite", "query_userinfo"]);
export const PHRASE = "COUPURE POSSIBLE";

export type RealmDetail = { realm: string; type: string; builtin: boolean; digest: string } & Record<string, string | number | boolean | null>;
export type RealmPreview = { dry_run: true; params?: Record<string, string>; remove?: string[]; locks?: Record<string, unknown> };
