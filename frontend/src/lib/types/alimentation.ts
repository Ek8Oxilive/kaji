/** Redémarrer / éteindre un nœud : forme des réponses de `docs/api/systeme-noeud.md`. */
export type PowerCheck = {
  node: string; known: boolean; online: boolean;
  running_guests: { vmid: number; name: string | null; type: "qemu" | "lxc" }[];
  protected_running: number[]; quorum_loss: boolean; nodes_online_after: number | null;
};
export type PowerAction = "reboot" | "shutdown";
