import { ApiError } from "./api";

/**
 * Le serveur décide quand une action de job demande une confirmation (réduction de rétention, mode « Arrêt », changement
 * de stockage ou de sélection…). Il répond 400 « Confirmation requise (…) : raison ; raison ». On en tire les raisons pour
 * les montrer, puis on renvoie la même demande avec `confirm: true`. L'interface ne recopie donc aucune de ces règles.
 * Renvoie `null` si l'erreur n'est pas une demande de confirmation.
 */
export function confirmReasons(e: unknown): string[] | null {
  if (!(e instanceof ApiError) || e.status !== 400) return null;
  const m = e.message.match(/Confirmation requise \([^)]*\) : (.+)$/);
  return m ? m[1].split(" ; ").map((r) => r.trim()).filter(Boolean) : null;
}
