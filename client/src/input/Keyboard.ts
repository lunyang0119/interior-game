import type { Dir } from "../avatar/Avatar";

/** Desktop walking keys. Plain DOM listeners (Phaser's keyboard plugin captures keys globally and would
 *  eat the letters typed into the nickname box). `held()` answers the direction currently pressed, most
 *  recent key first, or null while a text field has focus. */
const KEY_DIRS: Record<string, Dir> = {
  KeyW: "up", ArrowUp: "up",
  KeyS: "down", ArrowDown: "down",
  KeyA: "left", ArrowLeft: "left",
  KeyD: "right", ArrowRight: "right",
};

const DELTA: Record<Dir, [number, number]> = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

export function dirDelta(d: Dir): [number, number] {
  return DELTA[d];
}

function typing(): boolean {
  const el = document.activeElement;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || (el as HTMLElement).isContentEditable);
}

export class WalkKeys {
  private order: Dir[] = []; // pressed keys, most recent last
  private onKeyDown = (e: KeyboardEvent) => {
    const d = KEY_DIRS[e.code];
    if (!d || typing() || e.ctrlKey || e.metaKey || e.altKey) return;
    e.preventDefault();
    if (!this.order.includes(d)) this.order.push(d);
  };
  private onKeyUp = (e: KeyboardEvent) => {
    const d = KEY_DIRS[e.code];
    if (d) this.order = this.order.filter((x) => x !== d);
  };
  private onBlur = () => { this.order = []; };

  constructor() {
    window.addEventListener("keydown", this.onKeyDown);
    window.addEventListener("keyup", this.onKeyUp);
    window.addEventListener("blur", this.onBlur);
  }

  held(): Dir | null {
    if (typing()) return null;
    return this.order.length ? this.order[this.order.length - 1] : null;
  }

  destroy(): void {
    window.removeEventListener("keydown", this.onKeyDown);
    window.removeEventListener("keyup", this.onKeyUp);
    window.removeEventListener("blur", this.onBlur);
    this.order = [];
  }
}
