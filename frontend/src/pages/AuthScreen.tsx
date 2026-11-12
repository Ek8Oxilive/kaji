import { useState, type FormEvent } from "react";
import { Logo } from "../components/Logo";
import { ThemeSwitcher } from "../components/ThemeSwitcher";
import { Button, Field, Notice } from "../components/ui";
import { api } from "../lib/api";

import { tr } from "../lib/i18n";
export function AuthScreen({ setup, tokenRequired = false, onDone }: { setup: boolean; tokenRequired?: boolean; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (setup && password !== confirm) return setError(tr("Les deux mots de passe ne correspondent pas"));
    setBusy(true);
    try {
      await api(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", body: setup && tokenRequired ? { username, password, setup_token: setupToken } : { username, password } });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-full place-items-center p-4">
      <div className="absolute right-4 top-4"><ThemeSwitcher /></div>
      <form onSubmit={submit} className="panel w-full max-w-sm space-y-5 p-7">
        <Logo />
        <div>
          <h1 className="text-lg font-semibold">{setup ? tr("Bienvenue") : tr("Connexion")}</h1>
          <p className="text-sm text-muted">
            {setup ? tr("Crée le compte administrateur de ton dashboard.") : tr("Accède à ton dashboard Proxmox.")}
          </p>
        </div>
        <Field label={tr("Identifiant")} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required minLength={3} autoFocus />
        <Field label={tr("Mot de passe")} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete={setup ? "new-password" : "current-password"} required minLength={setup ? 12 : 1}
          hint={setup ? tr("12 caractères minimum") : undefined} />
        {setup && tokenRequired && <Field label={tr("Jeton de première configuration")} type="password" value={setupToken} onChange={(e) => setSetupToken(e.target.value)} autoComplete="off" required
          hint={tr("Défini par KAJI_SETUP_TOKEN dans le fichier .env du serveur")} />}
        {setup && <Field label={tr("Confirmer le mot de passe")} type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />}
        {error && <Notice kind="error">{error}</Notice>}
        <Button type="submit" disabled={busy} className="w-full">{busy ? "…" : setup ? tr("Créer le compte") : "Se connecter"}</Button>
      </form>
    </main>
  );
}
