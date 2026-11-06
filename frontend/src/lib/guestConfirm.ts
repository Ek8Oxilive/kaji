import type { GuestAction } from "./api";

/** Textes des confirmations d'action sur une machine (tableau de bord et page Machine). `start` n'en demande pas. */
export const CONFIRM: Record<Exclude<GuestAction, "start">, { title: string; verb: string; text: string; danger?: boolean }> = {
  reboot: { title: "Redémarrer", verb: "Redémarrer", text: "La machine va redémarrer proprement. Ses services seront indisponibles quelques instants." },
  shutdown: { title: "Éteindre", verb: "Éteindre", text: "Arrêt propre du système invité. Il faudra la redémarrer pour la remettre en service." },
  stop: { title: "Forcer l'arrêt", verb: "Forcer l'arrêt", danger: true, text: "Coupure brutale, comme débrancher l'alimentation. Risque de perte de données non enregistrées." },
};
