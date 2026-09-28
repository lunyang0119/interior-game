import Phaser from "phaser";
import { Z_AVATAR, type AvatarLook, type Chars } from "../catalog";
import { depthOf } from "../room/depth";
import { CELL } from "../room/grid";
import type { Cell } from "../room/walk";
import { animKey, sheetsFor, texKey } from "./AvatarLoader";

const SPEED = 48; // px per second
const REMOTE_SPEED = 64;
const LABEL_DEPTH = 1_000_000; // always above furniture

/** Name-tag style from theme.css variables (data/ui_theme.json → "label"). */
function labelStyle(): { font: string; size: number; color: string; stroke: string; scale: number } {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  return {
    font: v("--label-font", '"Stardust"'),
    size: Number(v("--label-size", "16")) || 16,
    color: v("--label-color", "#ffffff"),
    stroke: v("--label-stroke", "#000000"),
    scale: Number(v("--label-scale", "0.5")) || 0.5,
  };
}

export type Dir = "right" | "up" | "left" | "down";

/** Layered character: sprites[0] drives the animation, the rest copy its frame every update.
 *  Walks along a queue of cells (see room/walk.ts); remote avatars chase the last position received. */
export class Avatar extends Phaser.GameObjects.Container {
  private sprites: Phaser.GameObjects.Sprite[] = [];
  private target: { x: number; y: number } | null = null;
  private path: { x: number; y: number }[] = [];
  dir: Dir = "down";
  moving = false;
  private speed: number;
  onArrive: (() => void) | null = null;
  onStep: ((x: number, y: number, dir: Dir, moving: boolean) => void) | null = null;
  /** Fired whenever the feet enter another cell (footsteps). Also for remote avatars. */
  onCell: ((cx: number, cy: number) => void) | null = null;
  private stepAcc = 0;
  private lastCell = { cx: -1, cy: -1 };
  private lastFrame: Phaser.Textures.Frame | null = null;
  private label: Phaser.GameObjects.Text;

  constructor(scene: Phaser.Scene, private chars: Chars, look: AvatarLook, cellX: number, cellY: number,
              name = "", remote = false) {
    super(scene, (cellX + 0.5) * CELL, (cellY + 1) * CELL);
    this.speed = remote ? REMOTE_SPEED : SPEED;
    scene.add.existing(this);
    // name tag lives outside the container so its depth is independent of the y-sort
    const st = labelStyle();
    this.label = scene.add.text(0, 0, name, {
      fontFamily: `${st.font}, sans-serif`, fontSize: `${st.size}px`, color: st.color,
      stroke: st.stroke, strokeThickness: 3, resolution: 2,
    }).setOrigin(0.5, 1).setScale(st.scale).setDepth(LABEL_DEPTH).setVisible(name !== "");
    this.setLook(look);
    this.refreshDepth();
    this.syncLabel();
    this.lastCell = this.footCell();
  }

  private syncLabel(): void {
    this.label.setPosition(Math.round(this.x), Math.round(this.y - this.chars.frameH - 1));
  }

  destroy(fromScene?: boolean): void {
    this.label.destroy();
    super.destroy(fromScene);
  }

  /** Requires textures to be loaded already (ensureAvatarTextures). */
  setLook(look: AvatarLook): void {
    for (const s of this.sprites) s.destroy();
    this.sprites = [];
    this.lastFrame = null;
    for (const { layer, idx } of sheetsFor(look, this.chars)) {
      const s = this.scene.add.sprite(0, 0, texKey(layer, idx)).setOrigin(0.5, 1);
      this.add(s);
      this.sprites.push(s);
    }
    this.playAnim();
  }

