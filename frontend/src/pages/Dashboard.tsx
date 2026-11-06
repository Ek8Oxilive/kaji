import { Helm } from "../components/Logo";

export function Dashboard() {
  return (
    <div className="mx-auto grid max-w-3xl place-items-center py-24 text-center">
      <div className="panel space-y-4 p-10">
        <Helm className="mx-auto size-10 text-accent" />
        <h1 className="text-2xl font-semibold tracking-tight">Le dashboard arrive</h1>
        <p className="text-muted">Prochaine étape : tes nœuds et tes machines en cartes, avec leurs actions. Commence par ajouter ton cluster dans « Connexions ».</p>
      </div>
    </div>
  );
}
