import { useState, type ReactNode } from "react";
import { AccountDialog } from "./AccountDialog";
import { Logo } from "./Logo";
import { TaskBar } from "./TaskBar";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { Button } from "./ui";

export type Page = "dashboard" | "connections" | "storage" | "backups" | "access" | "ceph" | "tasks" | "network" | "ha" | "cluster" | "datacenter";
type NavItem = { id: Page; label: string };
// Pages d'usage courant (en haut). Les nouvelles pages s'ajoutent à la fin de cette liste : leur adresse (`#/<id>`) en découle.
export const NAV: NavItem[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "storage", label: "Stockage" },
  { id: "backups", label: "Sauvegardes" },
  { id: "ceph", label: "Ceph" },
  { id: "tasks", label: "Tâches" },
  { id: "network", label: "Réseau" },
  { id: "ha", label: "HA" },
  { id: "cluster", label: "Cluster" },
  { id: "datacenter", label: "Datacenter" },
];
// Réglages rarement utilisés : en bas de la barre, au-dessus de « Compte » et « Déconnexion ».
export const NAV_BOTTOM: NavItem[] = [
  { id: "access", label: "Accès" },
  { id: "connections", label: "Connexions" },
];

export function Layout({ page, onNavigate, onLogout, children }: { page: Page; onNavigate: (p: Page) => void; onLogout: () => void; children: ReactNode }) {
  const [account, setAccount] = useState(false);
  const item = (n: NavItem) => (
    <button key={n.id} onClick={() => onNavigate(n.id)} aria-current={page === n.id ? "page" : undefined}
      className={`rounded-xl px-3 py-2 text-left text-sm transition ${page === n.id ? "bg-accent text-accentfg font-medium" : "text-muted hover:bg-surface2 hover:text-fg"}`}>
      {n.label}
    </button>
  );
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <aside className="panel m-3 flex shrink-0 flex-row items-center gap-4 p-3 md:sticky md:top-3 md:h-[calc(100dvh-1.5rem)] md:w-60 md:flex-col md:items-stretch md:gap-6 md:self-start md:overflow-y-auto md:p-5">
        <Logo />
        <nav className="flex flex-1 gap-1 md:flex-col" aria-label="Navigation principale">
          {NAV.map(item)}
        </nav>
        <div className="flex gap-2 md:flex-col">
          {NAV_BOTTOM.map(item)}
          <Button variant="ghost" onClick={() => setAccount(true)}>Compte</Button>
          <Button variant="ghost" onClick={onLogout}>Déconnexion</Button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex justify-end p-3 md:pr-6"><ThemeSwitcher /></header>
        <main className="flex-1 p-4 pt-2 md:px-6">{children}</main>
        {page !== "tasks" && <TaskBar onOpenTasks={() => onNavigate("tasks")} />}
      </div>
      {account && <AccountDialog onClose={() => setAccount(false)} onLoggedOut={onLogout} />}
    </div>
  );
}
