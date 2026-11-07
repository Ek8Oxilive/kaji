/** Types de la page « Tâches » : forme des réponses de `GET /api/connections/{id}/tasks` (docs/api/taches.md). */
export type TaskState = "running" | "ok" | "warning" | "error";

export type TaskRow = {
  upid: string; node: string | null; type: string | null; id: string | null;
  user: string | null; token: string | null;
  start: string | null; end: string | null; duration: number | null;
  state: TaskState; status_text: string | null; by_kaji: boolean;
};

export type TaskList = { tasks: TaskRow[]; failed: { node: string; reason: string }[] };

/** `GET /api/connections/{id}/tasks/{node}/{upid}` (existant) */
export type TaskDetail = { status: string | null; exitstatus: string | null; type: string | null; id: string | null; user: string | null; starttime: number | null; ok: boolean; warnings: boolean };
export type TaskLine = { n: number | null; t: string | null };
