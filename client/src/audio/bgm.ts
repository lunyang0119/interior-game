/** Background music: day list 08:00–18:00 KST, night list otherwise. Random order, no immediate repeats.
 *
 * Tracks come from /media/bgm.json (built by `preprocess.py media`). Playback can only start after a user
 * gesture, so we wait for the first pointerdown/keydown. Mute is remembered in localStorage.
 */

import { $ } from "../ui/hud";

interface Track { file: string; title: string }
type Period = "day" | "night";

const KEY_MUTED = "bgm_muted";
const VOLUME = 0.5;
const FADE_MS = 1000;
const CHECK_MS = 60_000;

let lists: Record<Period, Track[]> = { day: [], night: [] };
let audio: HTMLAudioElement | null = null;
let current: Period | null = null;
let queue: Track[] = [];
let lastFile = "";
let muted = false;
let started = false;

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
  const p = period();
  if (p !== current || queue.length === 0) {
    current = p;
    queue = shuffled(lists[p]);
  }
  const t = queue.shift();
  if (!t) return;
  lastFile = t.file;
  audio.src = `/media/bgm/${t.file}`;
  audio.volume = muted ? 0 : VOLUME;
  audio.play().catch(() => { /* blocked until a gesture; start() retries */ });
}

function fadeOutThen(fn: () => void): void {
  if (!audio || audio.paused || muted) { fn(); return; }
  const a = audio;
  const start = performance.now();
  const from = a.volume;
  const tick = () => {
    const k = Math.min(1, (performance.now() - start) / FADE_MS);
    a.volume = from * (1 - k);
    if (k < 1) requestAnimationFrame(tick); else fn();
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
  if (b) { b.textContent = muted ? "🔇" : "🔊"; b.title = muted ? "음악 켜기" : "음악 끄기"; }
}

export function toggleMute(): void {
  muted = !muted;
  try { localStorage.setItem(KEY_MUTED, muted ? "1" : "0"); } catch { /* ignore */ }
  renderButton();
  if (!audio) return;
  if (muted) {
    audio.pause();
  } else {
    started = true;
    if (audio.src && audio.currentTime > 0) { audio.volume = VOLUME; void audio.play().catch(() => undefined); }
    else next();
  }
}

export async function initBgm(): Promise<void> {
  try { muted = localStorage.getItem(KEY_MUTED) === "1"; } catch { /* ignore */ }
  renderButton();
  try {
    const res = await fetch("/media/bgm.json");
    if (!res.ok) return;
    lists = await res.json();
  } catch {
    return;
  }
  if (!lists.day.length && !lists.night.length) return;
  if (!lists.day.length) lists.day = lists.night;
  if (!lists.night.length) lists.night = lists.day;

  audio = new Audio();
  audio.preload = "none";
  audio.volume = VOLUME;
  audio.addEventListener("ended", next);
  audio.addEventListener("error", () => { if (started && !muted) next(); });

  const gesture = () => { start(); };
  document.addEventListener("pointerdown", gesture, { once: true });
  document.addEventListener("keydown", gesture, { once: true });
  $("btn-bgm").addEventListener("click", (e) => { e.stopPropagation(); toggleMute(); });

  // switch lists when the KST period changes while a track is playing
  window.setInterval(() => {
    if (!audio || muted || !started) return;
    if (period() !== current) fadeOutThen(next);
  }, CHECK_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && audio && started && !muted && audio.paused && audio.src) {
      void audio.play().catch(() => undefined);
    }
  });
}
