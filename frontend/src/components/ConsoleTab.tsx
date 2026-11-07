import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Guest } from "../lib/api";
import { Button, Notice } from "./ui";

type Mode = "vnc" | "term";
type State = "idle" | "connecting" | "open" | "closed" | "error";

const utf8Length = (s: string) => new TextEncoder().encode(s).length;

/**
 * Onglet « Console » : noVNC (écran, VM et conteneur) ou xterm.js (terminal, conteneur). Le navigateur ne parle qu'à Kaji (WebSocket
 * `/api/console/{session}`), qui relaie vers Proxmox : ni le token, ni l'adresse de Proxmox n'arrivent ici. La console se ferme dès
 * qu'on quitte l'onglet ou la page.
 */
export function ConsoleTab({ connId, guest }: { connId: number; guest: Guest }) {
  const running = guest.status === "running";
  const holder = useRef<HTMLDivElement>(null);
  const closer = useRef<(() => void) | null>(null);
  const rfbRef = useRef<{ sendCtrlAltDel: () => void } | null>(null);
  const [state, setState] = useState<State>("idle");
  const [mode, setMode] = useState<Mode | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const stop = useCallback(() => {
    const c = closer.current;
    closer.current = null;
    rfbRef.current = null;
    try { c?.(); } catch { /* déjà fermée */ }
  }, []);
  useEffect(() => stop, [stop]);                       // quitter l'onglet ou la page ferme la console

  const start = async (m: Mode) => {
    stop();
    setMode(m); setState("connecting"); setMessage(null);
    const el = holder.current;
    if (!el) return;
    el.replaceChildren();
    let session: { session: string; ticket?: string };
    try {
      session = await api<{ session: string; ticket?: string }>(
        `/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/${guest.type}/${guest.vmid}/console`, { method: "POST", body: { kind: m } });
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

  const busy = state === "connecting";
  const live = state === "open" || busy;
  return (
    <div className="space-y-4">
      {!running && <Notice kind="error">La machine doit être en marche pour ouvrir sa console.</Notice>}
      <div className="flex flex-wrap items-center gap-2">
        {!live && <>
          <Button onClick={() => start(guest.type === "lxc" ? "term" : "vnc")} disabled={!running} className="!px-3 !py-1.5">
            {guest.type === "lxc" ? "Ouvrir le terminal" : "Ouvrir la console"}
          </Button>
          {guest.type === "lxc" && <Button variant="ghost" onClick={() => start("vnc")} disabled={!running} className="!px-3 !py-1.5">Écran (noVNC)</Button>}
        </>}
        {live && <Button variant="danger" onClick={() => { stop(); setState("closed"); setMessage("Console fermée."); }} className="!px-3 !py-1.5">Déconnecter</Button>}
        {state === "open" && mode === "vnc" && <Button variant="ghost" onClick={() => rfbRef.current?.sendCtrlAltDel()} className="!px-3 !py-1.5">Ctrl+Alt+Suppr</Button>}
        {state === "open" && <Button variant="ghost" onClick={() => holder.current?.requestFullscreen?.().catch(() => undefined)} className="!px-3 !py-1.5">Plein écran</Button>}
        {busy && <span className="text-sm text-muted">Connexion à la console…</span>}
        {state === "open" && <span className="flex items-center gap-1.5 text-sm text-ok"><span className="size-2 rounded-full bg-ok" />Connecté</span>}
      </div>
      {message && <Notice kind={state === "error" ? "error" : "ok"}>{message}</Notice>}
      <div ref={holder} className={`min-h-[24rem] w-full overflow-hidden rounded-xl border border-line bg-black ${live ? "h-[60vh]" : "hidden"}`} aria-label="Console" />
      <p className="text-xs text-muted">
        Une console donne un accès complet à la machine. Elle est journalisée (ouverture et fermeture, jamais ce que tu tapes ni ce qui s'affiche),
        se ferme après 30 min d'inactivité ou 8 h, et au plus 4 sont ouvertes en même temps.
      </p>
    </div>
  );
}
