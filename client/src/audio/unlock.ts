/** Browsers only let audio start after a user gesture. The first pointer/key event unlocks BGM and SFX together. */

const listeners = new Set<() => void>();
let unlocked = false;

export function isUnlocked(): boolean {
  return unlocked;
}

/** Run `fn` once audio may start (immediately if it already may). */
export function onUnlock(fn: () => void): void {
  if (unlocked) { fn(); return; }
  listeners.add(fn);
}

function fire(): void {
  if (unlocked) return;
  unlocked = true;
  for (const fn of listeners) fn();
  listeners.clear();
}

document.addEventListener("pointerdown", fire, { once: true });
document.addEventListener("keydown", fire, { once: true });
