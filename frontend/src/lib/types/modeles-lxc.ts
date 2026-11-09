/** Téléchargement d'un modèle de conteneur du catalogue officiel (`docs/api/modeles-lxc.md`) : seulement un nom du catalogue, jamais d'URL. */
export type TemplateDownloadBody = { storage: string; template: string };
