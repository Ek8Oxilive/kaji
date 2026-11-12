import { useEffect, useId, useMemo, useRef, useState } from "react";

import { tr, locale } from "../../lib/i18n";
/** Une courbe. `slot` : emplacement de couleur (1 bleu, 2 orange), attribué dans l'ordre, jamais d'après le rang (palette validée). */
export type Series = { id: string; label: string; slot: 1 | 2; values: (number | null)[] };
export type Timeframe = "hour" | "day" | "week" | "month" | "year";

type Props = {
  title: string; subtitle?: string;
  times: number[]; series: Series[];
  /** Valeur lisible (survol, tableau, valeur actuelle). */
  format: (v: number) => string;
  /** Borne haute du domaine si elle est connue (100 % d'un processeur, mémoire totale) ; le domaine l'élargit si les données la dépassent. */
  domainMax?: number;
  /** Octets : les graduations s'arrondissent sur des multiples de 1024 (1, 2, 5 Ko, Mo, Go…) et non de 1000. */
  bytes?: boolean;
  timeframe: Timeframe;
  /** Rechargement en cours : on garde l'image précédente, atténuée (pas de squelette, pas de saut de mise en page). */
  loading?: boolean;
};

const W_MIN = 280, H = 168, X_BAND = 24, M = { r: 12, t: 10 };

/** Plus grand « nombre rond » (1, 2, 5 × 10ⁿ) au moins égal à `v`, pour des graduations propres. `base` 1024 : octets (1, 2, 5 Ko…). */
export function niceMax(v: number, base: 10 | 1024 = 10): number {
  if (!(v > 0) || !Number.isFinite(v)) return 1;
  const u = base === 1024 ? 1024 ** Math.max(0, Math.floor(Math.log(v) / Math.log(1024))) : 1;
  const x = v / u, p = 10 ** Math.floor(Math.log10(x)), f = x / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p * u;
}

function timeLabel(t: number, tf: Timeframe): string {
  const d = new Date(t * 1000);
  if (tf === "hour" || tf === "day") return d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  if (tf === "year") return d.toLocaleDateString(locale(), { month: "short", year: "2-digit" });
  return d.toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
}
const fullTime = (t: number) => new Date(t * 1000).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" });

/** Chemin d'une courbe : une valeur absente interrompt la ligne (un trou n'est jamais comblé ni lu comme zéro). */
function pathOf(xs: number[], ys: (number | null)[], sx: (t: number) => number, sy: (v: number) => number): string {
  let d = "", open = false;
  ys.forEach((v, i) => {
    if (v === null) { open = false; return; }
    d += `${open ? "L" : "M"}${sx(xs[i]).toFixed(1)} ${sy(v).toFixed(1)}`;
    open = true;
  });
  return d;
}

