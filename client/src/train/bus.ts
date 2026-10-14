/** Typed event bus of the train page (own instance; the room game's bus.ts is untouched). */

import type { Report } from "./api";

export interface TrainEvents {
  "scene:ready": { rooms: number };
  /** a room (or nothing) was tapped in the car; `door` when a door sprite was hit (edge key) */
  "room:tap": { room: string | null; door: string | null };
  "preview:grid": { on: boolean };
  /** the payload changed: every UI piece re-renders from tstate */
  "state:changed": Record<string, never>;
  /** scene: redraw hunters/fugitive/markers from the payload (after a state change, not during playback) */
  "scene:sync": Record<string, never>;
  /** scene: play this round's report; emits playback:done afterwards */
  "playback:start": { report: Report };
  "playback:done": { report: Report };
  /** HUD: centre the camera on my avatar (or the fugitive's) */
  "camera:home": Record<string, never>;
  /** fugitive picked a door for 문 잠금 / a room for 교란 (scene → UI highlight) */
  "pick:changed": Record<string, never>;
  toast: { text: string; ms?: number };
  /** round log: the history array changed */
  "history:changed": Record<string, never>;
  /** 건너뛰기: finish the running playback (and the queued ones) instantly */
  "playback:skip": Record<string, never>;
  /** 다시 보기: play this report again */
  "playback:replay": { report: Report };
  "orderbar:unfold": Record<string, never>;
  /** battery: low-FPS idle mode on/off (scene pauses/resumes its tweens) */
  throttle: { on: boolean };
}

type Handler<K extends keyof TrainEvents> = (payload: TrainEvents[K]) => void;

class Bus {
  private handlers = new Map<string, Set<(p: unknown) => void>>();

  on<K extends keyof TrainEvents>(type: K, fn: Handler<K>): () => void {
    let set = this.handlers.get(type);
    if (!set) this.handlers.set(type, (set = new Set()));
    set.add(fn as (p: unknown) => void);
    return () => set!.delete(fn as (p: unknown) => void);
  }

  emit<K extends keyof TrainEvents>(type: K, payload: TrainEvents[K]): void {
    this.handlers.get(type)?.forEach((fn) => fn(payload));
  }
}

export const tbus = new Bus();

export function toast(text: string, ms?: number): void {
  tbus.emit("toast", { text, ms });
}
