import { tr } from "../i18n";
/** Types de l'ajout / modification / suppression d'un stockage : forme des réponses de `docs/api/stockage-config.md`. */

export type StorageKind = "dir" | "nfs" | "cifs" | "lvm" | "lvmthin" | "zfspool" | "iscsi" | "cephfs" | "rbd" | "pbs";

/** `GET /api/connections/{id}/storage-config` : une entrée par stockage du datacenter (jamais de secret). */
export type StorageConfig = {
  storage: string;
  type: string | null;
  managed: boolean;                 // false : type que Kaji ne modifie pas encore (ex. pbs)
  digest?: string | null;
  content?: string[];
  nodes?: string[];
  disable?: boolean;
  secrets_set?: string[];
  [champ: string]: unknown;
};

export type FieldKind = "text" | "password" | "bool" | "list" | "select" | "number";
export type FieldDef = { key: string; label: string; kind: FieldKind; create?: boolean; required?: boolean; hint?: string; options?: string[] };

const CONTENT_ALL = ["images", "rootdir", "iso", "vztmpl", "backup", "snippets", "import"];

/** Même table que `backend/app/storageconf.py` (le serveur reste seul juge : il refuse tout champ hors liste). */
export const KINDS: Record<StorageKind, { label: string; contents: string[]; fields: FieldDef[] }> = {
  dir: { get label() { return tr("Répertoire"); }, contents: CONTENT_ALL, fields: [
    { key: "path", get label() { return tr("Chemin"); }, kind: "text", create: true, required: true, hint: "Ex. /mnt/sauvegardes (chemin absolu)" },
    { key: "create_base_path", get label() { return tr("Créer le dossier s'il n'existe pas"); }, kind: "bool", create: true },
    { key: "shared", get label() { return tr("Partagé entre les nœuds (déjà monté partout)"); }, kind: "bool" },
  ] },
  nfs: { label: "NFS", contents: CONTENT_ALL, fields: [
    { key: "server", get label() { return tr("Serveur"); }, kind: "text", create: true, required: true, get hint() { return tr("Adresse IP ou nom"); } },
    { key: "export", get label() { return tr("Export"); }, kind: "text", create: true, required: true, hint: "Ex. /srv/nfs" },
    { key: "options", get label() { return tr("Options de montage"); }, kind: "text", hint: "Ex. vers=4.2" },
  ] },
  cifs: { label: "SMB / CIFS", contents: CONTENT_ALL, fields: [
    { key: "server", get label() { return tr("Serveur"); }, kind: "text", create: true, required: true },
    { key: "share", get label() { return tr("Partage"); }, kind: "text", create: true, required: true },
    { key: "username", get label() { return tr("Utilisateur"); }, kind: "text" },
    { key: "password", get label() { return tr("Mot de passe"); }, kind: "password", get hint() { return tr("Jamais réaffiché. Laisser vide pour ne pas le changer."); } },
    { key: "domain", get label() { return tr("Domaine"); }, kind: "text" },
    { key: "smbversion", label: "Version SMB", kind: "select", options: ["default", "2.0", "2.1", "3", "3.0", "3.11"] },
    { key: "subdir", label: "Sous-dossier", kind: "text" },
    { key: "options", get label() { return tr("Options de montage"); }, kind: "text" },
  ] },
  lvm: { label: "LVM", contents: ["images", "rootdir"], fields: [
    { key: "vgname", get label() { return tr("Groupe de volumes"); }, kind: "text", create: true, required: true },
    { key: "shared", get label() { return tr("Partagé entre les nœuds"); }, kind: "bool" },
    { key: "saferemove", get label() { return tr("Effacer les données à la suppression d'un volume"); }, kind: "bool" },
  ] },
  lvmthin: { label: "LVM-thin", contents: ["images", "rootdir"], fields: [
    { key: "vgname", get label() { return tr("Groupe de volumes"); }, kind: "text", create: true, required: true },
    { key: "thinpool", get label() { return tr("Pool thin"); }, kind: "text", create: true, required: true },
  ] },
  zfspool: { label: "ZFS", contents: ["images", "rootdir"], fields: [
    { key: "pool", label: "Pool ZFS", kind: "text", create: true, required: true, get hint() { return tr("Ex. tank ou tank/vm"); } },
    { key: "blocksize", get label() { return tr("Taille de bloc"); }, kind: "select", options: ["4k", "8k", "16k", "32k", "64k", "128k"] },
    { key: "sparse", label: "Volumes fins (sparse)", kind: "bool" },
    { key: "mountpoint", get label() { return tr("Point de montage"); }, kind: "text" },
  ] },
  iscsi: { label: "iSCSI", contents: ["images"], fields: [
    { key: "portal", get label() { return tr("Portail"); }, kind: "text", create: true, required: true, get hint() { return tr("IP ou nom, port facultatif"); } },
    { key: "target", label: "Cible (IQN)", kind: "text", create: true, required: true },
  ] },
  cephfs: { label: "CephFS", contents: ["iso", "vztmpl", "backup", "snippets"], fields: [
    { key: "monhost", get label() { return tr("Moniteurs"); }, kind: "list", required: true, get hint() { return tr("Séparés par des virgules"); } },
    { key: "username", get label() { return tr("Utilisateur"); }, kind: "text" },
    { key: "fs_name", get label() { return tr("Système de fichiers"); }, kind: "text" },
    { key: "subdir", label: "Sous-dossier", kind: "text" },
    { key: "fuse", get label() { return tr("Monter avec FUSE"); }, kind: "bool" },
    { key: "keyring", label: "Keyring (cluster externe)", kind: "password", get hint() { return tr("Jamais réaffiché."); } },
  ] },
  pbs: { label: "Proxmox Backup Server", contents: ["backup"], fields: [
    { key: "server", get label() { return tr("Serveur"); }, kind: "text", create: true, required: true, get hint() { return tr("Adresse IP ou nom du PBS"); } },
    { key: "port", get label() { return tr("Port"); }, kind: "number", get hint() { return tr("8007 par défaut"); } },
    { key: "datastore", get label() { return tr("Datastore"); }, kind: "text", create: true, required: true },
    { key: "username", get label() { return tr("Utilisateur ou jeton d'API"); }, kind: "text", required: true, get hint() { return tr("Ex. kaji@pbs ou kaji@pbs!jeton"); } },
    { key: "password", get label() { return tr("Mot de passe ou secret du jeton"); }, kind: "password", required: true, get hint() { return tr("Jamais réaffiché. Laisser vide pour ne pas le changer."); } },
    { key: "fingerprint", get label() { return tr("Empreinte du certificat (SHA-256)"); }, kind: "text", get hint() { return tr("Obligatoire si le certificat du PBS est auto-signé"); } },
    { key: "namespace", get label() { return tr("Espace de noms"); }, kind: "text", get hint() { return tr("Ex. prod ou prod/vm"); } },
  ] },
  rbd: { label: "Ceph RBD", contents: ["images", "rootdir"], fields: [
    { key: "pool", get label() { return tr("Pool"); }, kind: "text", create: true, required: true },
    { key: "monhost", get label() { return tr("Moniteurs"); }, kind: "list", required: true, get hint() { return tr("Séparés par des virgules"); } },
    { key: "username", get label() { return tr("Utilisateur"); }, kind: "text" },
    { key: "krbd", get label() { return tr("Utiliser krbd"); }, kind: "bool" },
    { key: "namespace", get label() { return tr("Espace de noms"); }, kind: "text" },
    { key: "keyring", label: "Keyring (cluster externe)", kind: "password", get hint() { return tr("Jamais réaffiché."); } },
  ] },
};

export const CONTENT_LABEL: Record<string, string> = {
  get images() { return tr("Disques de VM"); }, get rootdir() { return tr("Disques de conteneur"); }, iso: "ISO", get vztmpl() { return tr("Modèles"); }, get backup() { return tr("Sauvegardes"); }, get snippets() { return tr("Snippets"); }, get import() { return tr("Import"); },
};
