/** Noms lisibles des types de tâches Proxmox. Un type inconnu s'affiche tel quel. */
const LABELS: Record<string, string> = {
  qmstart: "Démarrage de VM", qmstop: "Arrêt forcé de VM", qmshutdown: "Extinction de VM", qmreboot: "Redémarrage de VM", qmreset: "Réinitialisation de VM",
  qmsuspend: "Suspension de VM", qmresume: "Reprise de VM", qmcreate: "Création de VM", qmdestroy: "Suppression de VM", qmclone: "Clonage de VM",
  qmigrate: "Migration de VM", qmsnapshot: "Snapshot de VM", qmdelsnapshot: "Suppression d'un snapshot de VM", qmrollback: "Restauration d'un snapshot de VM",
  qmresize: "Agrandissement de disque de VM", qmmove: "Déplacement de disque de VM", qmrestore: "Restauration de VM", qmtemplate: "Conversion de VM en modèle",
  vzstart: "Démarrage de conteneur", vzstop: "Arrêt forcé de conteneur", vzshutdown: "Extinction de conteneur", vzreboot: "Redémarrage de conteneur",
  vzcreate: "Création de conteneur", vzdestroy: "Suppression de conteneur", vzmigrate: "Migration de conteneur", vzclone: "Clonage de conteneur",
  vzsnapshot: "Snapshot de conteneur", vzdelsnapshot: "Suppression d'un snapshot de conteneur", vzrollback: "Restauration d'un snapshot de conteneur",
  vzresize: "Agrandissement de disque de conteneur", vzrestore: "Restauration de conteneur", vzmove: "Déplacement de volume de conteneur",
  vzdump: "Sauvegarde", imgdel: "Suppression d'un volume", imgcopy: "Copie d'un volume", download: "Téléchargement", aptupdate: "Mise à jour de la liste des paquets",
  startall: "Démarrage de toutes les machines", stopall: "Arrêt de toutes les machines", migrateall: "Migration de toutes les machines",
  vncproxy: "Console (écran)", vncshell: "Shell du nœud", termproxy: "Console (terminal)", spiceproxy: "Console SPICE", srvstart: "Démarrage d'un service",
  srvstop: "Arrêt d'un service", srvrestart: "Redémarrage d'un service", srvreload: "Rechargement d'un service", reloadnetworkconfig: "Application de la configuration réseau",
  hamigrate: "Migration HA", hastart: "Démarrage HA", hastop: "Arrêt HA", pull_file: "Copie de fichier", verifyjob: "Vérification", prunejob: "Élagage",
};

export const taskLabel = (type: string | null) => (type ? LABELS[type] ?? type : "Tâche");

export const STATE_LABEL = { running: "En cours", ok: "Terminée", warning: "Avertissement", error: "Échec" } as const;

export function duration(s: number | null): string {
  if (s == null) return "–";
  if (s < 1) return "< 1 s";
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
