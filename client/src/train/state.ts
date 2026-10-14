/** Mutable client state of the train page (own instance; the room game's state.ts only lends token/catalog). */

import { state } from "../state";
import type { FugitiveOrder, Hack, OrderType, Report, TrainState } from "./api";

/** What the screen is doing, derived from the server status plus local playback. */
export type Phase = "idle" | "lobby" | "submit" | "playback" | "paused" | "captured";

export interface HunterPick { type: OrderType; target: string | null }
export interface FugitivePick { move: string | null; hack: Hack | null; target: string | null }

export const tstate = {
  payload: null as TrainState | null,
  phase: "idle" as Phase,
  /** my unconfirmed selection (hunter) */
  pick: null as HunterPick | null,
  /** my unconfirmed selection (fugitive) */
  fpick: { move: null, hack: null, target: null } as FugitivePick,
  /** orders the fugitive learned through this round's ping */
  pingOrders: null as Record<string, { type: OrderType; target: string | null } | null> | null,
  /** the round currently being played back (null = none) */
  playing: null as Report | null,
  /** the fugitive's true room as the fugitive view knows it (or the capture room for everyone) */
  revealedRoom: null as string | null,
};

export function me(): string | null {
  return tstate.payload?.you?.id ?? state.id ?? null;
}

/** AI hunters are lobby ids "bot:N" (server bot_player.py); everyone else is shown by their id. */
export function isBot(id: string): boolean {
  return id.startsWith("bot:");
}

export function label(id: string): string {
  return isBot(id) ? `제미나이-${id.slice(4)}` : id;
}

/** The account holding the controls (pause, config, AI crew…). In fugitive-AI games this is not the fugitive. */
export function isAdmin(): boolean {
  return !!tstate.payload?.admin;
}

export function isFugitive(): boolean {
  return tstate.payload?.role === "fugitive";
}

export function isHunter(): boolean {
  return tstate.payload?.role === "hunter";
}

// -- reconnect playback bookkeeping (per game) ------------------------------------------------------------------
const KEY = "train_played";

function readPlayed(): Record<string, number> {
  try {
    const v = localStorage.getItem(KEY);
    return v ? (JSON.parse(v) as Record<string, number>) : {};
  } catch {
    return {};
  }
}

/** Last round whose playback this browser finished for game `gameId` (0 = none). */
export function lastPlayed(gameId: number | null): number {
  if (gameId === null) return 0;
  return readPlayed()[String(gameId)] ?? 0;
}

export function markPlayed(gameId: number | null, round: number): void {
  if (gameId === null) return;
  try {
    const all = readPlayed();
    all[String(gameId)] = Math.max(all[String(gameId)] ?? 0, round);
    // keep the record small: this game and the previous one
    const keys = Object.keys(all).sort((a, b) => Number(b) - Number(a)).slice(0, 2);
    localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(keys.map((k) => [k, all[k]]))));
  } catch { /* private mode etc. */ }
}

export function describeFugitiveOrder(o: FugitiveOrder | FugitivePick | null): string {
  if (!o) return "";
  const parts: string[] = [];
  parts.push(o.move ? `이동 → ${o.move}` : "제자리");
  if (o.hack) parts.push(`${HACK_LABEL[o.hack]}${o.target ? ` (${o.target})` : ""}`);
  return parts.join(" · ");
}

const HACK_LABEL: Record<Hack, string> = {
  ping: "핑", doorlock: "문 잠금", distract: "교란", blackout: "광학 재부팅", hide: "은신", overload: "과부하",
};
