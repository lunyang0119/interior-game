import Phaser from "phaser";
import { Z_AVATAR, type AvatarLook, type Chars } from "../catalog";
import { depthOf } from "../room/depth";
import { CELL } from "../room/grid";
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

/** Layered character: sprites[0] drives the animation, the rest copy its frame every update. */
export class Avatar extends Phaser.GameObjects.Container {
  private sprites: Phaser.GameObjects.Sprite[] = [];
  private target: { x: number; y: number } | null = null;
  dir: Dir = "down";
  moving = false;
  private speed: number;
  onArrive: (() => void) | null = null;
  onStep: ((x: number, y: number, dir: Dir, moving: boolean) => void) | null = null;
  private stepAcc = 0;
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

  /** Walk to the centre-bottom of a cell (local avatar). */
  walkToCell(cx: number, cy: number): void {
    this.target = { x: (cx + 0.5) * CELL, y: (cy + 1) * CELL };
  }

  /** Remote avatar: server sent a new position in cell units. */
  applyRemote(x: number, y: number, dir: string, moving: boolean): void {
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

    if (this.target) {
      const dx = this.target.x - this.x;
      const dy = this.target.y - this.y;
      const dist = Math.hypot(dx, dy);
      const step = (this.speed * delta) / 1000;
      if (dist <= step) {
        this.setPosition(this.target.x, this.target.y);
        this.target = null;
        if (this.moving) {
          this.moving = false;
          this.playAnim();
          this.onStep?.(this.cellX, this.cellY, this.dir, false);
          this.onArrive?.();
        }
      } else {
        this.setPosition(this.x + (dx / dist) * step, this.y + (dy / dist) * step);
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
      this.refreshDepth();
      this.syncLabel();
    }
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
