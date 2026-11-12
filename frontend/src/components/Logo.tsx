import { tr } from "../lib/i18n";
export function Helm({ className = "size-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v7M12 15v7M2 12h7M15 12h7M4.9 4.9l4.9 4.9M14.2 14.2l4.9 4.9M19.1 4.9l-4.9 4.9M9.8 14.2l-4.9 4.9" />
    </svg>
  );
}

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="grid size-9 place-items-center rounded-xl bg-accent text-accentfg"><Helm className="size-5" /></span>
      <span className="text-xl font-semibold tracking-tight">{tr("Kaji")}</span>
    </div>
  );
}
