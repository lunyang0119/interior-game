/** Background music: one list per place (default / dock / field / room) and per period (day 08:00–18:00 KST,
 * night otherwise).
 *
 * Tracks come from /media/bgm.json (built by `preprocess.py media`): `{ "<place>": { "day": [...], "night": [...] } }`.
 * Scenes report where the player is via the `scene:changed` bus event (room → "room", map → "field",
 * dock → "dock"); a place without tracks of its own falls back to the default lists. Random order, no immediate
 * repeats. Playback can only start after a user gesture, so we wait for the first pointerdown/keydown. Mute is
 * remembered in localStorage.
 */

import { $ } from "../ui/hud";
import { bus } from "../bus";
import { onUnlock } from "./unlock";
import { assetUrl } from "../assets";

interface Track { file: string; title: string }
type Period = "day" | "night";
type Manifest = Record<string, Partial<Record<Period, Track[]>>>;
export type BgmScene = "room" | "map" | "dock";

const KEY_MUTED = "bgm_muted";
const VOLUME = 0.5;
const FADE_MS = 1000;
const CHECK_MS = 60_000;
const PLACE_OF: Record<BgmScene, string> = { room: "room", map: "field", dock: "dock" };

let manifest: Manifest = {};
let audio: HTMLAudioElement | null = null;
let place = "default";
let currentKey = ""; // identifies the list the queue was filled from
let queue: Track[] = [];
let lastFile = "";
let muted = false;
let started = false;
let fading = false;
const muteListeners = new Set<(muted: boolean) => void>();

/** One mute switch for music and sound effects (the 🔊 button). */
export function isMuted(): boolean {
  return muted;
}

export function onMuteChange(fn: (muted: boolean) => void): () => void {
  muteListeners.add(fn);
  return () => muteListeners.delete(fn);
}

function forcedPeriod(): Period | null {
  const q = new URLSearchParams(location.search).get("bgm");
  return q === "day" || q === "night" ? q : null;
}

export function period(now = new Date()): Period {
  const forced = forcedPeriod();
  if (forced) return forced;
  const hour = Number(new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Seoul", hour: "numeric", hour12: false }).format(now));
  return hour >= 8 && hour < 18 ? "day" : "night";
}

/** Tracks for a place and period: own period → own other period → default period → default other period. */
function resolve(loc: string, p: Period): Track[] {
  const other: Period = p === "day" ? "night" : "day";
  const own = manifest[loc], def = manifest.default;
  for (const l of [own?.[p], own?.[other], def?.[p], def?.[other]]) if (l && l.length) return l;
  return [];
}

function listKey(tracks: Track[]): string {
  return tracks.map((t) => t.file).join("|");
}

/** Called on every scene change: switch lists (with a fade) only when the new place plays a different list. */
export function setBgmScene(kind: BgmScene): void {
  const loc = PLACE_OF[kind];
  if (loc === place) return;
  place = loc;
  if (audio && started && !muted && listKey(resolve(place, period())) !== currentKey) fadeOutThen(next);
}

function shuffled(tracks: Track[]): Track[] {
  const out = [...tracks];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  // avoid playing the same track twice in a row across queue refills
  if (out.length > 1 && out[0].file === lastFile) out.push(out.shift()!);
  return out;
}

function next(): void {
  if (!audio) return;
  const list = resolve(place, period());
  const key = listKey(list);
  if (key !== currentKey || queue.length === 0) {
    currentKey = key;
    queue = shuffled(list);
  }
  const t = queue.shift();
  if (!t) return;
  lastFile = t.file;
  audio.src = `/media/bgm/${t.file}`;
  audio.volume = muted ? 0 : VOLUME;
  audio.play().catch(() => { /* blocked until a gesture; start() retries */ });
}

function fadeOutThen(fn: () => void): void {
  if (fading) return; // the running fade ends in next(), which re-reads place/period
  if (!audio || audio.paused || muted) { fn(); return; }
  const a = audio;
  const start = performance.now();
  const from = a.volume;
  fading = true;
  const tick = () => {
    const k = Math.min(1, (performance.now() - start) / FADE_MS);
    a.volume = from * (1 - k);
    if (k < 1) requestAnimationFrame(tick); else { fading = false; fn(); }
  };
  requestAnimationFrame(tick);
}

function start(): void {
  if (started || !audio) return;
  started = true;
  if (!muted) next();
}

function renderButton(): void {
  const b = document.getElementById("btn-bgm");
  if (b) { b.textContent = muted ? "🔇" : "🔊"; b.title = muted ? "소리 켜기" : "소리 끄기 (음악·효과음)"; }
}

export function toggleMute(): void {
  muted = !muted;
  try { localStorage.setItem(KEY_MUTED, muted ? "1" : "0"); } catch { /* ignore */ }
  renderButton();
  for (const fn of muteListeners) fn(muted);
  if (!audio) return;
  if (muted) {
    audio.pause();
  } else {
    started = true;
    // resume the paused track only if it still belongs to the current place/period
    if (audio.src && audio.currentTime > 0 && listKey(resolve(place, period())) === currentKey) {
      audio.volume = VOLUME;
      void audio.play().catch(() => undefined);
    } else next();
  }
}

function hasTracks(m: Manifest): boolean {
  return Object.values(m).some((lists) => (lists.day?.length ?? 0) + (lists.night?.length ?? 0) > 0);
}

export async function initBgm(): Promise<void> {
  try { muted = localStorage.getItem(KEY_MUTED) === "1"; } catch { /* ignore */ }
  renderButton();
  $("btn-bgm").addEventListener("click", (e) => { e.stopPropagation(); toggleMute(); });
  bus.on("scene:changed", ({ scene }) => setBgmScene(scene));
  try {
    const res = await fetch(assetUrl("/media/bgm.json"));
    if (!res.ok) return;
    manifest = await res.json();
  } catch {
    return;
  }
  if (!manifest || typeof manifest !== "object" || !hasTracks(manifest)) return;

  audio = new Audio();
  audio.preload = "none";
  audio.volume = VOLUME;
  audio.addEventListener("ended", next);
  audio.addEventListener("error", () => { if (started && !muted) next(); });

  onUnlock(start);

  // switch lists when the KST period changes while a track is playing
  window.setInterval(() => {
    if (!audio || muted || !started) return;
    if (listKey(resolve(place, period())) !== currentKey) fadeOutThen(next);
  }, CHECK_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && audio && started && !muted && audio.paused && audio.src) {
      void audio.play().catch(() => undefined);
    }
  });
}
