import Phaser from "phaser";
import { CELL } from "../room/grid";

/** Room / Map camera: the canvas is the whole window (Scale.RESIZE), the camera shows a window of the world.
 *
 * Zoom never drops below the "cover" zoom (the world fills the whole view, so no black margins); the automatic
 * and wheel zooms are integers (crisp pixel art), a pinch may leave any zoom in range and keeps it. The camera is
 * clamped to the world's edges (centred only when the world exactly fits an axis). Following is manual (Phaser's
 * startFollow + setBounds left-aligns small worlds). Pan gestures switch following off; the next `follow()` call
 * switches it back on.
 *
 * Pointer positions: after a zoom change `pointer.worldX` is stale until the pointer moves, so scenes convert
 * with `screenToWorld(p.x, p.y)` instead. (The dock keeps a fractional zoom via `fitToView`.)
 */
export interface CameraOpts {
  worldW: number;
  worldH: number;
  /** Preferred zoom (Room.zoom); used when it is within one step of the automatic choice. */
  zoomHint?: number;
  /** Lower bound for the zoom; raised to the cover zoom when the world would otherwise not fill the view. */
  minZoom?: number;
  /** Upper bound for the zoom (never below the effective minimum). */
  maxZoom?: number;
  /** How many cells the short axis of the screen should show. */
  targetRows?: number;
}

export class CameraController {
  private cam: Phaser.Cameras.Scene2D.Camera;
  private target: { x: number; y: number } | null = null;
  private center = { x: 0, y: 0 };
  private following = false;
  private userZoomed = false;
  private readonly minZoom: number;
  private readonly maxZoom: number;
  private readonly targetRows: number;
  private readonly zoomHint: number | undefined;
  zoom = 1;
  /** Called after every zoom change (the map refits its fixed backdrop here). */
  onZoom: ((zoom: number) => void) | null = null;
  private onResize = () => {
    this.applyZoom(this.userZoomed ? Phaser.Math.Clamp(this.zoom, this.lo, this.hi) : this.autoZoom());
    this.update();
    this.onZoom?.(this.zoom);
  };

  constructor(private scene: Phaser.Scene, private opts: CameraOpts) {
    this.cam = scene.cameras.main;
    this.minZoom = opts.minZoom ?? 2;
    this.maxZoom = opts.maxZoom ?? 4;
    this.targetRows = opts.targetRows ?? 13;
    this.zoomHint = opts.zoomHint;
    this.center = { x: opts.worldW / 2, y: opts.worldH / 2 };
    this.applyZoom(this.autoZoom());
    scene.scale.on(Phaser.Scale.Events.RESIZE, this.onResize);
    this.update();
  }

  get viewW(): number { return this.scene.scale.width; }
  get viewH(): number { return this.scene.scale.height; }

  /** Smallest zoom at which the world covers the whole view on both axes. */
  private coverZoom(): number {
    return Math.max(this.viewW / this.opts.worldW, this.viewH / this.opts.worldH);
  }

  /** Effective zoom range: [max(minZoom, cover), max(maxZoom, that)]. */
  private get lo(): number { return Math.max(this.minZoom, this.coverZoom()); }
  private get hi(): number { return Math.max(this.maxZoom, this.lo); }

  autoZoom(): number {
    const shortPx = Math.min(this.viewW, this.viewH);
    let auto = Phaser.Math.Clamp(Math.round(shortPx / (CELL * this.targetRows)), this.minZoom, this.maxZoom);
    const hint = this.zoomHint;
    if (hint && Math.abs(hint - auto) <= 1) auto = Phaser.Math.Clamp(Math.round(hint), this.minZoom, this.maxZoom);
    // an integer when one fills the view; otherwise the (fractional) cover zoom
    return Phaser.Math.Clamp(auto, this.lo, this.hi);
  }

  private applyZoom(z: number): void {
    this.zoom = z;
    this.cam.setZoom(z);
  }

  /** Follow a game object (its feet are at y; the view centres a little above them). */
  follow(target: { x: number; y: number } | null): void {
    this.target = target;
    this.following = target !== null;
    this.update();
  }

  /** Set an integer zoom (clamped to the effective range), keeping the world point under `anchor` (screen px) where it is. */
  setZoom(z: number, anchor?: { x: number; y: number }): void {
    const next = Phaser.Math.Clamp(Math.round(z), this.lo, this.hi);
    if (next === this.zoom) return;
    this.userZoomed = true;
    this.zoomTo(next, anchor);
    this.onZoom?.(this.zoom);
  }

  /** Any zoom (used mid-pinch); keeps the world point under `anchor` fixed. */
  private zoomTo(z: number, anchor?: { x: number; y: number }): void {
    if (anchor) {
      this.stopFollowing();
      const wp = this.screenToWorld(anchor.x, anchor.y);
      this.applyZoom(z);
      // world under anchor = center - view/(2z) + anchor/z  →  center = wp + view/(2z) - anchor/z
      this.center = { x: wp.x + this.viewW / (2 * z) - anchor.x / z, y: wp.y + this.viewH / (2 * z) - anchor.y / z };
    } else {
      this.applyZoom(z);
    }
    this.update();
  }

