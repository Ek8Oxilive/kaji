import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Layout, NAV, NAV_BOTTOM, type Page } from "./components/Layout";
import { api, type AuthStatus } from "./lib/api";
import { guestHash, nodeHash, pageHash, useRoute } from "./lib/route";
import { Acces } from "./pages/Acces";
import { CephPage } from "./pages/Ceph";
import { AuthScreen } from "./pages/AuthScreen";
import { Connections } from "./pages/Connections";
import { Dashboard } from "./pages/Dashboard";
import { Machine } from "./pages/Machine";
import { NodePage } from "./pages/Node";
import { Sauvegardes } from "./pages/Sauvegardes";
import { Cluster } from "./pages/Cluster";
import { Datacenter } from "./pages/Datacenter";
import { HA } from "./pages/HA";
import { Reseau } from "./pages/Reseau";
import { Stockage } from "./pages/Stockage";
import { Taches } from "./pages/Taches";

import { tr } from "./lib/i18n";
const PAGES = [...NAV, ...NAV_BOTTOM].map((n) => n.id) as string[];

export default function App() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const [route, go] = useRoute();

  const refresh = useCallback(() => api<AuthStatus>("/api/auth/status").then(setStatus).catch(() => setFailed(true)), []);
  useEffect(() => { refresh(); }, [refresh]);
  // Compte restreint à un groupe de machines (`docs/api/roles-perimetre.md`) : il n'a que le tableau de bord et les pages de SES machines ; le serveur refuse tout le reste.
  const me = useQuery({ queryKey: ["me"], staleTime: 60_000, enabled: !!status?.authenticated, queryFn: () => api<{ restricted?: boolean }>("/api/auth/me") });
  const restricted = me.data?.restricted === true;

  if (failed) return <div className="grid min-h-full place-items-center p-6 text-center text-muted">{tr("Impossible de joindre le serveur Kaji. Vérifie que le backend tourne.")}</div>;
  if (!status) return <div className="grid min-h-full place-items-center text-muted">{tr("Chargement…")}</div>;
  if (!status.authenticated) return <AuthScreen setup={status.setup_required} tokenRequired={status.setup_token_required} onDone={refresh} />;

  const logout = () => api("/api/auth/logout", { method: "POST" }).finally(refresh);
  // Les pages Machine et Nœud ne sont pas dans la barre latérale : elles gardent « Dashboard » allumé. Adresse inconnue : tableau de bord.
  const page = (!restricted && PAGES.includes(route.page) ? route.page : "dashboard") as Page;
  const goConnections = () => go(pageHash("connections"));
  return (
    <Layout page={page} onNavigate={(p) => go(pageHash(p))} onLogout={logout} restricted={restricted}>
      {route.page === "machine" ? <Machine params={route.params} go={go} onGoConnections={goConnections} />
        : route.page === "node" && !restricted ? <NodePage params={route.params} go={go} onGoConnections={goConnections} />
        : page === "connections" ? <Connections />
        : page === "storage" ? <Stockage onGoConnections={goConnections} />
        : page === "backups" ? <Sauvegardes onGoConnections={goConnections} />
        : page === "access" ? <Acces onGoConnections={goConnections} />
        : page === "ceph" ? <CephPage onGoConnections={goConnections} />
        : page === "tasks" ? <Taches onGoConnections={goConnections} />
        : page === "network" ? <Reseau onGoConnections={goConnections} />
        : page === "ha" ? <HA onGoConnections={goConnections} />
        : page === "cluster" ? <Cluster onGoConnections={goConnections} />
        : page === "datacenter" ? <Datacenter onGoConnections={goConnections} />
        : <Dashboard onGoConnections={goConnections} onOpenGuest={(g) => go(guestHash(g))} onOpenNode={(n) => go(nodeHash(n))} />}
    </Layout>
  );
}
