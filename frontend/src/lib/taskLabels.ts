import { tr } from "./i18n";
/** Noms lisibles des types de tâches Proxmox. Un type inconnu s'affiche tel quel. */
const LABELS: Record<string, string> = {
  get qmstart() { return tr("Démarrage de VM"); }, get qmstop() { return tr("Arrêt forcé de VM"); }, get qmshutdown() { return tr("Extinction de VM"); }, get qmreboot() { return tr("Redémarrage de VM"); }, get qmreset() { return tr("Réinitialisation de VM"); },
  get qmsuspend() { return tr("Suspension de VM"); }, get qmresume() { return tr("Reprise de VM"); }, get qmcreate() { return tr("Création de VM"); }, get qmdestroy() { return tr("Suppression de VM"); }, get qmclone() { return tr("Clonage de VM"); },
  get qmigrate() { return tr("Migration de VM"); }, get qmsnapshot() { return tr("Snapshot de VM"); }, get qmdelsnapshot() { return tr("Suppression d'un snapshot de VM"); }, get qmrollback() { return tr("Restauration d'un snapshot de VM"); },
  get qmresize() { return tr("Agrandissement de disque de VM"); }, get qmmove() { return tr("Déplacement de disque de VM"); }, get qmrestore() { return tr("Restauration de VM"); }, get qmtemplate() { return tr("Conversion de VM en modèle"); },
  get vzstart() { return tr("Démarrage de conteneur"); }, get vzstop() { return tr("Arrêt forcé de conteneur"); }, get vzshutdown() { return tr("Extinction de conteneur"); }, get vzreboot() { return tr("Redémarrage de conteneur"); },
  get vzcreate() { return tr("Création de conteneur"); }, get vzdestroy() { return tr("Suppression de conteneur"); }, get vzmigrate() { return tr("Migration de conteneur"); }, get vzclone() { return tr("Clonage de conteneur"); },
  get vzsnapshot() { return tr("Snapshot de conteneur"); }, get vzdelsnapshot() { return tr("Suppression d'un snapshot de conteneur"); }, get vzrollback() { return tr("Restauration d'un snapshot de conteneur"); },
  get vzresize() { return tr("Agrandissement de disque de conteneur"); }, get vzrestore() { return tr("Restauration de conteneur"); }, get vzmove() { return tr("Déplacement de volume de conteneur"); },
  get vzdump() { return tr("Sauvegarde"); }, get imgdel() { return tr("Suppression d'un volume"); }, get imgcopy() { return tr("Copie d'un volume"); }, get download() { return tr("Téléchargement"); }, get aptupdate() { return tr("Mise à jour de la liste des paquets"); },
  get startall() { return tr("Démarrage de toutes les machines"); }, get stopall() { return tr("Arrêt de toutes les machines"); }, get migrateall() { return tr("Migration de toutes les machines"); },
  get vncproxy() { return tr("Console (écran)"); }, get vncshell() { return tr("Shell du nœud"); }, termproxy: "Console (terminal)", spiceproxy: "Console SPICE", get srvstart() { return tr("Démarrage d'un service"); },
  get srvstop() { return tr("Arrêt d'un service"); }, get srvrestart() { return tr("Redémarrage d'un service"); }, get srvreload() { return tr("Rechargement d'un service"); }, get reloadnetworkconfig() { return tr("Application de la configuration réseau"); },
  hamigrate: "Migration HA", get hastart() { return tr("Démarrage HA"); }, get hastop() { return tr("Arrêt HA"); }, get pull_file() { return tr("Copie de fichier"); }, get verifyjob() { return tr("Vérification"); }, get prunejob() { return tr("Élagage"); },
};

export const taskLabel = (type: string | null) => (type ? LABELS[type] ?? type : tr("Tâche"));

export const STATE_LABEL = { get running() { return tr("En cours"); }, get ok() { return tr("Terminée"); }, get warning() { return tr("Avertissement"); }, get error() { return tr("Échec"); } } as const;

export function duration(s: number | null): string {
  if (s == null) return "–";
  if (s < 1) return "< 1 s";
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
