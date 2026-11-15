import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { tr } from "../lib/i18n";
import { Modal } from "./Modal";
import { Button, Field, Notice } from "./ui";

type Prov = "ldap" | "oidc";
type View = { provider: Prov; enabled: boolean; source: "database" | "env" | "none"; values: Record<string, string | number | boolean>; secrets: Record<string, boolean>; problems: string[]; updated_by: string | null };
type Test = { ok: boolean; detail: string };

const SECRET: Record<Prov, string> = { ldap: "bind_password", oidc: "client_secret" };
const TEXT: Record<Prov, { key: string; label: () => string; hint?: () => string; placeholder?: string }[]> = {
  ldap: [
    { key: "url", label: () => tr("Adresse de l'annuaire"), hint: () => tr("ldaps://hôte:636 (ou ldap:// avec STARTTLS) : le chiffrement est obligatoire"), placeholder: "ldaps://annuaire.example.com:636" },
    { key: "ca_file", label: () => tr("Autorité de certification (chemin dans le conteneur)"), hint: () => tr("Seulement si l'annuaire a une autorité privée ; le certificat est toujours vérifié") },
    { key: "tls_server_name", label: () => tr("Nom attendu dans le certificat"), hint: () => tr("Si l'adresse ci-dessus est une IP : le nom que porte le certificat de l'annuaire (jamais de joker)"), placeholder: "dc01.example.com" },
    { key: "base_dn", label: () => tr("Où chercher les personnes (base DN)"), placeholder: "dc=example,dc=com" },
    { key: "bind_dn", label: () => tr("Compte de lecture (DN)"), hint: () => tr("Un compte en lecture seule, jamais un administrateur de l'annuaire"), placeholder: "cn=kaji-lecture,dc=example,dc=com" },
    { key: "user_filter", label: () => tr("Filtre de recherche"), hint: () => tr("Contient {username}. Active Directory : (&(objectClass=user)(sAMAccountName={username}))") },
    { key: "username_attr", label: () => tr("Attribut de l'identifiant"), hint: () => tr("uid, ou sAMAccountName pour Active Directory") },
    { key: "groups_attr", label: () => tr("Attribut des groupes"), hint: () => tr("memberOf pour Active Directory (groupes directs seulement)") },
    { key: "admin_group", label: () => tr("Groupe administrateur de Kaji"), hint: () => tr("Nom ou DN complet EXACT du groupe. Ses membres sont administrateurs de Kaji, donc de Proxmox. Vide : aucun rôle n'est modifié"), placeholder: "cn=informatique,ou=groupes,dc=example,dc=com" },
    { key: "operator_group", label: () => tr("Groupe opérateur de Kaji"), hint: () => tr("Même forme. Vide : pas de groupe opérateur") },
    { key: "label", label: () => tr("Texte de la case de connexion") },
  ],
  oidc: [
    { key: "issuer", label: () => tr("Adresse du fournisseur (émetteur)"), placeholder: "https://idp.example.com/realms/entreprise" },
    { key: "client_id", label: () => tr("Identifiant du client") },
    { key: "redirect_uri", label: () => tr("Adresse de retour"), hint: () => tr("Elle se termine par /api/auth/oidc/callback et doit être déclarée à l'identique chez le fournisseur") },
    { key: "scopes", label: () => tr("Périmètres demandés") },
    { key: "username_claim", label: () => tr("Champ qui désigne le compte de Kaji") },
    { key: "groups_claim", label: () => tr("Champ des groupes dans le jeton"), hint: () => tr("Souvent « groups » : ajoute aussi le périmètre « groups » chez le fournisseur") },
    { key: "admin_group", label: () => tr("Groupe administrateur de Kaji"), hint: () => tr("Nom ou DN complet EXACT du groupe. Ses membres sont administrateurs de Kaji, donc de Proxmox. Vide : aucun rôle n'est modifié"), placeholder: "informatique" },
    { key: "operator_group", label: () => tr("Groupe opérateur de Kaji"), hint: () => tr("Même forme. Vide : pas de groupe opérateur") },
    { key: "label", label: () => tr("Texte du bouton de connexion") },
  ],
};