  wheel(deltaY: number, p: { x: number; y: number }): void {
    if (deltaY === 0) return;
    this.setZoom(this.zoom + (deltaY < 0 ? 1 : -1), p);
  }

  private stopFollowing(): void {
    if (!this.following) return;
    this.following = false;
    if (this.target) this.center = { x: this.target.x, y: this.target.y - CELL };
  }

  /** Drag pan in screen px. Switches following off until the next follow(). */
  panBy(dx: number, dy: number): void {
    this.stopFollowing();
    this.center = { x: this.center.x - dx / this.zoom, y: this.center.y - dy / this.zoom };
    this.update();
  }

  /** Live pinch: `ratio` is the change in finger distance since the last call. */
  pinch(ratio: number, mid: { x: number; y: number }): void {
    const z = Phaser.Math.Clamp(this.zoom * ratio, this.lo * 0.9, this.hi * 1.1); // a little rubber band past the ends
    this.userZoomed = true;
    this.zoomTo(z, mid);
  }

  /** End of a pinch: keep the pinched zoom (pulled back into range; snapped to an integer only when very close). */
  pinchEnd(): void {
    const near = Math.round(this.zoom);
    const z = Phaser.Math.Clamp(Math.abs(near - this.zoom) < 0.08 ? near : this.zoom, this.lo, this.hi);
    if (z !== this.zoom) this.zoomTo(z, { x: this.viewW / 2, y: this.viewH / 2 });
    this.onZoom?.(this.zoom);
  }

  /** Once per frame: place the camera. Clamped to the world's edges (centred when the world exactly fits an axis). */
  update(): void {
    if (this.following && this.target) this.center = { x: this.target.x, y: this.target.y - CELL };
    const z = this.zoom;
    const half = { x: this.viewW / (2 * z), y: this.viewH / (2 * z) };
    const cx = this.opts.worldW * z <= this.viewW ? this.opts.worldW / 2
      : Phaser.Math.Clamp(this.center.x, half.x, this.opts.worldW - half.x);
    const cy = this.opts.worldH * z <= this.viewH ? this.opts.worldH / 2
      : Phaser.Math.Clamp(this.center.y, half.y, this.opts.worldH - half.y);
    if (!this.following) this.center = { x: cx, y: cy };
    // keep world→screen on whole device pixels: the view's top-left must be a multiple of 1/zoom
    const sx = Math.round((cx - this.viewW / 2) * z) / z, sy = Math.round((cy - this.viewH / 2) * z) / z;
    this.cam.setScroll(sx, sy);
  }

  screenToWorld(sx: number, sy: number): { x: number; y: number } {
    const p = this.cam.getWorldPoint(sx, sy);
    return { x: p.x, y: p.y };
  }

  worldToScreen(wx: number, wy: number): { x: number; y: number } {
    const v = this.cam.worldView;
    return { x: (wx - v.x) * this.zoom, y: (wy - v.y) * this.zoom };
  }

  /** World → CSS pixels of the page (for DOM overlays like the context menu). */
  toClient(wx: number, wy: number): { x: number; y: number } {
    const rect = this.scene.game.canvas.getBoundingClientRect();
    const s = this.worldToScreen(wx, wy);
    const k = rect.width / this.viewW; // 1 under Scale.RESIZE, but stay correct if the canvas is CSS-scaled
    return { x: rect.left + s.x * k, y: rect.top + s.y * k };
  }

  destroy(): void {
    this.scene.scale.off(Phaser.Scale.Events.RESIZE, this.onResize);
  }
}

/** Fixed-size scenes (the dock): scale the whole layout to fit the window, letterboxed, fractional zoom. */
export interface FitOptions {
  /** `cover`: scale so the layout fills the window (cropping the long side) instead of letterboxing. */
  cover?: boolean;
  /** World point to keep in view when cropping (clamped so the camera never shows outside the layout). */
  focus?: { x: number; y: number };
}

export function fitToView(scene: Phaser.Scene, w: number, h: number, opts: FitOptions = {}): () => void {
  const apply = () => {
    const sx = scene.scale.width / w, sy = scene.scale.height / h;
    const z = opts.cover ? Math.max(sx, sy) : Math.min(sx, sy);
    const vw = scene.scale.width / z, vh = scene.scale.height / z;
    const f = opts.focus ?? { x: w / 2, y: h / 2 };
    const cx = vw >= w ? w / 2 : Phaser.Math.Clamp(f.x, vw / 2, w - vw / 2);
    const cy = vh >= h ? h / 2 : Phaser.Math.Clamp(f.y, vh / 2, h - vh / 2);
    scene.cameras.main.setZoom(z).centerOn(cx, cy);
  };
  apply();
  scene.scale.on(Phaser.Scale.Events.RESIZE, apply);
  return () => scene.scale.off(Phaser.Scale.Events.RESIZE, apply);
}
