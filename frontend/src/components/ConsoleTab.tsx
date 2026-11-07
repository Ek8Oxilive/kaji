import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Guest } from "../lib/api";
import { Button, Notice } from "./ui";

export type ConsoleMode = "vnc" | "term";
type State = "idle" | "connecting" | "open" | "closed" | "error";

const utf8Length = (s: string) => new TextEncoder().encode(s).length;

/**
 * Moteur d'une console : noVNC (écran) ou xterm.js (terminal). Le navigateur ne parle qu'à Kaji (WebSocket `/api/console/{session}`), qui
 * relaie vers Proxmox : ni le token, ni l'adresse de Proxmox n'arrivent ici. La console se ferme dès qu'on quitte la page ou l'onglet.
 * `openPath` : route qui demande la console ; `bodyFor` : corps de la demande.
 */
function useConsole(openPath: string, bodyFor: (m: ConsoleMode) => object) {
  const holder = useRef<HTMLDivElement>(null);
  const closer = useRef<(() => void) | null>(null);
  const rfbRef = useRef<{ sendCtrlAltDel: () => void } | null>(null);
  const [state, setState] = useState<State>("idle");
  const [mode, setMode] = useState<ConsoleMode | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const stop = useCallback(() => {
    const c = closer.current;
    closer.current = null;
    rfbRef.current = null;
    try { c?.(); } catch { /* déjà fermée */ }
  }, []);
  useEffect(() => stop, [stop]);

  const start = async (m: ConsoleMode) => {
    stop();
    setMode(m); setState("connecting"); setMessage(null);
    const el = holder.current;
    if (!el) return;
    el.replaceChildren();
    let session: { session: string; ticket?: string };
    try {
      session = await api<{ session: string; ticket?: string }>(openPath, { method: "POST", body: bodyFor(m) });
    } catch (e) {
      setState("error"); setMessage((e as Error).message); return;
    }
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/console/${session.session}`;
    let opened = false;
    const fail = (clean: boolean) => {
      setState(opened ? "closed" : "error");
      setMessage(opened ? (clean ? "Console fermée." : "Connexion à la console perdue.") : "Impossible d'ouvrir la console (refusée ou Proxmox injoignable).");
    };
    const slow = window.setTimeout(() => { if (!opened) { stop(); setState("error"); setMessage("La console ne répond pas."); } }, 20_000);

    try {
      if (m === "vnc") {
        const { default: RFB } = await import("@novnc/novnc");
        const rfb = new RFB(el, url, { credentials: { password: session.ticket ?? "" }, wsProtocols: ["binary"] });
        rfb.scaleViewport = true;
        rfb.resizeSession = false;
        rfb.background = "#000000";
        rfb.addEventListener("connect", () => { opened = true; window.clearTimeout(slow); setState("open"); rfb.focus(); });
        rfb.addEventListener("disconnect", (e) => { window.clearTimeout(slow); fail(!!(e as CustomEvent<{ clean: boolean }>).detail?.clean); });
        rfb.addEventListener("securityfailure", () => { window.clearTimeout(slow); setState("error"); setMessage("Authentification de la console refusée."); });
        rfb.addEventListener("credentialsrequired", () => rfb.sendCredentials({ password: session.ticket ?? "" }));
        rfbRef.current = rfb;
        closer.current = () => { window.clearTimeout(slow); rfb.disconnect(); };
      } else {
        const [{ Terminal }, { FitAddon }] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
        await import("@xterm/xterm/css/xterm.css");
        const term = new Terminal({ cursorBlink: true, fontSize: 14, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", theme: { background: "#000000" } });
        const fit = new FitAddon();
        term.loadAddon(fit);
        term.open(el);
        fit.fit();
        const ws = new WebSocket(url, ["binary"]);
        ws.binaryType = "arraybuffer";
        const resize = () => { fit.fit(); if (ws.readyState === WebSocket.OPEN) ws.send(`1:${term.cols}:${term.rows}:`); };
        const observer = new ResizeObserver(resize);
        observer.observe(el);
        let ping = 0;
        ws.onopen = () => {
          opened = true; window.clearTimeout(slow); setState("open"); resize(); term.focus();
          ping = window.setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send("2"); }, 30_000);   // maintien de la liaison (protocole de Proxmox)
        };
        ws.onmessage = (e) => term.write(typeof e.data === "string" ? e.data : new Uint8Array(e.data as ArrayBuffer));
        ws.onclose = (e) => { window.clearTimeout(slow); window.clearInterval(ping); fail(e.code === 1000 || e.code === 1005); };
        term.onData((d) => { if (ws.readyState === WebSocket.OPEN) ws.send(`0:${utf8Length(d)}:${d}`); });
        closer.current = () => { window.clearTimeout(slow); window.clearInterval(ping); observer.disconnect(); ws.onclose = null; ws.close(); term.dispose(); };
      }
    } catch (e) {
      window.clearTimeout(slow);
      setState("error"); setMessage(`Le module de console n'a pas pu se charger : ${(e as Error).message}`);
    }
  };

  const disconnect = () => { stop(); setState("closed"); setMessage("Console fermée."); };
  return { holder, rfbRef, state, mode, message, start, disconnect };
}

