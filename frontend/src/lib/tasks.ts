import { api, type TaskStatus } from "./api";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Attend la fin d'une tâche Proxmox (UPID). Renvoie null si elle dépasse le délai. */
export async function waitTask(connId: number, node: string, upid: string, seconds = 90): Promise<TaskStatus | null> {
  for (let i = 0; i < seconds; i++) {
    await sleep(1000);
    const t = await api<TaskStatus>(`/api/connections/${connId}/tasks/${node}/${encodeURIComponent(upid)}`);
    if (t.status === "stopped") return t;
  }
  return null;
}

/** Lance une action qui renvoie un UPID, attend sa fin et lève une erreur claire si la tâche échoue. */
/** Durée d'attente des opérations longues (migration, clonage, déplacement de disque) : 30 minutes. */
export const LONG_TASK_SECONDS = 1800;

export async function runTask(connId: number, node: string, start: () => Promise<{ upid: string }>, what: string, seconds = 90) {
  const { upid } = await start();
  const t = await waitTask(connId, node, upid, seconds);
  if (!t) throw new Error(`${what} : la tâche prend trop de temps`);
  if (!t.ok) throw new Error(`${what} : la tâche a échoué (${t.exitstatus ?? "erreur"})`);
}
