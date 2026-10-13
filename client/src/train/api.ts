/** /api/train/* client. `call()` is the room game's api.ts call() with the train error table. */

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

/** One room of an engine map (config.BUILTIN_MAPS row). */
export interface MapRoom { id: string; col: number; row: number; device: string; neighbors: string[] }
export interface MapDetail { id: string; rooms: MapRoom[] }
export interface MapSummary { id: string; rooms: number; cols: number; rows: number }

export type Role = "fugitive" | "hunter" | "spectator";

/** Role payload of GET /api/train/state (views.py). Only the parts the preview needs are typed so far. */
export interface TrainState { status: string; role: Role; [k: string]: unknown }

export const api = {
  state: () => call<TrainState>("GET", "/api/train/state"),
  claim: (secret: string) => call<{ role: Role }>("POST", "/api/train/claim", { secret }),
  maps: () => call<{ maps: MapSummary[] }>("GET", "/api/train/maps"),
  map: (id: string) => call<MapDetail>("GET", `/api/train/maps/${encodeURIComponent(id)}`),
};
