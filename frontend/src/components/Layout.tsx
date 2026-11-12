import { useEffect, useState, type ReactNode } from "react";
import { AccountDialog } from "./AccountDialog";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { Logo } from "./Logo";
import { TaskBar } from "./TaskBar";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { Button } from "./ui";

import { tr } from "../lib/i18n";
export type Page = "dashboard" | "connections" | "storage" | "backups" | "access" | "ceph" | "tasks" | "network" | "ha" | "cluster" | "datacenter";
type NavItem = { id: Page; label: string };
// Pages d'usage courant (en haut). Les nouvelles pages s'ajoutent à la fin de cette liste : leur adresse (`#/<id>`) en découle.
export const NAV: NavItem[] = [
  { id: "dashboard", get label() { return tr("Dashboard"); } },
  { id: "storage", get label() { return tr("Stockage"); } },
  { id: "backups", get label() { return tr("Sauvegardes"); } },
  { id: "ceph", get label() { return tr("Ceph"); } },
  { id: "tasks", get label() { return tr("Tâches"); } },
  { id: "network", get label() { return tr("Réseau"); } },
  { id: "ha", label: "HA" },
  { id: "cluster", get label() { return tr("Cluster"); } },
  { id: "datacenter", get label() { return tr("Datacenter"); } },
];
// Réglages rarement utilisés : en bas de la barre, au-dessus de « Compte » et « Déconnexion ».
export const NAV_BOTTOM: NavItem[] = [
  { id: "access", get label() { return tr("Accès"); } },
  { id: "connections", get label() { return tr("Connexions"); } },
];

export function Layout({ page, onNavigate, onLogout, children }: { page: Page; onNavigate: (p: Page) => void; onLogout: () => void; children: ReactNode }) {
  const [account, setAccount] = useState(false);
  const [menu, setMenu] = useState(false);                       // tiroir de navigation (petits écrans seulement)
  const go = (p: Page) => { setMenu(false); onNavigate(p); };
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenu(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);
  const item = (n: NavItem) => (
    <button key={n.id} onClick={() => go(n.id)} aria-current={page === n.id ? "page" : undefined}
      className={`rounded-xl px-3 py-2.5 text-left text-sm transition md:py-2 ${page === n.id ? "bg-accent text-accentfg font-medium" : "text-muted hover:bg-surface2 hover:text-fg"}`}>
      {n.label}
    </button>
  );
  const nav = (
    <>
      <nav className="flex flex-1 flex-col gap-1" aria-label={tr("Navigation principale")}>{NAV.map(item)}</nav>
      <div className="flex flex-col gap-2">
        {NAV_BOTTOM.map(item)}
        <Button variant="ghost" onClick={() => { setMenu(false); setAccount(true); }}>{tr("Compte")}</Button>
        <Button variant="ghost" onClick={() => { setMenu(false); onLogout(); }}>{tr("Déconnexion")}</Button>
      </div>
    </>
  );
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      {/* Petit écran : barre du haut (menu, logo, thème) ; la navigation s'ouvre dans un tiroir. */}
      <header className="panel sticky top-2 z-40 m-2 flex items-center gap-2 p-2 md:hidden">
        <button onClick={() => setMenu(true)} aria-label={tr("Ouvrir le menu")} aria-expanded={menu} aria-controls="menu-tiroir"
          className="grid size-10 shrink-0 place-items-center rounded-xl bg-surface2 text-fg hover:brightness-125">
          <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <Logo />
        <div className="ml-auto"><LanguageSwitcher /></div>
      </header>
      {menu && (
        <div className="fixed inset-0 z-50 bg-black/60 md:hidden" onClick={() => setMenu(false)}>
          <aside id="menu-tiroir" role="dialog" aria-modal="true" aria-label={tr("Navigation principale")} onClick={(e) => e.stopPropagation()}
            className="panel rise flex h-full w-[min(18rem,85vw)] flex-col gap-4 overflow-y-auto !rounded-none !rounded-r-2xl p-4">
            <div className="flex items-center justify-between"><Logo />
              <button onClick={() => setMenu(false)} aria-label={tr("Fermer le menu")} autoFocus className="grid size-10 place-items-center rounded-xl text-muted hover:bg-surface2 hover:text-fg">✕</button></div>
            {nav}
            <ThemeSwitcher />
          </aside>
        </div>
      )}
      {/* Écran large : barre latérale fixe. */}
      <aside className="panel m-3 hidden shrink-0 md:sticky md:top-3 md:flex md:h-[calc(100dvh-1.5rem)] md:w-48 md:flex-col md:gap-6 md:self-start md:overflow-y-auto md:p-4 lg:w-60 lg:p-5">
        <Logo />
        {nav}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="hidden items-center justify-end gap-2 p-3 md:flex md:pr-6"><LanguageSwitcher /><ThemeSwitcher /></header>
        <main className="flex-1 p-3 pt-1 sm:p-4 sm:pt-2 md:px-6">{children}</main>
        {page !== "tasks" && <TaskBar onOpenTasks={() => onNavigate("tasks")} />}
      </div>
      {account && <AccountDialog onClose={() => setAccount(false)} onLoggedOut={onLogout} />}
    </div>
  );
}
