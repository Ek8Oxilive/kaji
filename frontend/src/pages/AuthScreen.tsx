import { useEffect, useState, type FormEvent } from "react";
import { Logo } from "../components/Logo";
import { AppearanceMenu } from "../components/AppearanceMenu";
import { Button, Field, Notice } from "../components/ui";
import { api } from "../lib/api";
import type { LoginStep } from "../lib/types/totp";

import { tr } from "../lib/i18n";
export function AuthScreen({ setup, tokenRequired = false, onDone }: { setup: boolean; tokenRequired?: boolean; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);      // double authentification : mot de passe accepté, il manque le code
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // SSO (OpenID Connect, `docs/api/sso.md`) : le bouton n'apparaît que si le serveur l'a configuré ; le mot de passe local reste le repli.
  const [sso, setSso] = useState<{ enabled: boolean; label: string | null } | null>(null);
  useEffect(() => { if (!setup) api<{ enabled: boolean; label: string | null }>("/api/auth/oidc/status").then(setSso).catch(() => setSso(null)); }, [setup]);
  // Annuaire LDAP / AD (`docs/api/ldap.md`) : la case n'apparaît que si le serveur l'a configuré ; le mot de passe est vérifié par l'annuaire, jamais gardé par Kaji.
  const [ldap, setLdap] = useState<{ enabled: boolean; label: string | null } | null>(null);
  const [useLdap, setUseLdap] = useState(false);
  useEffect(() => { if (!setup) api<{ enabled: boolean; label: string | null }>("/api/auth/ldap/status").then(setLdap).catch(() => setLdap(null)); }, [setup]);
  const ssoResult = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("sso") : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (setup && password !== confirm) return setError(tr("Les deux mots de passe ne correspondent pas"));
    setBusy(true);
    try {
      if (challenge) {
        await api("/api/auth/login/totp", { method: "POST", body: { challenge, code } });
        onDone();
        return;
      }
      const r = await api<LoginStep>(setup ? "/api/auth/setup" : useLdap && ldap?.enabled ? "/api/auth/ldap/login" : "/api/auth/login", { method: "POST", body: setup && tokenRequired ? { username, password, setup_token: setupToken } : { username, password } });
      if (r?.totp_required && r.challenge) {
        setChallenge(r.challenge); setPassword(""); setCode("");
        return;
      }
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-full place-items-center p-4">
      <div className="absolute right-4 top-4"><AppearanceMenu /></div>
      <form onSubmit={submit} className="panel w-full max-w-sm space-y-5 p-7">
        <Logo />
        <div>
          <h1 className="text-lg font-semibold">{setup ? tr("Bienvenue") : tr("Connexion")}</h1>
          <p className="text-sm text-muted">
            {setup ? tr("Crée le compte administrateur de ton dashboard.") : tr("Accède à ton dashboard Proxmox.")}
          </p>
        </div>
        {challenge ? (
          <>
            <p className="text-sm">{tr("Double authentification : tape le code à 6 chiffres de ton application, ou un code de secours.")}</p>
            <Field label={tr("Code")} inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required minLength={6} maxLength={40} autoFocus />
          </>
        ) : (
          <>
            <Field label={tr("Identifiant")} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required minLength={3} autoFocus />
            <Field label={tr("Mot de passe")} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={setup ? "new-password" : "current-password"} required minLength={setup ? 12 : 1}
              hint={setup ? tr("12 caractères minimum") : undefined} />
          </>
        )}
        {!challenge && !setup && ldap?.enabled && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={useLdap} onChange={(e) => setUseLdap(e.target.checked)} />
            {tr("Compte d'annuaire ({nom})", { nom: ldap.label ?? "LDAP" })}
          </label>
        )}
        {!challenge && setup && tokenRequired && <Field label={tr("Jeton de première configuration")} type="password" value={setupToken} onChange={(e) => setSetupToken(e.target.value)} autoComplete="off" required
          hint={tr("Défini par KAJI_SETUP_TOKEN dans le fichier .env du serveur")} />}
        {!challenge && setup && <Field label={tr("Confirmer le mot de passe")} type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />}
        {ssoResult === "erreur" && !error && <Notice kind="error">{tr("Connexion par le SSO refusée. Utilise ton mot de passe ou demande à un administrateur de relier ton compte.")}</Notice>}
        {ssoResult === "trop" && !error && <Notice kind="error">{tr("Trop de tentatives par le SSO, réessaie plus tard.")}</Notice>}
        {error && <Notice kind="error">{error}</Notice>}
        <Button type="submit" disabled={busy} className="w-full">{busy ? "…" : setup ? tr("Créer le compte") : "Se connecter"}</Button>
        {!setup && !challenge && sso?.enabled && <a href="/api/auth/oidc/login" className="btn-ghost block w-full rounded-xl border border-line px-3 py-2 text-center text-sm hover:bg-surface2">{tr("Se connecter avec {nom}", { nom: sso.label ?? "SSO" })}</a>}
        {challenge && <Button type="button" variant="ghost" className="w-full" onClick={() => { setChallenge(null); setCode(""); setError(null); }}>{tr("Retour")}</Button>}
      </form>
    </main>
  );
}
