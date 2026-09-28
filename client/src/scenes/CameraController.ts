import Phaser from "phaser";
import { CELL } from "../room/grid";

/** Room / Map camera: the canvas is the whole window (Scale.RESIZE), the camera shows a window of the world.
 *
 * Zoom is an integer (crisp pixel art). The world is centred when it is smaller than the view on an axis and
 * clamped to its edges otherwise. Following is manual (Phaser's startFollow + setBounds left-aligns small
 * worlds). Pan gestures switch following off; the next `follow()` call switches it back on.
 *
 * Pointer positions: after a zoom change `pointer.worldX` is stale until the pointer moves, so scenes convert
 * with `screenToWorld(p.x, p.y)` instead. (The dock keeps a fractional zoom via `fitToView`.)
 */
export interface CameraOpts {
  worldW: number;
  worldH: number;
  /** Preferred zoom (Room.zoom); used when it is within one step of the automatic choice. */
  zoomHint?: number;
  minZoom?: number;
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
    if (!this.userZoomed) this.applyZoom(this.autoZoom());
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

  autoZoom(): number {
    const shortPx = Math.min(this.viewW, this.viewH);
    const auto = Phaser.Math.Clamp(Math.round(shortPx / (CELL * this.targetRows)), this.minZoom, this.maxZoom);
    const hint = this.zoomHint;
    if (hint && Math.abs(hint - auto) <= 1) return Phaser.Math.Clamp(Math.round(hint), this.minZoom, this.maxZoom);
    return auto;
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

  /** Set an integer zoom, keeping the world point under `anchor` (screen px) where it is. */
  setZoom(z: number, anchor?: { x: number; y: number }): void {
    const next = Phaser.Math.Clamp(Math.round(z), this.minZoom, this.maxZoom);
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
    const z = Phaser.Math.Clamp(this.zoom * ratio, this.minZoom * 0.8, this.maxZoom * 1.25);
    this.userZoomed = true;
    this.zoomTo(z, mid);
  }

  /** End of a pinch: snap to the nearest integer zoom. */
  pinchEnd(): void {
    this.zoomTo(Phaser.Math.Clamp(Math.round(this.zoom), this.minZoom, this.maxZoom), { x: this.viewW / 2, y: this.viewH / 2 });
    this.onZoom?.(this.zoom);
  }

  /** Once per frame: place the camera. Centred axes when the world fits, clamped to the edges otherwise. */
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
export function fitToView(scene: Phaser.Scene, w: number, h: number): () => void {
  const apply = () => {
    const z = Math.min(scene.scale.width / w, scene.scale.height / h);
    scene.cameras.main.setZoom(z).centerOn(w / 2, h / 2);
  };
  apply();
  scene.scale.on(Phaser.Scale.Events.RESIZE, apply);
  return () => scene.scale.off(Phaser.Scale.Events.RESIZE, apply);
}
