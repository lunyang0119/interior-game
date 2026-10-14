/** /ws/train socket: the room game's GameSocket (ws.ts) with the endpoint as a parameter and no move/enter. */

type Handler = (msg: any) => void;

const PING_MS = 25_000;
const BACKOFF_MAX_MS = 15_000;

export class TrainSocket {
  private ws: WebSocket | null = null;
  private token: string | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private backoff = 1000;
  private pingTimer: number | null = null;
  private reconnectTimer: number | null = null;
  private closedByUser = false;
  connected = false;

  constructor(private readonly path = "/ws/train") {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && this.token && !this.connected) this.reconnectNow();
    });
  }

  on(type: string, fn: Handler): () => void {
    let set = this.handlers.get(type);
    if (!set) this.handlers.set(type, (set = new Set()));
    set.add(fn);
    return () => set!.delete(fn);
  }

  connect(token: string): void {
    this.close();
    this.closedByUser = false;
    this.token = token;
    this.open();
  }

  close(): void {
    this.closedByUser = true;
    this.token = null;
    this.stopTimers();
    if (this.ws) {
      try { this.ws.close(); } catch { /* ignore */ }
      this.ws = null;
    }
    this.setConnected(false);
  }

  private send(obj: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  private open(): void {
    if (!this.token) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}${this.path}`);
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token: this.token }));
      this.backoff = 1000;
      this.setConnected(true);
      this.pingTimer = window.setInterval(() => this.send({ type: "ping" }), PING_MS);
    };
    ws.onmessage = (ev) => {
      let msg: { type: string };
      try { msg = JSON.parse(ev.data); } catch { return; }
      this.handlers.get(msg.type)?.forEach((fn) => fn(msg));
      this.handlers.get("*")?.forEach((fn) => fn(msg));
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.stopTimers();
      this.setConnected(false, ev.code);
      if (this.closedByUser || ev.code === 4401) return; // bad token: don't retry
      this.reconnectTimer = window.setTimeout(() => this.open(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS);
    };
    ws.onerror = () => { /* onclose follows */ };
  }

  private reconnectNow(): void {
    if (this.reconnectTimer !== null) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    this.backoff = 1000;
    if (!this.ws) this.open();
  }

  private stopTimers(): void {
    if (this.pingTimer !== null) { clearInterval(this.pingTimer); this.pingTimer = null; }
    if (this.reconnectTimer !== null) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
  }

  private setConnected(v: boolean, code = 0): void {
    if (this.connected === v) return;
    this.connected = v;
    this.handlers.get(v ? "open" : "close")?.forEach((fn) => fn(v ? { type: "open" } : { type: "close", code }));
  }
}

export const tsocket = new TrainSocket();
