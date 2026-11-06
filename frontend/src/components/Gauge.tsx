export function Gauge({ label, value, detail }: { label: string; value: number; detail?: string }) {
  const color = value >= 90 ? "bg-danger" : value >= 70 ? "bg-warn" : "bg-accent";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className="tabular-nums">{detail ?? `${value.toFixed(0)} %`}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface2" role="progressbar" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full rounded-full transition-[width] duration-700 ease-out ${color}`} style={{ width: `${Math.max(value, value > 0 ? 2 : 0)}%` }} />
      </div>
    </div>
  );
}