export function TimeChart({ title, subtitle, times, series, format, domainMax, bytes, timeframe, loading }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(520);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const uid = useId();

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.max(W_MIN, el.clientWidth)));
    ro.observe(el);
    setWidth(Math.max(W_MIN, el.clientWidth));
    return () => ro.disconnect();
  }, []);

  const n = times.length;
  const dataMax = Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)));
  // Domaine connu (100 %, mémoire totale) : l'axe s'y arrête ; sinon un nombre rond au-dessus du maximum. Les données qui le dépassent l'élargissent.
  const yMax = (domainMax && dataMax <= domainMax ? domainMax : Math.max(domainMax ?? 0, niceMax(dataMax, bytes ? 1024 : 10))) || 1;
  const t0 = times[0] ?? 0, t1 = times[n - 1] ?? 1;
  // Marge gauche selon la longueur réelle des étiquettes de l'axe (sinon « 18,8 Ko/s » est coupé).
  const ml = Math.min(96, Math.max(44, Math.max(...[0, 1, 2, 3, 4].map((i) => format((yMax * i) / 4).length)) * 6.4 + 16));
  const pw = width - ml - M.r;
  const sx = (t: number) => ml + (t1 === t0 ? pw / 2 : ((t - t0) / (t1 - t0)) * pw);
  const sy = (v: number) => M.t + (1 - Math.min(v, yMax) / yMax) * H;
  const ticks = [0, 1, 2, 3, 4].map((i) => (yMax * i) / 4);
  const xticks = n < 2 ? [] : [0, 1, 2, 3, 4].map((i) => times[Math.round(((n - 1) * i) / 4)]);

  const nearest = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || n === 0) return null;
    const t = t0 + ((clientX - rect.left - ml) / pw) * (t1 - t0);
    let lo = 0, hi = n - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (times[mid] < t) lo = mid + 1; else hi = mid; }
    return lo > 0 && Math.abs(times[lo - 1] - t) < Math.abs(times[lo] - t) ? lo - 1 : lo;
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (n === 0) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); setHover((h) => Math.max(0, (h ?? n) - 1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); setHover((h) => Math.min(n - 1, (h ?? -1) + 1)); }
    else if (e.key === "Escape") setHover(null);
  };

  const last = (s: Series) => { for (let i = s.values.length - 1; i >= 0; i--) if (s.values[i] !== null) return s.values[i]; return null; };
  const summary = useMemo(() => series.map((s) => {
    const v = s.values.filter((x): x is number => x !== null);
    return v.length ? tr("{label} : minimum {p}, maximum {p2}, dernière valeur {p3}", { label: s.label, p: format(Math.min(...v)), p2: format(Math.max(...v)), p3: format(v[v.length - 1]) }) : tr("{label} : aucune mesure", { label: s.label });
  }).join(". "), [series, format]);

  const single = series.length === 1;
  const h = hover !== null && hover < n ? hover : null;
  const tipLeft = h !== null ? Math.min(Math.max(sx(times[h]) + 12, 4), width - 190) : 0;

  return (
    <figure className="panel space-y-2 p-4" aria-label={title}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <figcaption>
          <h3 className="text-sm font-semibold">{title}</h3>
          {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
        </figcaption>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          {series.map((s) => (
            <span key={s.id} className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4 rounded" style={{ background: `var(--series-${s.slot})` }} aria-hidden />
              <span className="text-muted">{s.label}</span>
              <strong className="tabular-nums">{last(s) === null ? "–" : format(last(s) as number)}</strong>
            </span>
          ))}
        </div>
      </div>

      <div ref={box} className={`relative transition-opacity ${loading ? "opacity-60" : ""}`} style={{ height: M.t + H + X_BAND }}>
        {n < 2 || series.every((s) => s.values.every((v) => v === null))
          ? <div className="grid h-full place-items-center rounded-xl border border-line text-sm text-muted">{tr("Aucune mesure sur cette période.")}</div>
          : (
            <>
              <svg width={width} height={M.t + H + X_BAND} role="img" aria-label={`${title}. ${summary}`} tabIndex={0} onKeyDown={onKey} onBlur={() => setHover(null)}
                className="block touch-none rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                onPointerMove={(e) => setHover(nearest(e.clientX))} onPointerLeave={() => setHover(null)}>
                {ticks.map((v, i) => (
                  <g key={i}>
                    <line x1={ml} x2={width - M.r} y1={sy(v)} y2={sy(v)} stroke="var(--line)" strokeWidth={1} />
                    <text x={ml - 8} y={sy(v) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{format(v)}</text>
                  </g>
                ))}
                {xticks.map((t, i) => (
                  <text key={i} x={Math.min(Math.max(sx(t), ml + 14), width - M.r - 14)} y={M.t + H + 17} textAnchor="middle" fontSize={11} fill="var(--muted)">{timeLabel(t, timeframe)}</text>
                ))}
                {single && series[0] && <AreaFill uid={uid} times={times} values={series[0].values} sx={sx} sy={sy} base={sy(0)} slot={series[0].slot} />}
                {series.map((s) => (
                  <path key={s.id} d={pathOf(times, s.values, sx, sy)} fill="none" stroke={`var(--series-${s.slot})`} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                ))}
                {h !== null && (
                  <g pointerEvents="none">
                    <line x1={sx(times[h])} x2={sx(times[h])} y1={M.t} y2={M.t + H} stroke="var(--muted)" strokeWidth={1} />
                    {series.map((s) => s.values[h] !== null && (
                      <circle key={s.id} cx={sx(times[h])} cy={sy(s.values[h] as number)} r={4} fill={`var(--series-${s.slot})`} stroke="var(--surface2)" strokeWidth={2} />
                    ))}
                  </g>
                )}
              </svg>
              {h !== null && (
                <div role="status" className="pointer-events-none absolute top-1 z-10 w-44 rounded-lg border border-line bg-surface2 p-2 text-xs shadow-lg" style={{ left: tipLeft }}>
                  <p className="mb-1 text-muted">{fullTime(times[h])}</p>
                  {series.map((s) => (
                    <p key={s.id} className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-muted"><span className="inline-block h-0.5 w-3 rounded" style={{ background: `var(--series-${s.slot})` }} aria-hidden />{s.label}</span>
                      <strong className="tabular-nums">{s.values[h] === null ? "–" : format(s.values[h] as number)}</strong>
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
      </div>

      <div className="flex justify-end">
        <button type="button" className="text-xs text-muted underline hover:text-fg" aria-expanded={table} onClick={() => setTable((t) => !t)}>{table ? tr("Masquer le tableau") : tr("Afficher le tableau")}</button>
      </div>
      {table && (
        <div className="max-h-56 overflow-y-auto rounded-xl border border-line">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-surface2"><tr className="text-left text-muted"><th scope="col" className="px-3 py-1.5 font-normal">{tr("Date")}</th>{series.map((s) => <th key={s.id} scope="col" className="px-3 py-1.5 text-right font-normal">{s.label}</th>)}</tr></thead>
            <tbody>
              {times.map((t, i) => (
                <tr key={t} className="border-t border-line/60"><td className="px-3 py-1 text-muted">{fullTime(t)}</td>{series.map((s) => <td key={s.id} className="px-3 py-1 text-right tabular-nums">{s.values[i] === null ? "–" : format(s.values[i] as number)}</td>)}</tr>
              )).reverse()}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}

/** Lavis de la courbe d'une série seule (environ 10 % d'opacité), qui s'interrompt aux trous comme la courbe. */
function AreaFill({ uid, times, values, sx, sy, base, slot }: { uid: string; times: number[]; values: (number | null)[]; sx: (t: number) => number; sy: (v: number) => number; base: number; slot: 1 | 2 }) {
  const runs: string[] = [];
  let cur: number[] = [];
  const flush = () => {
    if (cur.length > 1) {
      const top = cur.map((i, k) => `${k ? "L" : "M"}${sx(times[i]).toFixed(1)} ${sy(values[i] as number).toFixed(1)}`).join("");
      runs.push(`${top}L${sx(times[cur[cur.length - 1]]).toFixed(1)} ${base.toFixed(1)}L${sx(times[cur[0]]).toFixed(1)} ${base.toFixed(1)}Z`);
    }
    cur = [];
  };
  values.forEach((v, i) => { if (v === null) flush(); else cur.push(i); });
  flush();
  return <path key={uid} d={runs.join("")} fill={`var(--series-${slot})`} fillOpacity={0.1} stroke="none" />;
}
