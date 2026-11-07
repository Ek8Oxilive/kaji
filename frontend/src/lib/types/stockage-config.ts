/** Types de l'ajout / modification / suppression d'un stockage : forme des réponses de `docs/api/stockage-config.md`. */

export type StorageKind = "dir" | "nfs" | "cifs" | "lvm" | "lvmthin" | "zfspool" | "iscsi" | "cephfs" | "rbd";

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

export type FieldKind = "text" | "password" | "bool" | "list" | "select";
export type FieldDef = { key: string; label: string; kind: FieldKind; create?: boolean; required?: boolean; hint?: string; options?: string[] };

const CONTENT_ALL = ["images", "rootdir", "iso", "vztmpl", "backup", "snippets", "import"];

/** Même table que `backend/app/storageconf.py` (le serveur reste seul juge : il refuse tout champ hors liste). */
export const KINDS: Record<StorageKind, { label: string; contents: string[]; fields: FieldDef[] }> = {
  dir: { label: "Répertoire", contents: CONTENT_ALL, fields: [
    { key: "path", label: "Chemin", kind: "text", create: true, required: true, hint: "Ex. /mnt/sauvegardes (chemin absolu)" },
    { key: "create_base_path", label: "Créer le dossier s'il n'existe pas", kind: "bool", create: true },
    { key: "shared", label: "Partagé entre les nœuds (déjà monté partout)", kind: "bool" },
  ] },
  nfs: { label: "NFS", contents: CONTENT_ALL, fields: [
    { key: "server", label: "Serveur", kind: "text", create: true, required: true, hint: "Adresse IP ou nom" },
    { key: "export", label: "Export", kind: "text", create: true, required: true, hint: "Ex. /srv/nfs" },
    { key: "options", label: "Options de montage", kind: "text", hint: "Ex. vers=4.2" },
  ] },
  cifs: { label: "SMB / CIFS", contents: CONTENT_ALL, fields: [
    { key: "server", label: "Serveur", kind: "text", create: true, required: true },
    { key: "share", label: "Partage", kind: "text", create: true, required: true },
    { key: "username", label: "Utilisateur", kind: "text" },
    { key: "password", label: "Mot de passe", kind: "password", hint: "Jamais réaffiché. Laisser vide pour ne pas le changer." },
    { key: "domain", label: "Domaine", kind: "text" },
    { key: "smbversion", label: "Version SMB", kind: "select", options: ["default", "2.0", "2.1", "3", "3.0", "3.11"] },
    { key: "subdir", label: "Sous-dossier", kind: "text" },
    { key: "options", label: "Options de montage", kind: "text" },
  ] },
  lvm: { label: "LVM", contents: ["images", "rootdir"], fields: [
    { key: "vgname", label: "Groupe de volumes", kind: "text", create: true, required: true },
    { key: "shared", label: "Partagé entre les nœuds", kind: "bool" },
    { key: "saferemove", label: "Effacer les données à la suppression d'un volume", kind: "bool" },
  ] },
  lvmthin: { label: "LVM-thin", contents: ["images", "rootdir"], fields: [
    { key: "vgname", label: "Groupe de volumes", kind: "text", create: true, required: true },
    { key: "thinpool", label: "Pool thin", kind: "text", create: true, required: true },
  ] },
  zfspool: { label: "ZFS", contents: ["images", "rootdir"], fields: [
    { key: "pool", label: "Pool ZFS", kind: "text", create: true, required: true, hint: "Ex. tank ou tank/vm" },
    { key: "blocksize", label: "Taille de bloc", kind: "select", options: ["4k", "8k", "16k", "32k", "64k", "128k"] },
    { key: "sparse", label: "Volumes fins (sparse)", kind: "bool" },
    { key: "mountpoint", label: "Point de montage", kind: "text" },
  ] },
  iscsi: { label: "iSCSI", contents: ["images"], fields: [
    { key: "portal", label: "Portail", kind: "text", create: true, required: true, hint: "IP ou nom, port facultatif" },
    { key: "target", label: "Cible (IQN)", kind: "text", create: true, required: true },
  ] },
  cephfs: { label: "CephFS", contents: ["iso", "vztmpl", "backup", "snippets"], fields: [
    { key: "monhost", label: "Moniteurs", kind: "list", required: true, hint: "Séparés par des virgules" },
    { key: "username", label: "Utilisateur", kind: "text" },
    { key: "fs_name", label: "Système de fichiers", kind: "text" },
    { key: "subdir", label: "Sous-dossier", kind: "text" },
    { key: "fuse", label: "Monter avec FUSE", kind: "bool" },
    { key: "keyring", label: "Keyring (cluster externe)", kind: "password", hint: "Jamais réaffiché." },
  ] },
  rbd: { label: "Ceph RBD", contents: ["images", "rootdir"], fields: [
    { key: "pool", label: "Pool", kind: "text", create: true, required: true },
    { key: "monhost", label: "Moniteurs", kind: "list", required: true, hint: "Séparés par des virgules" },
    { key: "username", label: "Utilisateur", kind: "text" },
    { key: "krbd", label: "Utiliser krbd", kind: "bool" },
    { key: "namespace", label: "Espace de noms", kind: "text" },
    { key: "keyring", label: "Keyring (cluster externe)", kind: "password", hint: "Jamais réaffiché." },
  ] },
};

export const CONTENT_LABEL: Record<string, string> = {
  images: "Disques de VM", rootdir: "Disques de conteneur", iso: "ISO", vztmpl: "Modèles", backup: "Sauvegardes", snippets: "Snippets", import: "Import",
};
