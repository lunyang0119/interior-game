/** Attention cues: a short SFX + best-effort vibration when a round opens, and the tab-title badge.
 *  Everything here must never throw (iOS has no vibrate; audio may still be locked). */

import { onUnlock } from "../audio/unlock";
import { assetUrl } from "../assets";
import { isMuted } from "./bgm";

const BASE_TITLE = document.title;
let cue: HTMLAudioElement | null = null;
let unlocked = false;

export function initCues(): void {
  onUnlock(() => { unlocked = true; });
  try {
    cue = new Audio(assetUrl("/media/sfx/sell.mp3"));   // placeholder chime from the room game's SFX
    cue.preload = "auto";
    cue.volume = 0.6;
  } catch { cue = null; }
}

/** "Your move": chime (after the audio unlock, unless muted) + vibrate where supported. */
export function roundCue(): void {
  try {
    if (cue && unlocked && !isMuted()) { cue.currentTime = 0; void cue.play().catch(() => undefined); }
  } catch { /* ignore */ }
  try {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") navigator.vibrate([120, 60, 120]);
  } catch { /* ignore */ }
}

/** Tab title badge: "● " while it is my turn (unsubmitted) or a result I have not seen is waiting. */
export function setTitleBadge(on: boolean, label = ""): void {
  const t = on ? `● ${label ? label + " · " : ""}${BASE_TITLE}` : BASE_TITLE;
  if (document.title !== t) document.title = t;
}
