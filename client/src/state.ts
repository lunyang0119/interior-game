import type { CatView, ComfortView, RoomProgress } from "./api";
import { bus } from "./bus";
import { DEFAULT_LOOK, type AvatarLook, type Catalog } from "./catalog";

export interface Contribution { id: string; earned: number }

/** Mutable app-wide state. Change through the owning module, read anywhere. */
export const state = {
  catalog: null as Catalog | null,
  id: null as string | null,
  token: null as string | null,
  balance: 0,
  contributions: [] as Contribution[],
  avatar: { ...DEFAULT_LOOK } as AvatarLook,
  online: 0,
  /** Grid room the Room scene shows (id from the catalog). */
  roomId: "inn",
  roomVersion: -1,
  /** ruined-tagged items left in the current room. */
  ruined: 0,
  /** Restoration progress per room id (rooms without stages are absent) and the places that are still locked. */
  progress: {} as Record<string, RoomProgress>,
  locked: new Set<string>(),
  /** Comfort + tonight's guests per guest unit key (`room` or `room:zone`), from /api/rooms or /api/activity. */
  comfort: {} as Record<string, ComfortView>,
  /** Zone id the avatar stands in (null = none / the room has no zones). */
  zone: null as string | null,
  /** The inn cat: affection 0–3 and the taps behind it (from /api/activity, the ws `cat` message or our own pets). */
  cat: { affection: 0, taps: 0 } as CatView,
};

export const CAT_TAPS_PER_LEVEL = 100;
export const CAT_MAX_AFFECTION = 3;

export function applyCat(view: CatView | null | undefined): void {
  if (!view) return; // an older server has no cat picture
  state.cat = { affection: view.affection, taps: view.taps };
  bus.emit("cat:changed");
}

/** The guest unit the avatar is in right now. */
export function currentUnit(): string {
  return state.zone ? `${state.roomId}:${state.zone}` : state.roomId;
}

export function setZone(zone: string | null): void {
  if (zone === state.zone) return;
  state.zone = zone;
  bus.emit("zone:changed", { zone });
}

export function catalog(): Catalog {
  if (!state.catalog) throw new Error("catalog not loaded");
  return state.catalog;
}

/** New progress picture (from /api/rooms, /api/activity or the ws `progress` message). Emits progress:changed with
 *  the stages that completed since the last picture, so the UI can celebrate them. */
/** New comfort picture for every open guest unit (merged from /api/rooms' per-room dicts or /api/activity). */
export function applyComfort(views: Record<string, ComfortView> | null | undefined): void {
  state.comfort = views ?? {}; // an older server (no `comfort` in /api/activity) must not wipe the picture to undefined
  bus.emit("comfort:changed");
}

export function applyProgress(progress: Record<string, RoomProgress>, locked: string[]): void {
  const completed: { room: string; from: number; to: number }[] = [];
  for (const [room, p] of Object.entries(progress)) {
    const before = state.progress[room]?.stage;
    if (before !== undefined && p.stage > before) completed.push({ room, from: before, to: p.stage });
  }
  state.progress = progress;
  state.locked = new Set(locked);
  bus.emit("progress:changed", { completed });
}
