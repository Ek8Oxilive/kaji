export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function messageOf(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? "Valeur invalide").join(" · ");
  return `Erreur ${status}`;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? "GET",
    headers: init.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    credentials: "same-origin",
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, messageOf(body, res.status));
  return body as T;
}

export type AuthStatus = { setup_required: boolean; authenticated: boolean };
export type Connection = {
  id: number; name: string; host: string; port: number; user: string; token_id: string; verify_ssl: boolean;
};
export type ProbeResult = { ok: boolean; version?: string; release?: string; error?: string };
