/** Moniteur QEMU en lecture seule (`docs/api/moniteur-qemu.md`) : seules les commandes « info … » de la liste blanche du serveur. */
export type MonitorCommand = { command: string; label: string };
export type MonitorCommands = { commands: MonitorCommand[] };
export type MonitorResult = { command: string; output: string; truncated: boolean };
