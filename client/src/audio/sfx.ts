/** Sound effects: short clips from /media/sfx/<kind>.mp3 (built by `preprocess.py media` from assets/sfx).
 *
 * Plain HTMLAudioElements (no Phaser sound manager anywhere in the client). One base element per kind is
 * created up front; overlapping plays clone it. Mute is shared with the BGM button; playback is unlocked by
 * the same first gesture (audio/unlock.ts).
 */

import type { StepKind, TileInfo } from "../catalog";
import { bus } from "../bus";
import { isMuted, onMuteChange } from "./bgm";
import { onUnlock } from "./unlock";
import { assetUrl } from "../assets";

/** Every sound the game plays, by the kind name in media/sfx.json. */
export const SFX = {
  step: { wood: "step_wood", tile: "step_tile", grass: "step_grass", water: "step_water" } as Record<Exclude<StepKind, "none">, string>,
  rod: "rod", // cast
  splash: "water", // bobber lands / bite / pull-up
  reel: "reel", // looping while holding
  sell: "sell", // sold or refunded an item
  meow: "cat", // the inn cat was petted (assets/sfx/<any>/cat_*.mp3 → media/sfx/cat.mp3; missing = silent)
  ocean: "ocean", // dock ambience: its files play back to back under the BGM while at the dock (setAmbientScene)
} as const;

export const SFX_VOL = { step: 0.35, ui: 0.6, reel: 0.4 };

const POOL_MAX = 4; // simultaneous plays per kind

export interface SfxHandle { stop(): void }

const base = new Map<string, HTMLAudioElement>(); // by file key: "cat", "cat_2", …
const variants = new Map<string, number>(); // kind → how many files (media/sfx.json "variants")
const pools = new Map<string, HTMLAudioElement[]>();
const loops = new Set<HTMLAudioElement>();
let unlocked = false;

/** `cat` with 3 files → media/sfx/cat.mp3, cat_2.mp3, cat_3.mp3 */
function fileKey(kind: string, n: number): string {
  return n <= 1 ? kind : `${kind}_${n}`;
}

export async function initSfx(): Promise<void> {
  // hooks first: a scene:changed (the #dock deep link) or unlock that arrives while sfx.json loads must not be lost
  onUnlock(() => { unlocked = true; if (ambientKind && !ambientEl) ambientNext(); });
  onMuteChange((m) => {
    if (m) { for (const l of loops) { l.pause(); loops.delete(l); } ambientStop(); }
    else if (ambientKind && !ambientEl) ambientNext();
  });
  bus.on("scene:changed", ({ scene }) => setAmbientScene(scene));
  document.addEventListener("visibilitychange", () => { if (!document.hidden && ambientEl?.paused) void ambientEl.play().catch(() => { ambientEl = null; }); });
  let kinds: string[] = [];
  let counts: Record<string, number> = {};
  try {
    const res = await fetch(assetUrl("/media/sfx.json"));
    if (res.ok) {
      const j = (await res.json()) as { kinds?: string[]; variants?: Record<string, number> };
      kinds = j.kinds ?? [];
      counts = j.variants ?? {};
    }
  } catch {
    return;
  }
  for (const k of kinds) {
    const n = Math.max(1, counts[k] ?? 1);
    variants.set(k, n);
    for (let i = 1; i <= n; i++) {
      const a = new Audio(`/media/sfx/${fileKey(k, i)}.mp3`);
      a.preload = "auto";
      base.set(fileKey(k, i), a);
    }
  }
  if (ambientKind && !ambientEl) ambientNext(); // the scene was already set while the list loaded
}

/** One of the kind's files at random (a kind with several variants sounds less repetitive). */
function take(kind: string): HTMLAudioElement | null {
  const n = variants.get(kind) ?? 1;
  const key = fileKey(kind, n > 1 ? 1 + Math.floor(Math.random() * n) : 1);
  const proto = base.get(key);
  if (!proto) return null;
  let pool = pools.get(key);
  if (!pool) pools.set(key, (pool = []));
  const idle = pool.find((a) => a.paused || a.ended);
  if (idle) return idle;
  if (pool.length >= POOL_MAX) return null;
  const a = proto.cloneNode() as HTMLAudioElement;
  pool.push(a);
  return a;
}

/** Play a kind once (or looped). Silently does nothing while muted, before the first gesture, or for unknown kinds. */
export function play(kind: string, opts: { volume?: number; loop?: boolean } = {}): SfxHandle | null {
  if (!unlocked || isMuted()) return null;
  const a = take(kind);
  if (!a) return null;
  a.loop = !!opts.loop;
  a.volume = Math.max(0, Math.min(1, opts.volume ?? 1));
  a.currentTime = 0;
  if (a.loop) loops.add(a);
  void a.play().catch(() => undefined);
  return { stop: () => { a.pause(); a.loop = false; loops.delete(a); } };
}

// ---------------------------------------------------------------- ambient loop (the dock's waves)

/** Which ambient kind plays in each scene; a kind with several files cycles through them without repeats. */
const AMBIENT: Partial<Record<"room" | "map" | "dock", string>> = { dock: SFX.ocean };
const AMBIENT_VOL = 0.4;

let ambientKind: string | null = null; // what the current scene wants (null = silence)
let ambientEl: HTMLAudioElement | null = null;
let ambientIdx = 0;

/** Play the next file of the ambient kind; when it ends, the next one follows (back-to-back, no gap on `ended`). */
function ambientNext(): void {
  if (!ambientKind || !unlocked || isMuted()) return;
  const n = variants.get(ambientKind) ?? 0;
  if (!n) return;
  ambientIdx = n > 1 ? (ambientIdx + 1 + Math.floor(Math.random() * (n - 1))) % n : 0; // never the same twice in a row
  const proto = base.get(fileKey(ambientKind, ambientIdx + 1));
  if (!proto) return;
  const a = proto.cloneNode() as HTMLAudioElement;
  a.volume = AMBIENT_VOL;
  a.addEventListener("ended", () => { if (ambientEl === a) { ambientEl = null; ambientNext(); } });
  ambientEl = a;
  void a.play().catch(() => { if (ambientEl === a) ambientEl = null; }); // a refused play must not block the next attempt
}

function ambientStop(): void {
  if (ambientEl) { ambientEl.pause(); ambientEl.src = ""; ambientEl = null; }
}

/** The scene changed: stop the old ambience, start the new one (if any). Safe before unlock — starts then. */
export function setAmbientScene(scene: "room" | "map" | "dock"): void {
  const kind = AMBIENT[scene] ?? null;
  if (kind === ambientKind && ambientEl) return;
  ambientStop();
  ambientKind = kind;
  ambientNext();
}

/** The footstep kind for a tile: its `step`, else the scene's default; "none" is silent. */
export function stepKindFor(meta: TileInfo | undefined, fallback: Exclude<StepKind, "none">): string | null {
  const k = meta?.step ?? fallback;
  return k === "none" ? null : SFX.step[k];
}

/** Rate-limits footsteps per avatar so a fast walk does not machine-gun. */
export class Footsteps {
  private last = new Map<string, number>();
  constructor(private minGapMs = 180) {}

  trigger(id: string, kind: string | null, volume: number): void {
    if (!kind || volume <= 0.01) return;
    const now = performance.now();
    if (now - (this.last.get(id) ?? -Infinity) < this.minGapMs) return;
    this.last.set(id, now);
    play(kind, { volume });
  }

  forget(id: string): void {
    this.last.delete(id);
  }
}