/** Barre d'état et zone d'affichage communes. */
function Screen({ c, children }: { c: ReturnType<typeof useConsole>; children: ReactNode }) {
  const busy = c.state === "connecting";
  const live = c.state === "open" || busy;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {!live && children}
        {live && <Button variant="danger" onClick={c.disconnect} className="!px-3 !py-1.5">Déconnecter</Button>}
        {c.state === "open" && c.mode === "vnc" && <Button variant="ghost" onClick={() => c.rfbRef.current?.sendCtrlAltDel()} className="!px-3 !py-1.5">Ctrl+Alt+Suppr</Button>}
        {c.state === "open" && <Button variant="ghost" onClick={() => c.holder.current?.requestFullscreen?.().catch(() => undefined)} className="!px-3 !py-1.5">Plein écran</Button>}
        {busy && <span className="text-sm text-muted">Connexion à la console…</span>}
        {c.state === "open" && <span className="flex items-center gap-1.5 text-sm text-ok"><span className="size-2 rounded-full bg-ok" />Connecté</span>}
      </div>
      {c.message && <Notice kind={c.state === "error" ? "error" : "ok"}>{c.message}</Notice>}
      <div ref={c.holder} className={`min-h-[24rem] w-full overflow-hidden rounded-xl border border-line bg-black ${live ? "h-[60vh]" : "hidden"}`} aria-label="Console" />
    </div>
  );
}

/** Onglet « Console » d'une machine : noVNC (VM et conteneur) ou xterm.js (conteneur). */
export function ConsoleTab({ connId, guest }: { connId: number; guest: Guest }) {
  const running = guest.status === "running";
  const c = useConsole(`/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/${guest.type}/${guest.vmid}/console`, (m) => ({ kind: m }));
  const live = c.state === "open" || c.state === "connecting";
  return (
    <div className="space-y-4">
      {!running && <Notice kind="error">La machine doit être en marche pour ouvrir sa console.</Notice>}
      <Screen c={c}>
        <Button onClick={() => c.start(guest.type === "lxc" ? "term" : "vnc")} disabled={!running || live} className="!px-3 !py-1.5">
          {guest.type === "lxc" ? "Ouvrir le terminal" : "Ouvrir la console"}
        </Button>
        {guest.type === "lxc" && <Button variant="ghost" onClick={() => c.start("vnc")} disabled={!running} className="!px-3 !py-1.5">Écran (noVNC)</Button>}
      </Screen>
      <p className="text-xs text-muted">
        Une console donne un accès complet à la machine. Elle est journalisée (ouverture et fermeture, jamais ce que tu tapes ni ce qui s'affiche),
        se ferme après 30 min d'inactivité ou 8 h, et au plus 4 sont ouvertes en même temps.
      </p>
    </div>
  );
}

/** Console (shell) d'un nœud : accès au système de l'hôte, donc case à cocher et droit `Sys.Console` côté Proxmox. */
export function NodeConsole({ connId, node, online }: { connId: number; node: string; online: boolean }) {
  const [ok, setOk] = useState(false);
  const c = useConsole(`/api/connections/${connId}/nodes/${encodeURIComponent(node)}/console`, () => ({ confirm: true }));
  const live = c.state === "open" || c.state === "connecting";
  const noRight = c.state === "error" && /Droits insuffisants|Sys\.Console/i.test(c.message ?? "");
  return (
    <div className="space-y-4">
      {!online && <Notice kind="error">Le nœud est hors ligne : sa console n'est pas disponible.</Notice>}
      {!live && (
        <div className="space-y-2 rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
          <p>Cette console est une session <strong>sur le nœud lui-même</strong> : accès au système de l'hôte Proxmox. Elle demande <code>login:</code>, avec un compte du nœud
            (Kaji ne stocke ni ne transmet aucun identifiant). Elle se ferme après 10 min d'inactivité ou 1 h.</p>
          <label className="flex items-start gap-2"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={ok} onChange={(e) => setOk(e.target.checked)} />
            <span>Je comprends que cette console donne accès au système de « {node} ».</span></label>
        </div>
      )}
      <Screen c={c}>
        <Button onClick={() => c.start("term")} disabled={!online || !ok} className="!px-3 !py-1.5">Ouvrir le shell du nœud</Button>
      </Screen>
      {noRight && <p className="text-xs text-muted">Il manque le droit <code>Sys.Console</code> sur <code>/nodes</code> : la page « Accès » propose la commande à copier.</p>}
      {live && <p className="text-xs text-muted">Journalisée (ouverture et fermeture, jamais le contenu).</p>}
    </div>
  );
}
