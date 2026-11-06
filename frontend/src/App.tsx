import { useCallback, useEffect, useState } from "react";
import { Layout, NAV, NAV_BOTTOM, type Page } from "./components/Layout";
import { api, type AuthStatus } from "./lib/api";
import { guestHash, pageHash, useRoute } from "./lib/route";
import { AuthScreen } from "./pages/AuthScreen";
import { Connections } from "./pages/Connections";
import { Dashboard } from "./pages/Dashboard";
import { Machine } from "./pages/Machine";
import { Stockage } from "./pages/Stockage";

const PAGES = [...NAV, ...NAV_BOTTOM].map((n) => n.id) as string[];

export default function App() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const [route, go] = useRoute();

  const refresh = useCallback(() => api<AuthStatus>("/api/auth/status").then(setStatus).catch(() => setFailed(true)), []);
  useEffect(() => { refresh(); }, [refresh]);

  if (failed) return <div className="grid min-h-full place-items-center p-6 text-center text-muted">Impossible de joindre le serveur Kaji. Vérifie que le backend tourne.</div>;
  if (!status) return <div className="grid min-h-full place-items-center text-muted">Chargement…</div>;
  if (!status.authenticated) return <AuthScreen setup={status.setup_required} onDone={refresh} />;

  const logout = () => api("/api/auth/logout", { method: "POST" }).finally(refresh);
  // La page Machine n'est pas dans la barre latérale : elle garde « Dashboard » allumé. Adresse inconnue : tableau de bord.
  const page = (PAGES.includes(route.page) ? route.page : "dashboard") as Page;
  const goConnections = () => go(pageHash("connections"));
  return (
    <Layout page={page} onNavigate={(p) => go(pageHash(p))} onLogout={logout}>
      {route.page === "machine" ? <Machine params={route.params} go={go} onGoConnections={goConnections} />
        : page === "connections" ? <Connections />
        : page === "storage" ? <Stockage onGoConnections={goConnections} />
        : <Dashboard onGoConnections={goConnections} onOpenGuest={(g) => go(guestHash(g))} />}
    </Layout>
  );
}
