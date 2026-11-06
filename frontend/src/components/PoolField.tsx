import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, type Pool } from "../lib/api";
import { Field } from "./ui";

const KEY = "kaji-pool";
export const lastPool = () => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } };
export const rememberPool = (v: string) => { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* ignoré */ } };

/**
 * Choix du pool. Liste déroulante si Proxmox en fournit une ; sinon saisie manuelle : avec certains tokens
 * la liste des pools est illisible alors que la création dans un pool fonctionne.
 */
export function PoolField({ connId, value, onChange }: { connId: number; value: string; onChange: (v: string) => void }) {
  const pools = useQuery({ queryKey: ["pools", connId], queryFn: () => api<Pool[]>(`/api/connections/${connId}/pools`), staleTime: 30_000, retry: false });
  useEffect(() => { if (!value) { const l = lastPool(); if (l) onChange(l); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (v: string) => { onChange(v); rememberPool(v); };
  if (pools.data && pools.data.length > 0) {
    return (
      <label className="block space-y-1.5">
        <span className="text-sm text-muted">Pool</span>
        <select className="field" value={value} onChange={(e) => set(e.target.value)}>
          <option value="">Aucun pool</option>
          {pools.data.map((p) => <option key={p.poolid} value={p.poolid}>{p.poolid}{p.comment ? ` · ${p.comment}` : ""}</option>)}
        </select>
      </label>
    );
  }
  return <Field label="Pool (facultatif)" value={value} onChange={(e) => set(e.target.value.trim())} placeholder="kaji-test"
    hint={pools.isLoading ? "Chargement…" : "La liste des pools n'est pas lisible avec ce token : saisis le nom du pool, ou laisse vide pour ne pas en utiliser."} />;
}