  get cellX(): number { return this.x / CELL; }
  get cellY(): number { return this.y / CELL; }
  /** The cell the feet are in (y is the bottom edge, so look half a cell up). */
  footCell(): Cell { return { cx: Math.floor(this.cellX), cy: Math.floor(this.cellY - 0.5) }; }
  get walking(): boolean { return this.target !== null; }
  /** Waypoints still queued after the current target. */
  get pending(): number { return this.path.length; }
  /** The cell of the last queued waypoint (or the current target). */
  targetCell(): Cell | null {
    const t = this.path.length ? this.path[this.path.length - 1] : this.target;
    return t ? { cx: Math.floor(t.x / CELL), cy: Math.floor(t.y / CELL) - 1 } : null;
  }
  /** Append a cell to the current walk (keyboard: keeps the run animation going between cells). */
  extend(c: Cell): void {
    const wp = { x: (c.cx + 0.5) * CELL, y: (c.cy + 1) * CELL };
    if (this.target) this.path.push(wp); else this.target = wp;
  }

  /** Walk along waypoints (each the centre-bottom of a cell). An empty path stops. */
  walkPath(cells: Cell[]): void {
    this.path = cells.map((c) => ({ x: (c.cx + 0.5) * CELL, y: (c.cy + 1) * CELL }));
    this.target = this.path.shift() ?? null;
  }

  /** Walk straight to one cell (no pathfinding). */
  walkToCell(cx: number, cy: number): void {
    this.walkPath([{ cx, cy }]);
  }

  /** Turn without moving (keyboard walking into a wall). */
  face(dir: Dir): void {
    if (this.dir === dir) return;
    this.dir = dir;
    this.playAnim();
  }

  /** Remote avatar: server sent a new position in cell units. */
  applyRemote(x: number, y: number, dir: string, moving: boolean): void {
    this.path = [];
    this.target = { x: x * CELL, y: y * CELL };
    if (dir === "right" || dir === "up" || dir === "left" || dir === "down") this.dir = dir;
    // stay in the run animation while the sender is still moving, even between packets
    this.moving = moving || this.distanceToTarget() > 1;
    this.playAnim();
  }

  private distanceToTarget(): number {
    return this.target ? Phaser.Math.Distance.Between(this.x, this.y, this.target.x, this.target.y) : 0;
  }

  update(_time: number, delta: number): void {
    const driver = this.sprites[0];
    if (driver && driver.frame !== this.lastFrame) { // copy the frame only when the animation advanced
      this.lastFrame = driver.frame;
      for (let i = 1; i < this.sprites.length; i++) this.sprites[i].setFrame(driver.frame.name);
    }

    if (!this.target) return;
    let budget = (this.speed * delta) / 1000;
    while (this.target && budget > 0) {
      const dx = this.target.x - this.x;
      const dy = this.target.y - this.y;
      const dist = Math.hypot(dx, dy);
      if (dist <= budget) {
        this.setPosition(this.target.x, this.target.y);
        budget -= dist;
        this.target = this.path.shift() ?? null;
        if (this.target) continue;
        if (this.moving) {
          this.moving = false;
          this.playAnim();
          this.onStep?.(this.cellX, this.cellY, this.dir, false);
          this.checkCell();
          this.onArrive?.();
        }
        break;
      }
      this.setPosition(this.x + (dx / dist) * budget, this.y + (dy / dist) * budget);
      budget = 0;
      if (this.onStep) {
        // local avatar: derive facing from movement and notify every ~200ms
        const nd: Dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
        if (nd !== this.dir || !this.moving) { this.dir = nd; this.moving = true; this.playAnim(); }
        this.stepAcc += delta;
        if (this.stepAcc >= 200) { this.stepAcc = 0; this.onStep(this.cellX, this.cellY, this.dir, true); }
      } else if (!this.moving) {
        this.moving = true;
        this.playAnim();
      }
    }
    this.checkCell();
    this.refreshDepth();
    this.syncLabel();
  }

  private checkCell(): void {
    const c = this.footCell();
    if (c.cx === this.lastCell.cx && c.cy === this.lastCell.cy) return;
    this.lastCell = c;
    this.onCell?.(c.cx, c.cy);
  }

  private refreshDepth(): void {
    this.setDepth(depthOf(Math.floor((this.y - 1) / CELL), Z_AVATAR));
  }

  private playAnim(): void {
    const anim = `${this.moving ? "run" : "idle"}_${this.dir}`;
    for (const s of this.sprites) {
      const key = animKey(s.texture.key, anim);
      if (this.scene.anims.exists(key)) s.play(key, true);
    }
  }
}