/** Réglages du SSO et de l'annuaire (administrateurs ; le serveur revérifie tout). Le secret est en écriture seule : il n'est jamais renvoyé, seulement « défini ». */
export function AuthSettingsDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["auth-settings"], queryFn: () => api<Record<Prov, View>>("/api/auth-settings") });
  const [prov, setProv] = useState<Prov>("ldap");
  const [form, setForm] = useState<Record<string, string>>({});
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [role, setRole] = useState("viewer");
  const [timeout, setTimeoutS] = useState("5");
  const [secret, setSecret] = useState("");
  const [clear, setClear] = useState(false);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [ok, setOk] = useState<string | null>(null);
  const [test, setTest] = useState<Test | null>(null);
  const [askReset, setAskReset] = useState(false);
  const view = q.data?.[prov];

  useEffect(() => {
    if (!view) return;
    const f: Record<string, string> = {};
    for (const t of TEXT[prov]) f[t.key] = String(view.values[t.key] ?? "");
    if (prov === "oidc" && !f.redirect_uri) f.redirect_uri = `${window.location.origin}/api/auth/oidc/callback`;
    setForm(f);
    setFlags({ auto_create: Boolean(view.values.auto_create), start_tls: Boolean(view.values.start_tls), allow_admin: view.values.allow_admin !== false });
    setRole(String(view.values.default_role ?? "viewer"));
    setTimeoutS(String(view.values.timeout ?? 5));
    setSecret(""); setClear(false); setErr(null); setOk(null); setTest(null); setAskReset(false);
  }, [view, prov]);

  const act = async (what: () => Promise<void>) => {
    setBusy(true); setErr(null); setOk(null);
    try { await what(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const formValues = () => {
    const values: Record<string, string | number | boolean> = { ...form, auto_create: flags.auto_create, allow_admin: flags.allow_admin, default_role: role };
    if (prov === "ldap") { values.start_tls = flags.start_tls; values.timeout = Number(timeout); }
    return values;
  };
  const save = () => act(async () => {
    await api(`/api/auth-settings/${prov}`, { method: "PUT", body: { values: formValues(), secrets: secret ? { [SECRET[prov]]: secret } : {}, clear_secrets: clear ? [SECRET[prov]] : [], confirm: true } });
    await qc.invalidateQueries({ queryKey: ["auth-settings"] });
    setOk(tr("Réglages enregistrés. Le mot de passe local reste toujours possible."));
  });
  // Le test utilise ce qui est SAISI dans la fenêtre (rien n'est enregistré) ; sans mot de passe tapé, le secret déjà enregistré sert.
  const runTest = () => act(async () => { setTest(await api<Test>(`/api/auth-settings/${prov}/test`, { method: "POST", body: { values: formValues(), secrets: secret ? { [SECRET[prov]]: secret } : {} } })); });
  const reset = () => act(async () => {
    await api(`/api/auth-settings/${prov}?confirm=true`, { method: "DELETE" });
    await qc.invalidateQueries({ queryKey: ["auth-settings"] });
    setAskReset(false); setOk(tr("Réglages de l'interface retirés : le fichier .env s'applique de nouveau."));
  });
  const secretSet = Boolean(view?.secrets[SECRET[prov]]);
  const source = view?.source === "database" ? tr("réglages de l'interface") : view?.source === "env" ? tr("fichier .env") : tr("aucune configuration");

  return (
    <Modal title={tr("Authentification")} subtitle={tr("Connexion à Kaji par le SSO ou par un annuaire LDAP / Active Directory. Le mot de passe local reste le repli.")}
      onClose={busy ? () => {} : onClose} onSubmit={save} submitLabel={tr("Enregistrer")} busy={busy} error={err} wide>
      <div className="flex gap-2">
        {(["ldap", "oidc"] as Prov[]).map((p) => (
          <Button key={p} type="button" variant={prov === p ? "primary" : "ghost"} className="!px-3 !py-1" disabled={busy} onClick={() => setProv(p)}>{p === "ldap" ? tr("Annuaire (LDAP / AD)") : tr("SSO (OpenID Connect)")}</Button>
        ))}
      </div>
      {q.isLoading ? <div className="h-24 animate-pulse rounded bg-surface2" /> : q.error ? <Notice kind="error">{(q.error as Error).message}</Notice> : view && (
        <>
          <p className="text-sm text-muted">{view.enabled ? tr("Activé") : tr("Désactivé")} · {tr("Source : {source}", { source })}{view.updated_by ? ` · ${tr("modifié par {name}", { name: view.updated_by })}` : ""}</p>
          {view.problems.length > 0 && <Notice kind="error">{view.problems.join(" ; ")}</Notice>}
          {TEXT[prov].map((t) => <Field key={t.key} label={t.label()} hint={t.hint?.()} placeholder={t.placeholder} value={form[t.key] ?? ""} onChange={(e) => setForm({ ...form, [t.key]: e.target.value })} autoComplete="off" />)}
          <Field label={prov === "ldap" ? tr("Mot de passe du compte de lecture") : tr("Secret du client")} type="password" autoComplete="new-password" value={secret} disabled={clear} onChange={(e) => setSecret(e.target.value)}
            hint={secretSet ? tr("Défini : laisse vide pour le garder. Il n'est jamais réaffiché.") : tr("Non défini. Il est chiffré dans la base et n'est jamais réaffiché.")} />
          {secretSet && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={clear} onChange={(e) => { setClear(e.target.checked); setSecret(""); }} />{tr("Retirer le secret enregistré")}</label>}
          {prov === "ldap" && (
            <>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(flags.start_tls)} onChange={(e) => setFlags({ ...flags, start_tls: e.target.checked })} />{tr("STARTTLS (pour une adresse ldap://)")}</label>
              <Field label={tr("Délai (secondes)")} type="number" min={1} max={30} value={timeout} onChange={(e) => setTimeoutS(e.target.value)} />
            </>
          )}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(flags.auto_create)} onChange={(e) => setFlags({ ...flags, auto_create: e.target.checked })} />{tr("Créer le compte à la première connexion (administrateur seulement si un groupe le donne)")}</label>
          <label className="block text-sm">{tr("Rôle par défaut d'un compte (sans groupe)")}
            <select className="field mt-1" value={role} onChange={(e) => setRole(e.target.value)}><option value="viewer">{tr("Lecture seule")}</option><option value="operator">{tr("Opérateur")}</option></select>
          </label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={flags.allow_admin !== false} onChange={(e) => setFlags({ ...flags, allow_admin: e.target.checked })} />{tr("Autoriser les administrateurs à se connecter par ce fournisseur")}</label>
          <p className="text-xs text-muted">{tr("Le mot de passe local reste possible comme secours si le fournisseur est indisponible. Le rôle suit les groupes à chaque connexion ; le dernier administrateur n'est jamais rétrogradé.")}</p>
          {test && <Notice kind={test.ok ? "ok" : "error"}>{test.detail}</Notice>}
          {ok && <Notice kind="ok">{ok}</Notice>}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="ghost" disabled={busy} onClick={runTest}>{tr("Tester la connexion")}</Button>
            {view.source === "database" && !askReset && <Button type="button" variant="ghost" disabled={busy} onClick={() => setAskReset(true)}>{tr("Retirer mes réglages…")}</Button>}
            {askReset && <Button type="button" variant="danger" disabled={busy} onClick={reset}>{tr("Confirmer : revenir au fichier .env")}</Button>}
          </div>
        </>
      )}
    </Modal>
  );
}
