import { useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./Modal";
import { useSubmit } from "./HardwareDialogs";
import { useToast } from "./Toast";
import { Button, Field, Notice } from "./ui";

/** Compte administrateur : changer le mot de passe, couper toutes les sessions. Aucun mot de passe n'est conservé ailleurs que dans l'état du formulaire. */
export function AccountDialog({ onClose, onLoggedOut }: { onClose: () => void; onLoggedOut: () => void }) {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [askAll, setAskAll] = useState(false);
  const [allError, setAllError] = useState<string | null>(null);
  const [allBusy, setAllBusy] = useState(false);
  const { busy, error, run } = useSubmit(onClose);

  const tooShort = next.length > 0 && next.length < 12;
  const mismatch = confirm.length > 0 && next !== confirm;
  const same = next.length > 0 && next === current;
  const ok = current.length > 0 && next.length >= 12 && next === confirm && next !== current;

  const change = () => run(async () => {
    await api("/api/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
    setCurrent(""); setNext(""); setConfirm("");
    toast("ok", "Mot de passe changé : les autres sessions ont été déconnectées");
  });

  const logoutAll = async () => {
    setAllBusy(true); setAllError(null);
    try { await api("/api/auth/logout-all", { method: "POST" }); onClose(); onLoggedOut(); }
    catch (e) { setAllError((e as Error).message); setAllBusy(false); }
  };

  return (
    <Modal title="Compte" subtitle="Administrateur du dashboard" onClose={onClose} busy={busy} error={error} canSubmit={ok} submitLabel="Changer le mot de passe" onSubmit={change}>
      <Field label="Mot de passe actuel" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" autoFocus />
      <Field label="Nouveau mot de passe" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" hint="12 caractères minimum" />
      <Field label="Confirmer le nouveau mot de passe" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
      {tooShort && <p className="text-sm text-danger">Au moins 12 caractères.</p>}
      {same && <p className="text-sm text-danger">Le nouveau mot de passe doit différer de l'actuel.</p>}
      {mismatch && <p className="text-sm text-danger">Les deux mots de passe ne correspondent pas.</p>}

      <div className="space-y-2 border-t border-line pt-4">
        <h3 className="text-sm font-semibold">Sessions</h3>
        <p className="text-sm text-muted">Déconnecte tous les navigateurs et appareils connectés, y compris celui-ci. Utile si tu penses qu'un accès a fuité.</p>
        {allError && <Notice kind="error">{allError}</Notice>}
        {askAll
          ? <div className="flex gap-2"><Button type="button" variant="danger" disabled={allBusy} onClick={logoutAll}>{allBusy ? "…" : "Confirmer : tout déconnecter"}</Button><Button type="button" variant="ghost" onClick={() => setAskAll(false)}>Annuler</Button></div>
          : <Button type="button" variant="ghost" onClick={() => setAskAll(true)}>Déconnecter toutes les sessions</Button>}
      </div>
    </Modal>
  );
}
