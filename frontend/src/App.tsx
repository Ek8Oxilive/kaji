import { useCallback, useEffect, useState } from "react";
import { Layout, type Page } from "./components/Layout";
import { api, type AuthStatus } from "./lib/api";
import { AuthScreen } from "./pages/AuthScreen";
import { Connections } from "./pages/Connections";
import { Dashboard } from "./pages/Dashboard";

export default function App() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const [page, setPage] = useState<Page>("dashboard");

  const refresh = useCallback(() => api<AuthStatus>("/api/auth/status").then(setStatus).catch(() => setFailed(true)), []);
  useEffect(() => { refresh(); }, [refresh]);

  if (failed) return <div className="grid min-h-full place-items-center p-6 text-center text-muted">Impossible de joindre le serveur Kaji. Vérifie que le backend tourne.</div>;
  if (!status) return <div className="grid min-h-full place-items-center text-muted">Chargement…</div>;
  if (!status.authenticated) return <AuthScreen setup={status.setup_required} onDone={refresh} />;

  const logout = () => api("/api/auth/logout", { method: "POST" }).finally(refresh);
  return (
    <Layout page={page} onNavigate={setPage} onLogout={logout}>
      {page === "connections" ? <Connections /> : <Dashboard onGoConnections={() => setPage("connections")} />}
    </Layout>
  );
}
