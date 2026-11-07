/** ACME : forme des réponses de `docs/api/systeme-noeud.md`. */
import type { Section } from "./systeme";
export type AcmeAccount = { name: string; directory: string | null; contact: string[]; status: string | null };
export type AcmeInfo = {
  accounts: Section<AcmeAccount[]>;
  directories: Section<{ name: string; url: string }[]>;
  tos: Section<string>;
  plugins: Section<{ id: string; type: string | null }[]>;
  config: Section<{ account: string | null; domains: { slot: number; domain: string; plugin: string | null }[]; digest: string | null }>;
};
