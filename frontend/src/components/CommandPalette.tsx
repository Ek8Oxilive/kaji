import { useEffect, useMemo, useRef, useState } from "react";

export type Command = { id: string; group: string; label: string; hint?: string; keywords?: string; run: () => void };

const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Tous les mots saisis doivent apparaître (sans tenir compte des accents ni de la casse). */
export function matches(cmd: Command, query: string): boolean {
  const hay = norm(`${cmd.label} ${cmd.hint ?? ""} ${cmd.keywords ?? ""} ${cmd.group}`);
  return norm(query).split(/\s+/).filter(Boolean).every((t) => hay.includes(t));
}

export function CommandPalette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const list = useRef<HTMLUListElement>(null);
  const results = useMemo(() => commands.filter((c) => matches(c, q)).slice(0, 60), [commands, q]);
  const index = Math.min(active, Math.max(results.length - 1, 0));

  useEffect(() => { list.current?.querySelector(`[data-i="${index}"]`)?.scrollIntoView({ block: "nearest" }); }, [index]);

  const run = (c: Command | undefined) => { if (c) { onClose(); c.run(); } };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((index + 1) % Math.max(results.length, 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((index - 1 + results.length) % Math.max(results.length, 1)); }
    else if (e.key === "Enter") { e.preventDefault(); run(results[index]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  let lastGroup = "";
  return (
    <div className="fixed inset-0 z-[70] grid place-items-start justify-items-center bg-black/60 p-4 pt-[12vh]" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Palette de commandes" className="panel rise w-full max-w-xl overflow-hidden" onClick={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setActive(0); }} placeholder="Rechercher une machine ou une action…"
          role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={results[index] ? `cmd-${results[index].id}` : undefined}
          className="w-full border-b border-line bg-transparent px-5 py-4 text-base outline-none placeholder:text-muted" />
        <ul id="palette-list" ref={list} role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
          {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">Aucun résultat</li>}
          {results.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <li key={c.id} role="presentation">
                {header && <div className="px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wider text-muted">{header}</div>}
                <div id={`cmd-${c.id}`} data-i={i} role="option" aria-selected={i === index} onMouseMove={() => setActive(i)} onClick={() => run(c)}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm ${i === index ? "bg-accent text-accentfg" : ""}`}>
                  <span className="truncate">{c.label}</span>
                  {c.hint && <span className={`shrink-0 text-xs ${i === index ? "opacity-80" : "text-muted"}`}>{c.hint}</span>}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="flex gap-4 border-t border-line px-5 py-2 text-xs text-muted"><span>↑↓ naviguer</span><span>↵ choisir</span><span>Échap fermer</span></div>
      </div>
    </div>
  );
}
