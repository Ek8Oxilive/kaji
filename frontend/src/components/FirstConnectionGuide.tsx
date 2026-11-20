import { useState } from "react";
import { Button, Notice } from "./ui";
import { tr } from "../lib/i18n";

const SCRIPT = "https://raw.githubusercontent.com/Ek8Oxilive/kaji/main/tools/proxmox-setup.sh";
const COMMANDS = [`curl -fsSL ${SCRIPT} -o proxmox-setup.sh`, "less proxmox-setup.sh", "sh proxmox-setup.sh"];

function Copyable({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* presse-papiers refusé : le texte reste sélectionnable */ }
  }
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-surface2 px-3 py-2">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap text-xs">{text}</code>
      <Button type="button" variant="ghost" className="!px-2 !py-1 text-xs" onClick={copy}>{done ? tr("Copié") : tr("Copier")}</Button>
    </div>
  );
}

/** Guide de la première connexion à Proxmox : ouvert quand aucun cluster n'est enregistré, replié sinon. Il ne manipule jamais le secret du jeton. */
export function FirstConnectionGuide({ empty, onPrefill }: { empty: boolean; onPrefill: () => void }) {
  return (
    <details open={empty} className="panel p-5">
      <summary className="cursor-pointer text-lg font-semibold">{tr("Première connexion à Proxmox : guide en 3 étapes")}</summary>
      <ol className="mt-4 list-decimal space-y-5 pl-5 text-sm">
        <li className="space-y-2">
          <p>{tr("Sur un nœud Proxmox, dans son shell et en root, télécharge le script, relis-le, puis lance-le. Il crée un utilisateur et un jeton en lecture seule, et affiche les valeurs à saisir ci-dessous.")}</p>
          {COMMANDS.map((c) => <Copyable key={c} text={c} />)}
        </li>
        <li className="space-y-2">
          <p>{tr("Le script affiche l'hôte, l'utilisateur, l'identifiant et le secret du jeton. Pré-remplis le formulaire avec les valeurs habituelles, puis complète le nom, l'hôte et le secret.")}</p>
          <Button type="button" variant="ghost" onClick={onPrefill}>{tr("Pré-remplir : kaji@pve, jeton kaji, port 8006")}</Button>
        </li>
        <li className="space-y-2">
          <p>{tr("Clique sur « Tester la connexion », puis « Enregistrer ». Ensuite, « Épingler le certificat… » : compare l'empreinte affichée avec celle du script avant de confirmer.")}</p>
        </li>
      </ol>
      <div className="mt-4 space-y-2">
        <Notice kind="warn">{tr("Le script n'affiche le secret du jeton qu'une seule fois. Colle-le toi-même dans le formulaire : Kaji ne le ré-affiche jamais et personne d'autre que toi ne doit le voir.")}</Notice>
        <p className="text-xs text-muted">{tr("Sans le script, les trois commandes à la main sont dans docs/installation-lab.md, étape 2.")}</p>
      </div>
    </details>
  );
}
