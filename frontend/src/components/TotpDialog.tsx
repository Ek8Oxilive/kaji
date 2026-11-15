import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import type { TotpSetup, TotpStatus } from "../lib/types/totp";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

type Action = "none" | "recovery" | "disable";
const group = (s: string) => (s.match(/.{1,4}/g) ?? []).join(" ");

/** Double authentification de MA connexion à Kaji : activer (secret à saisir dans une application d'authentification, puis un premier code), codes de secours, désactiver.
 *  Le secret et les codes de secours ne vivent que dans l'état de cette fenêtre : ils disparaissent à sa fermeture ; le serveur ne les renvoie qu'une fois. */
export function TotpDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["totp-status"], queryFn: () => api<TotpStatus>("/api/auth/totp") });
  const [password, setPassword] = useState(""), [code, setCode] = useState("");
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [action, setAction] = useState<Action>("none");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [copied, setCopied] = useState<string | null>(null);

  const status = q.data;
  const enabled = !!status?.enabled;
  const reset = () => { setPassword(""); setCode(""); setAction("none"); setErr(null); };
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["totp-status"] }), qc.invalidateQueries({ queryKey: ["kaji-users"] })]);
  const run = async (what: () => Promise<void>) => {
    setBusy(true); setErr(null);
    try { await what(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const copy = async (what: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(what); } catch { setCopied(null); }
  };

  const start = () => run(async () => { setSetup(await api<TotpSetup>("/api/auth/totp/setup", { method: "POST", body: { password } })); setPassword(""); setCode(""); });
  const confirm = () => run(async () => {
    const r = await api<{ recovery_codes: string[] }>("/api/auth/totp/confirm", { method: "POST", body: { code } });
    setCodes(r.recovery_codes); setSetup(null); setCode(""); await refresh();
  });
  const newCodes = () => run(async () => {
    const r = await api<{ recovery_codes: string[] }>("/api/auth/totp/recovery", { method: "POST", body: { password, code } });
    setCodes(r.recovery_codes); reset(); await refresh();
  });
  const disable = () => run(async () => { await api("/api/auth/totp/disable", { method: "POST", body: { password, code } }); reset(); await refresh(); });

  const codeOk = code.replace(/[\s-]/g, "").length >= 6;
  let submitLabel = tr("Activer la double authentification"), onSubmit: () => void = start, canSubmit = password.length > 0, danger = false;
  if (codes) { submitLabel = tr("J'ai noté mes codes"); onSubmit = () => { setCodes(null); setCopied(null); }; canSubmit = true; }
  else if (setup) { submitLabel = tr("Confirmer l'activation"); onSubmit = confirm; canSubmit = /^[0-9 ]{6,7}$/.test(code); }
  else if (enabled && action === "recovery") { submitLabel = tr("Générer de nouveaux codes de secours"); onSubmit = newCodes; canSubmit = password.length > 0 && codeOk; }
  else if (enabled && action === "disable") { submitLabel = tr("Désactiver la double authentification"); onSubmit = disable; canSubmit = password.length > 0 && codeOk; danger = true; }
  else if (enabled) { submitLabel = tr("Fermer"); onSubmit = onClose; canSubmit = true; }

  return (
    <Modal title={tr("Double authentification")} subtitle={tr("Un code à usage unique, en plus du mot de passe, pour te connecter à Kaji.")}
      onClose={busy ? () => {} : onClose} onSubmit={onSubmit} submitLabel={submitLabel} busy={busy} error={err} canSubmit={canSubmit} danger={danger} wide>
      {q.isLoading && <div className="h-16 animate-pulse rounded bg-surface2" />}
      {q.error && <Notice kind="error">{(q.error as Error).message}</Notice>}

      {codes && (
        <div className="space-y-3">
          <Notice kind="ok">{tr("La double authentification est activée. Note ces codes de secours MAINTENANT : ils ne seront plus affichés.")}</Notice>
          <ul className="grid grid-cols-1 gap-1 rounded-xl border border-line p-3 font-mono text-sm sm:grid-cols-2" aria-label={tr("Codes de secours")}>
            {codes.map((c) => <li key={c}>{c}</li>)}
          </ul>
          <p className="text-sm text-muted">{tr("Chaque code ne sert qu'une fois, si tu perds ton application. Garde-les ailleurs que sur cet ordinateur (gestionnaire de mots de passe, papier).")}</p>
          <Button type="button" variant="ghost" onClick={() => copy("codes", codes.join("\n"))}>{copied === "codes" ? tr("Copié") : tr("Copier les codes")}</Button>
        </div>)}

      {!codes && status && !enabled && !setup && (
        <div className="space-y-3">
          <p className="text-sm text-muted">{tr("Tu auras besoin d'une application d'authentification (Aegis, FreeOTP, Google Authenticator, 1Password, Bitwarden…). Confirme ton mot de passe pour commencer.")}</p>
          <Field label={tr("Mot de passe actuel")} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
        </div>)}

      {!codes && setup && (
        <div className="space-y-3">
          <p className="text-sm">{tr("1. Dans ton application d'authentification, ajoute un compte « saisie manuelle » avec cette clé :")}</p>
          <div className="rounded-xl border border-line p-3">
            <code className="break-all font-mono text-base tracking-wider" aria-label={tr("Clé secrète")}>{group(setup.secret)}</code>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="ghost" onClick={() => copy("secret", setup.secret)}>{copied === "secret" ? tr("Copié") : tr("Copier la clé")}</Button>
            <Button type="button" variant="ghost" onClick={() => copy("uri", setup.uri)}>{copied === "uri" ? tr("Copié") : tr("Copier le lien otpauth")}</Button>
          </div>
          <p className="text-xs text-muted">{tr("Type : basé sur le temps (TOTP), 6 chiffres, 30 secondes, SHA-1. Cette clé n'est montrée qu'ici, une seule fois.")}</p>
          <p className="text-sm">{tr("2. Tape le code à 6 chiffres que l'application affiche :")}</p>
          <Field label={tr("Code à 6 chiffres")} inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={7} autoFocus />
        </div>)}

      {!codes && enabled && (
        <div className="space-y-3">
          <Notice kind="ok">{tr("Activée : un code est demandé à chaque connexion. Codes de secours restants : {n}.", { n: status?.recovery_remaining ?? 0 })}</Notice>
          {action === "none" && (
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="ghost" onClick={() => { reset(); setAction("recovery"); }}>{tr("Nouveaux codes de secours…")}</Button>
              <Button type="button" variant="danger" onClick={() => { reset(); setAction("disable"); }}>{tr("Désactiver…")}</Button>
            </div>)}
          {action !== "none" && (
            <div className="space-y-3">
              <p className="text-sm text-muted">{action === "recovery"
                ? tr("Les anciens codes de secours cesseront de fonctionner. Confirme avec ton mot de passe et un code de l'application.")
                : tr("Ton compte ne sera plus protégé que par le mot de passe. Confirme avec ton mot de passe et un code (de l'application ou de secours).")}</p>
              <Field label={tr("Mot de passe actuel")} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
              <Field label={action === "recovery" ? tr("Code de l'application") : tr("Code de l'application ou code de secours")} autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={40} />
              <Button type="button" variant="ghost" onClick={reset}>{tr("Retour")}</Button>
            </div>)}
        </div>)}
    </Modal>
  );
}
