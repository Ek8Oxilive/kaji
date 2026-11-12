import type { CloudInit } from "../api";

import { tr } from "../i18n";
export const CI_PARTS = ["user", "network", "meta", "vendor"] as const;
export type CiPart = (typeof CI_PARTS)[number];
export const CI_PART_LABEL: Record<CiPart, string> = { user: "Utilisateur (user-data)", get network() { return tr("Réseau (network-config)"); }, get meta() { return tr("Métadonnées (meta-data)"); }, vendor: "Fournisseur (vendor-data)" };

/** Réponse de GET …/cloudinit : `custom` = snippets `cicustom` par partie (volid `stockage:snippets/fichier`, ou null). */
export type CloudInitFull = CloudInit & { custom: Record<CiPart, string | null> };
export type CiSnippet = { volid: string; storage: string; name: string; size: number | null };
export type CiSnippets = { snippets: CiSnippet[]; errors: string[] };
