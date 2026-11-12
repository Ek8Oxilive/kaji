import type { GuestAction } from "./api";

import { tr } from "./i18n";
/** Textes des confirmations d'action sur une machine (tableau de bord et page Machine). `start` n'en demande pas. */
export const CONFIRM: Record<Exclude<GuestAction, "start">, { title: string; verb: string; text: string; danger?: boolean }> = {
  reboot: { get title() { return tr("Redémarrer"); }, get verb() { return tr("Redémarrer"); }, get text() { return tr("La machine va redémarrer proprement. Ses services seront indisponibles quelques instants."); } },
  shutdown: { get title() { return tr("Éteindre"); }, get verb() { return tr("Éteindre"); }, get text() { return tr("Arrêt propre du système invité. Il faudra la redémarrer pour la remettre en service."); } },
  stop: { get title() { return tr("Forcer l'arrêt"); }, get verb() { return tr("Forcer l'arrêt"); }, danger: true, get text() { return tr("Coupure brutale, comme débrancher l'alimentation. Risque de perte de données non enregistrées."); } },
};
