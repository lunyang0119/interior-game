/** Train BGM by trace level: four phases driven by the PUBLIC trace value, so everyone hears the same escalation.
 *
 *  Placeholder tracks: picked out of the room game's /media/bgm.json lists (TRAIN_BGM.phases → place/period/index),
 *  or a direct `file` under /media/bgm/. Phase changes happen only when a round resolves (`setTrace` from
 *  round_resolved / a fresh state), never mid-round, with a short crossfade between two <audio> elements.
 *  Mute is the room game's switch (localStorage "bgm_muted") so the 🔊 chip here and the one on / agree.
 */

import { onUnlock } from "../audio/unlock";
import { assetUrl } from "../assets";

export interface PhasePick { place: string; period: "day" | "night"; index: number; file?: string }

/** ONE place to tune: thresholds are the lower bounds of phases 1..3 (phase 0 = below the first). */
export const TRAIN_BGM = {
  thresholds: [25, 50, 75],
  phases: [
    { place: "room", period: "day", index: 0 },     // 0–24: calm
    { place: "field", period: "day", index: 0 },    // 25–49
    { place: "default", period: "night", index: 0 }, // 50–74
    { place: "cave", period: "night", index: 0 },   // 75–100: the net closes
  ] as PhasePick[],
  volume: 0.45,
  fadeMs: 1400,
};

const KEY_MUTED = "bgm_muted";
type Manifest = Record<string, { day?: { file: string }[]; night?: { file: string }[] }>;

let manifest: Manifest | null = null;
let cur: HTMLAudioElement | null = null;
let phase = -1;
let muted = false;
let unlocked = false;
let wanted = -1;
const muteListeners = new Set<(m: boolean) => void>();

export function phaseOf(trace: number): number {
  let k = 0;
  for (const t of TRAIN_BGM.thresholds) if (trace >= t) k++;
  return k;
}

function fileFor(k: number): string | null {
  const p = TRAIN_BGM.phases[Math.min(k, TRAIN_BGM.phases.length - 1)];
  if (!p) return null;
  if (p.file) return p.file;
  const lists = manifest?.[p.place] ?? manifest?.default;
  const list = lists?.[p.period]?.length ? lists[p.period]! : (lists?.day?.length ? lists.day! : lists?.night ?? []);
  const all = list.length ? list : Object.values(manifest ?? {}).flatMap((l) => [...(l.day ?? []), ...(l.night ?? [])]);
  const t = all[p.index % Math.max(1, all.length)];
  return t ? t.file : null;
}

function fade(a: HTMLAudioElement, to: number, ms: number, then?: () => void): void {
  const from = a.volume;
  const t0 = performance.now();
  const tick = () => {
    const k = Math.min(1, (performance.now() - t0) / ms);
    a.volume = from + (to - from) * k;
    if (k < 1) requestAnimationFrame(tick); else then?.();
  };
  requestAnimationFrame(tick);
}

function swapTo(k: number): void {
  const file = fileFor(k);
  if (!file) return;
  const next = new Audio(assetUrl(`/media/bgm/${file}`));
  next.loop = true;
  next.volume = 0;
  const old = cur;
  cur = next;
  phase = k;
  void next.play().then(() => {
    fade(next, muted ? 0 : TRAIN_BGM.volume, TRAIN_BGM.fadeMs);
    if (old) fade(old, 0, TRAIN_BGM.fadeMs, () => { old.pause(); old.src = ""; });
  }).catch(() => { cur = old; phase = old ? phase : -1; });
}

/** Called when a round resolves (or on the first state): switch phase only if it changed. */
export function setTrace(trace: number): void {
  wanted = phaseOf(trace);
  if (!unlocked || !manifest) return;
  if (wanted !== phase) swapTo(wanted);
}

export function stop(): void {
  if (cur) { const a = cur; cur = null; phase = -1; fade(a, 0, 600, () => { a.pause(); a.src = ""; }); }
}

export function isMuted(): boolean { return muted; }
export function onMuteChange(fn: (m: boolean) => void): void { muteListeners.add(fn); }

export function toggleMute(): boolean {
  muted = !muted;
  try { localStorage.setItem(KEY_MUTED, muted ? "1" : "0"); } catch { /* ignore */ }
  if (cur) fade(cur, muted ? 0 : TRAIN_BGM.volume, 300);
  for (const fn of muteListeners) fn(muted);
  return muted;
}

export async function initTrainBgm(): Promise<void> {
  try { muted = localStorage.getItem(KEY_MUTED) === "1"; } catch { /* ignore */ }
  try {
    const res = await fetch(assetUrl("/media/bgm.json"));
    if (res.ok) manifest = (await res.json()) as Manifest;
  } catch { manifest = null; }
  onUnlock(() => { unlocked = true; if (wanted >= 0 && wanted !== phase) swapTo(wanted); });
  // iOS pauses <audio> in the background; resume the current phase when the tab comes back
  document.addEventListener("visibilitychange", () => { if (!document.hidden && cur?.paused && !muted) void cur.play().catch(() => undefined); });
}
