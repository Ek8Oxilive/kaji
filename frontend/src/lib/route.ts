import { useCallback, useEffect, useState } from "react";

/**
 * Routage par `#` (aucune dépendance, aucune configuration du serveur) : chaque page a une adresse, le bouton retour
 * du navigateur marche, et le lien d'une machine peut être copié.
 *
 *   #/                                  tableau de bord
 *   #/storage                           une page de la barre latérale : `#/<id de la page>`
 *   #/machine/enzo/qemu/100/snapshots   page d'une machine (nœud / type / identifiant / onglet)
 *
 * Tout ce qui vient de l'adresse est une saisie non fiable : on ne garde que des segments simples, et la page Machine
 * ne s'en sert que pour retrouver une machine dans la liste du cluster (jamais directement dans un appel d'API).
 */
export type Route = { page: string; params: string[] };

const SEGMENT = /^[A-Za-z0-9._-]{1,64}$/;
const HOME: Route = { page: "dashboard", params: [] };

export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts.length === 0 || parts.length > 6 || parts.some((p) => !SEGMENT.test(p))) return HOME;
  return { page: parts[0], params: parts.slice(1) };
}

export const pageHash = (page: string) => (page === "dashboard" ? "#/" : `#/${page}`);

export type GuestRef = { node: string; type: "qemu" | "lxc"; vmid: number };
export const guestHash = (g: GuestRef, tab?: string) => `#/machine/${g.node}/${g.type}/${g.vmid}${tab ? `/${tab}` : ""}`;

export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  /** `replace` : remplace l'entrée courante de l'historique (changement d'onglet, redirection) au lieu d'en ajouter une. */
  const go = useCallback((hash: string, opts?: { replace?: boolean }) => {
    if (opts?.replace) {
      window.history.replaceState(null, "", hash);
      setRoute(parseHash(hash));
    } else {
      window.location.hash = hash;
    }
  }, []);
  return [route, go] as const;
}
