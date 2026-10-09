/** Sound effects: short clips from /media/sfx/<kind>.mp3 (built by `preprocess.py media` from assets/sfx).
 *
 * Plain HTMLAudioElements (no Phaser sound manager anywhere in the client). One base element per kind is
 * created up front; overlapping plays clone it. Mute is shared with the BGM button; playback is unlocked by
 * the same first gesture (audio/unlock.ts).
 */

import type { StepKind, TileInfo } from "../catalog";
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
} as const;

export const SFX_VOL = { step: 0.35, ui: 0.6, reel: 0.4 };

const POOL_MAX = 4; // simultaneous plays per kind

export interface SfxHandle { stop(): void }

const base = new Map<string, HTMLAudioElement>();
const pools = new Map<string, HTMLAudioElement[]>();
const loops = new Set<HTMLAudioElement>();
let unlocked = false;

export async function initSfx(): Promise<void> {
  let kinds: string[] = [];
  try {
    const res = await fetch(assetUrl("/media/sfx.json"));
    if (res.ok) kinds = ((await res.json()) as { kinds?: string[] }).kinds ?? [];
  } catch {
    return;
  }
  for (const k of kinds) {
    const a = new Audio(`/media/sfx/${k}.mp3`);
    a.preload = "auto";
    base.set(k, a);
  }
  onUnlock(() => { unlocked = true; });
  onMuteChange((m) => { if (m) for (const l of loops) { l.pause(); loops.delete(l); } });
}

function take(kind: string): HTMLAudioElement | null {
  const proto = base.get(kind);
  if (!proto) return null;
  let pool = pools.get(kind);
  if (!pool) pools.set(kind, (pool = []));
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
