import { useQuery } from "@tanstack/react-query";
import { api, type Connection } from "./api";

const CONN_KEY = "kaji-connection";   // même clé que le tableau de bord : le cluster choisi est partagé
const readConn = () => { try { return Number(localStorage.getItem(CONN_KEY)) || null; } catch { return null; } };

/** Cluster actif : celui choisi sur le tableau de bord, sinon le premier. */
export function useActiveConnection() {
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/api/connections") });
  const stored = readConn();
  const active = conns.data?.find((c) => c.id === stored) ?? conns.data?.[0] ?? null;
  return { conns, active, id: active?.id ?? null };
}
