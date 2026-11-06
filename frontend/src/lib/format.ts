export function bytes(n: number | null | undefined): string {
  if (n == null) return "–";
  const u = ["o", "Ko", "Mo", "Go", "To"];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${u[i]}`;
}

export function uptime(s: number | null | undefined): string {
  if (!s) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d} j ${h} h`;
  if (h) return `${h} h ${m} min`;
  return m ? `${m} min` : `${s} s`;
}

export const pct = (used: number | null | undefined, max: number | null | undefined) =>
  used != null && max ? Math.min(100, (used / max) * 100) : 0;
