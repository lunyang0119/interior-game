/** /api/train/* client + the payload types of views.py. `call()` mirrors the room game's api.ts. */

import type { AvatarLook } from "../catalog";
import { state } from "../state";
import { MESSAGES } from "./strings";

export class ApiError extends Error {
  message: string;
  constructor(public status: number, public code: string, message?: string) {
    super(code);
    this.message = message ?? code;
  }
}

export function msgFor(e: unknown): string {
  if (e instanceof ApiError) return e.code === "rule" ? e.message : (MESSAGES[e.code] ?? e.code);
  return String(e);
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network");
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message: string | undefined;
    try {
      const j = await res.json();
      code = j.error ?? code;
      message = j.message; // engine RuleError text (code "rule")
    } catch { /* ignore */ }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// payload types (server/app/train/views.py; engine PublicView / report)
// ---------------------------------------------------------------------------
export type Role = "fugitive" | "hunter" | "spectator";
export type OrderType = "move" | "search" | "scan" | "stay";
export type Hack = "ping" | "doorlock" | "distract" | "blackout" | "hide" | "overload";

export interface MapRoom { id: string; col: number; row: number; device: string; neighbors: string[] }
export interface MapDetail { id: string; rooms: MapRoom[] }
export interface MapSummary { id: string; rooms: number; cols: number; rows: number }
/** engine map row (PublicView.map_rows): neighbours as a comma string */
export interface MapRow { map_id: string; room: string; device: string; neighbors: string; col: number; row: number }

export interface Order { type: OrderType; target: string | null }
export interface FugitiveOrder { move: string | null; hack: Hack | null; target: string | null }

export interface HunterPub { name: string; room: string; tag: string; submitted: boolean; dazed: boolean; color: string }
export interface PlaybackHunter { id: string; from: string; to: string; blocked_edge: string | null; action: OrderType; result: string | null }
export interface ReportEvent { type: string; uid: string; room?: string; edge?: string; device?: string }

export interface PublicView {
  round_no: number; status: string; trace: number; bar: string; signal: string;
  hunters: HunterPub[]; locks: string[]; markers: string[]; steam: string[];
  map_rows: MapRow[]; map_id: string; capture_room: string | null;
  playback: PlaybackHunter[]; glimpses: string[];
}

export interface Report {
  round: number; trace: number; bar: string; tier: number; signal: string; distance: number | null;
  signature: string | null; markers: string[]; locks: string[]; steam: string[]; blackout: boolean;
  events: ReportEvent[]; order: string[]; timed_out: boolean; traced: boolean; frozen: boolean;
  captured_by: string | null; capture_how: string | null;
  hunters: Record<string, { name: string; room: string }>;
  playback: { hunters: PlaybackHunter[]; fugitive_path?: string[] };
  /** fugitive client only, attached from the ws `log_entry` / the payload `log`: the own order and the engine's
   *  hidden notes ("퀵핵 doorlock → A1-A2", "퀵핵 hide 무효: …", "잠긴 문(…) 앞에서 정지") */
  fugitive_order?: FugitiveOrder | null;
  hidden_events?: string[];
}

/** engine log entry (fugitive payload `log`): the full report plus what the hunters never see */
export interface LogEntry { round: number; report: Report; hidden_events: string[]; fugitive_order: FugitiveOrder | null }

export interface FugitiveState {
  room: string; ram: number; trace: number; tier: number; hidden_until: number; frozen: boolean;
  hacks_disabled: boolean; traced_at: number | null; ping_round: number; pinged: boolean; order: FugitiveOrder | null;
}

export interface TrainState {
  game_id: number | null;
  status: "IDLE" | "LOBBY" | "ROUND_OPEN" | "PAUSED" | "CAPTURED" | "ENDED";
  role: Role;
  hunter_count?: number;
  map_id?: string;
  lobby?: string[];
  deadline_ts?: number;
  grace_until?: number | null;
  paused_remaining?: number | null;
  vote_after_ts?: number | null;
  votes?: Record<string, string[]>;
  need?: number;
  you: { id: string; room: string | null; order: Order | null; dazed: boolean } | null;
  avatars?: Record<string, AvatarLook>;
  round_no?: number;
  view?: PublicView | null;
  report?: Report | null;
  /** the last few rounds' public reports, oldest first (a client that was away replays the unseen ones in order) */
  reports?: Report[];
  orders?: Record<string, Order | null>;
  /** whether the fugitive has submitted this round (everyone sees the flag, never the order) */
  fugitive_submitted?: boolean;
  config?: Record<string, unknown>;
  ai_available?: boolean;
  admin?: boolean;
  fugitive_ai?: boolean;
  /** every AI's reasoning, present once the game is CAPTURED (fugitive entries have uid "fugitive") */
  ai_log?: BotReason[];
  /** the fugitive's route per round; only while CAPTURED and the admin's "경로 공개" is on */
  route?: { round: number; path: string[] }[];
  // fugitive / admin only
  bot_reasons?: BotReason[];
  fugitive?: FugitiveState | null;
  hacks?: Record<Hack, { ok: boolean; why: string; cost: number; trace: number }>;
  reachable?: string[];
  lockable_edges?: string[];
  hunters_full?: Record<string, { name: string; room: string; submitted: boolean; dazed_until: number; order: Order | null }>;
  log?: LogEntry[];
  position_history?: string[];
  overrides?: Record<string, unknown>;
}

export interface BotReason {
  round: number; uid: string; name: string; order: string; target: string | null; reason: string;
  accepted: boolean; note: string; error: string | null;
  hack_target?: string | null;
}

export interface HelpText {
  tutorial: string; help: string; devices: Record<string, string>; hacks: Record<string, string>;
  hack_devices: Record<string, string | null>; signals: Record<string, string>;
}

export interface ConfigResponse { config: Record<string, unknown>; overrides: Record<string, unknown>; map_id: string; defaults: Record<string, unknown> }

export function mapRooms(rows: MapRow[]): MapRoom[] {
  return rows.map((r) => ({ id: r.room, col: r.col, row: r.row, device: r.device, neighbors: r.neighbors.split(",").filter(Boolean) }));
}

export const api = {
  state: () => call<TrainState>("GET", "/api/train/state"),
  claim: (secret: string) => call<{ role: Role }>("POST", "/api/train/claim", { secret }),
  maps: () => call<{ maps: MapSummary[] }>("GET", "/api/train/maps"),
  map: (id: string) => call<MapDetail>("GET", `/api/train/maps/${encodeURIComponent(id)}`),
  create: (hunter_count: number, map_id?: string, fugitive_ai = false) => call<TrainState>("POST", "/api/train/game", { hunter_count, map_id, fugitive_ai }),
  setFugitiveAi: (on: boolean) => call<TrainState>("POST", "/api/train/fugitive-ai", { on }),
  reveal: (on: boolean) => call<TrainState>("POST", "/api/train/reveal", { on }),
  help: () => call<HelpText>("GET", "/api/train/help"),
  join: () => call<TrainState>("POST", "/api/train/join", {}),
  leave: () => call<TrainState>("POST", "/api/train/leave", {}),
  start: () => call<TrainState>("POST", "/api/train/start", {}),
  addBots: (target_count: number) => call<TrainState>("POST", "/api/train/bots", { target_count }),
  removeBots: () => call<TrainState>("DELETE", "/api/train/bots"),
  order: (type: OrderType, target?: string | null) => call<{ order: Order }>("POST", "/api/train/order", { type, target: target ?? null }),
  cancelOrder: () => call<{ order: null }>("DELETE", "/api/train/order"),
  fugitiveOrder: (o: Partial<FugitiveOrder>) => call<{ order: FugitiveOrder; resolved: boolean }>("POST", "/api/train/fugitive/order", o),
  cancelFugitiveOrder: () => call<{ order: null }>("DELETE", "/api/train/fugitive/order"),
  ping: () => call<{ orders: Record<string, Order | null>; ram: number; trace: number }>("POST", "/api/train/fugitive/ping", {}),
  vote: (target: string) => call<{ votes: string[]; need: number; passed: boolean }>("POST", "/api/train/vote", { target }),
  getConfig: () => call<ConfigResponse>("GET", "/api/train/config"),
  setConfig: (set: Record<string, unknown>, map_id?: string) => call<ConfigResponse>("PUT", "/api/train/config", { set, map_id }),
  resetConfig: () => call<ConfigResponse>("PUT", "/api/train/config", { reset: true }),
  pause: () => call<unknown>("POST", "/api/train/pause", {}),
  resume: () => call<unknown>("POST", "/api/train/resume", {}),
  extend: (sec: number) => call<unknown>("POST", "/api/train/extend", { sec }),
  endRound: () => call<TrainState>("POST", "/api/train/round/end", {}),
  endGame: () => call<unknown>("POST", "/api/train/game/end", {}),
};
