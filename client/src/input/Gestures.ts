import Phaser from "phaser";

type Pointer = Phaser.Input.Pointer;

/** What a scene does with the gestures. Every handler is optional. */
export interface GestureHandlers {
  /** Return true to take the single-pointer event yourself (the placement ghost does). */
  claim?(p: Pointer, phase: "down" | "move" | "up"): boolean;
  tap?(p: Pointer): void;
  longPress?(p: Pointer): void;
  rightClick?(p: Pointer): void;
  panStart?(): void;
  pan?(dx: number, dy: number): void;
  panEnd?(): void;
  /** `ratio` = finger distance now / last call; `mid` = midpoint in screen px. */
  pinch?(ratio: number, mid: { x: number; y: number }): void;
  pinchEnd?(): void;
  wheel?(deltaY: number, p: Pointer): void;
}

export interface GestureOpts { longPressMs?: number; slop?: number }

interface Press { id: number; x: number; y: number; moved: boolean; timer: number | null }

/** One pointer: tap / long press / mouse drag-pan / right click. Two pointers: pan + pinch.
 *  Shared by the Room and Map scenes; needs `input.activePointers >= 2` in the game config. */
export class Gestures {
  private press: Press | null = null;
  private down = new Map<number, { x: number; y: number }>();
  private pinching = false;
  private panning = false;
  private last = { x: 0, y: 0 };
  private lastDist = 0;
  private lastMid = { x: 0, y: 0 };
  private readonly longPressMs: number;
  private readonly slop: number;

  constructor(private scene: Phaser.Scene, private h: GestureHandlers, opts: GestureOpts = {}) {
    this.longPressMs = opts.longPressMs ?? 400;
    this.slop = opts.slop ?? 14;
    const input = scene.input;
    input.mouse?.disableContextMenu(); // right click is ours; also no iOS callout on long press
    input.on(Phaser.Input.Events.POINTER_DOWN, this.onDown);
    input.on(Phaser.Input.Events.POINTER_MOVE, this.onMove);
    input.on(Phaser.Input.Events.POINTER_UP, this.onUp);
    input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.onUp);
    input.on(Phaser.Input.Events.POINTER_WHEEL, this.onWheel);
  }

  destroy(): void {
    const input = this.scene.input;
    input.off(Phaser.Input.Events.POINTER_DOWN, this.onDown);
    input.off(Phaser.Input.Events.POINTER_MOVE, this.onMove);
    input.off(Phaser.Input.Events.POINTER_UP, this.onUp);
    input.off(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.onUp);
    input.off(Phaser.Input.Events.POINTER_WHEEL, this.onWheel);
    this.clearPress();
  }

  private clearPress(): void {
    if (this.press?.timer !== null && this.press?.timer !== undefined) clearTimeout(this.press.timer);
    this.press = null;
  }

  /** The two active pointers of a pinch, in screen px. */
  private pair(): [{ x: number; y: number }, { x: number; y: number }] | null {
    const ps = this.scene.input.manager.pointers.filter((p) => p.isDown && this.down.has(p.id));
    if (ps.length < 2) return null;
    return [{ x: ps[0].x, y: ps[0].y }, { x: ps[1].x, y: ps[1].y }];
  }

  private onDown = (p: Pointer): void => {
    if (this.h.claim?.(p, "down")) return;
    if (p.rightButtonDown()) { this.h.rightClick?.(p); return; }
    this.down.set(p.id, { x: p.x, y: p.y });
    if (this.down.size >= 2) {
      // second finger: a tap/long press is off the table, this is a pan/pinch
      this.clearPress();
      if (this.panning) { this.panning = false; this.h.panEnd?.(); }
      const pair = this.pair();
      if (pair) {
        this.pinching = true;
        this.lastDist = Phaser.Math.Distance.Between(pair[0].x, pair[0].y, pair[1].x, pair[1].y);
        this.lastMid = { x: (pair[0].x + pair[1].x) / 2, y: (pair[0].y + pair[1].y) / 2 };
        this.h.panStart?.();
      }
      return;
    }
    const press: Press = { id: p.id, x: p.x, y: p.y, moved: false, timer: null };
    press.timer = window.setTimeout(() => {
      if (this.press === press && !press.moved) {
        this.press = null;
        this.h.longPress?.(p);
      }
    }, this.longPressMs);
    this.press = press;
    this.last = { x: p.x, y: p.y };
  };

  private onMove = (p: Pointer): void => {
    if (this.h.claim?.(p, "move")) return;
    if (this.pinching) {
      const pair = this.pair();
      if (!pair) return;
      const mid = { x: (pair[0].x + pair[1].x) / 2, y: (pair[0].y + pair[1].y) / 2 };
      const dist = Phaser.Math.Distance.Between(pair[0].x, pair[0].y, pair[1].x, pair[1].y);
      this.h.pan?.(mid.x - this.lastMid.x, mid.y - this.lastMid.y);
      if (this.lastDist > 0 && dist > 0) this.h.pinch?.(dist / this.lastDist, mid);
      this.lastMid = mid;
      this.lastDist = dist;
      return;
    }
    if (!p.isDown) return;
    const press = this.press;
    if (press && press.id === p.id && !press.moved && Phaser.Math.Distance.Between(p.x, p.y, press.x, press.y) > this.slop) {
      press.moved = true; // no tap, no long press
      if (press.timer !== null) { clearTimeout(press.timer); press.timer = null; }
      if (!p.wasTouch) { this.panning = true; this.h.panStart?.(); } // mouse drag pans; a finger drag just cancels the tap
    }
    if (this.panning) {
      this.h.pan?.(p.x - this.last.x, p.y - this.last.y);
    }
    this.last = { x: p.x, y: p.y };
  };

  private onUp = (p: Pointer): void => {
    if (this.h.claim?.(p, "up")) return;
    this.down.delete(p.id);
    if (this.pinching) {
      if (this.down.size < 2) {
        this.pinching = false;
        this.down.clear(); // the finger still down must not turn into a tap
        this.h.pinchEnd?.();
        this.h.panEnd?.();
      }
      return;
    }
    const press = this.press;
    if (!press || press.id !== p.id) return;
    this.clearPress();
    if (this.panning) { this.panning = false; this.h.panEnd?.(); return; }
    if (!press.moved) this.h.tap?.(p);
  };

  private onWheel = (p: Pointer, _objs: unknown, _dx: number, dy: number): void => {
    this.h.wheel?.(dy, p);
  };
}
