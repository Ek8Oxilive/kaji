// noVNC ne fournit pas de types : seule la partie de l'API que Kaji utilise est déclarée.
declare module "@novnc/novnc" {
  export interface RFBOptions {
    credentials?: { username?: string; password?: string; target?: string };
    wsProtocols?: string[];
    shared?: boolean;
  }
  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, urlOrChannel: string | WebSocket, options?: RFBOptions);
    scaleViewport: boolean;
    resizeSession: boolean;
    clipViewport: boolean;
    viewOnly: boolean;
    focusOnClick: boolean;
    background: string;
    disconnect(): void;
    focus(): void;
    sendCtrlAltDel(): void;
    sendCredentials(credentials: { username?: string; password?: string; target?: string }): void;
  }
}
