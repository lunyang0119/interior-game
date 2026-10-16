/** The fugitive's silhouette: a LimeZu avatar tinted black, with a glitch that grows with the trace tier (0→3)
 *  and peaks when traced/frozen ("과부하"). Hunter clients only ever see it where the server said so (glimpses,
 *  the capture room); the fugitive client sees it at the true position. */

import Phaser from "phaser";
import { Avatar } from "../../avatar/Avatar";
import { ensureAvatarTextures } from "../../avatar/AvatarLoader";
import { DEFAULT_LOOK, type AvatarLook, type Chars } from "../../catalog";
import { CELL } from "../../room/grid";
import { cellKey, pathToward, type Cell } from "../../room/walk";
import { nearestFree, type Layout } from "./layout";
import { walkGrid } from "./Hunters";

const SILHOUETTE: AvatarLook = { ...DEFAULT_LOOK, preset: 0, skin: 0, outfit: 0, hair: 0 };
const TINT = 0x000000;

export class FugitiveSprite {
  private avatar: Avatar | null = null;
  private ready: Promise<void>;
  private tier = 0;
  private frozen = false;
  private revealed = false;
  private glitch: Phaser.Time.TimerEvent | null = null;
  private baseX = 0;
  /** the open walk promise (see Hunters.walkTo: released by onArrive or by update() once the avatar stands still) */
  private waiting: (() => void) | null = null;

  constructor(private scene: Phaser.Scene, chars: Chars, private layout: Layout) {
    this.ready = ensureAvatarTextures(scene, SILHOUETTE, chars).then(() => {
      if (!this.scene.sys.isActive() && !this.scene.sys.isVisible()) return;
      this.avatar = new Avatar(scene, chars, SILHOUETTE, 0, 0, "", true);
      this.avatar.onStep = () => { /* facing follows the movement (see Hunters.ts) */ };
      this.avatar.setVisible(false);
      this.tint();
      this.glitch = scene.time.addEvent({ delay: 70, loop: true, callback: () => this.tick() });
    });
  }

  private sprites(): Phaser.GameObjects.Sprite[] {
    return (this.avatar?.list ?? []).filter((o): o is Phaser.GameObjects.Sprite => o instanceof Phaser.GameObjects.Sprite);
  }

  private tint(): void {
    for (const s of this.sprites()) {
      if (this.revealed) s.clearTint(); else s.setTintFill(TINT);
    }
  }

  /** The fugitive's standing spot in a room: right side, away from the hunters' slots. */
  cellFor(room: string): Cell {
    const b = this.layout.rooms.get(room);
    return b ? nearestFree(this.layout, b, { cx: b.x0 + b.w - 3, cy: b.y0 + b.h - 2 }) : { cx: 0, cy: 0 };
  }

  async show(room: string): Promise<void> {
    await this.ready;
    const a = this.avatar;
    if (!a) return;
    const c = this.cellFor(room);
    a.walkPath([]);
    a.setPosition((c.cx + 0.5) * CELL, (c.cy + 1) * CELL);
    a.update(0, 1_000_000);
    this.baseX = a.x;
    a.setVisible(true);
  }

  hide(): void {
    this.avatar?.setVisible(false);
  }

  get visible(): boolean { return this.avatar?.visible ?? false; }

  setTrace(tier: number, frozen: boolean): void {
    this.tier = tier;
    this.frozen = frozen;
  }

  /** Capture: the tint lifts and the glitch stops. */
  async reveal(): Promise<void> {
    await this.ready;
    this.revealed = true;
    this.tint();
    this.tier = 0;
    this.frozen = false;
    if (this.avatar) { this.avatar.setAlpha(1); this.avatar.x = this.baseX || this.avatar.x; }
  }

  /** Walk the silhouette along engine rooms (the fugitive view's playback of `fugitive_path`). */
  async walkRooms(rooms: string[]): Promise<void> {
    await this.ready;
    const a = this.avatar;
    if (!a || rooms.length === 0) return;
    await this.show(rooms[0]);
    const grid = walkGrid(this.layout);
    for (const r of rooms.slice(1)) {
      const path = pathToward(grid, a.footCell(), this.cellFor(r));
      if (!path.length) continue;
      await new Promise<void>((resolve) => {
        const done = () => {
          if (this.waiting === done) this.waiting = null;
          if (a.onArrive === done) a.onArrive = null;
          resolve();
        };
        this.waiting?.();
        this.waiting = done;
        a.onArrive = done;
        a.walkPath(path);
      });
      if (!this.avatar) return;   // destroyed mid-walk (scene restart)
    }
    this.baseX = a.x;
  }

  /** A hunter saw the intruder in `room`: flicker there for a moment (hunter clients). */
  async glimpse(room: string, ms = 1600): Promise<void> {
    await this.show(room);
    const a = this.avatar;
    if (!a) return;
    await new Promise<void>((resolve) => {
      this.scene.tweens.add({ targets: a, alpha: { from: 0.2, to: 1 }, duration: 160, yoyo: true, repeat: Math.floor(ms / 320), onComplete: () => resolve() });
    });
    a.setAlpha(1);
    this.hide();
  }

  private tick(): void {
    const a = this.avatar;
    if (!a || !a.visible || this.revealed) return;
    const level = this.frozen ? 4 : this.tier;
    if (level === 0) { a.setAlpha(1); return; }
    const amp = level * 1.5;
    const chance = 0.15 * level;
    if (Math.random() < chance) {
      a.setAlpha(Phaser.Math.FloatBetween(0.35, 1));
      const off = Phaser.Math.Between(-amp, amp);
      a.x = (a.walking ? a.x : this.baseX) + off;
      for (const s of this.sprites()) s.setTintFill(Math.random() < 0.3 ? 0x1a3aff : TINT);
      this.scene.time.delayedCall(40, () => {
        if (!a.walking) a.x = this.baseX;
        for (const s of this.sprites()) if (!this.revealed) s.setTintFill(TINT);
      });
    } else {
      a.setAlpha(1);
    }
  }

  update(time: number, delta: number): void {
    if (this.avatar) {
      const wasWalking = this.avatar.walking;
      this.avatar.update(time, delta);
      if (wasWalking && !this.avatar.walking) this.baseX = this.avatar.x;
      if (!this.avatar.walking) this.waiting?.();
    }
  }

  destroy(): void {
    this.glitch?.remove();
    this.avatar?.destroy();
    this.avatar = null;
    this.waiting?.();
  }

  /** Is `cell` inside the fugitive's current room? (used for door picking) */
  static cellInRoom(layout: Layout, room: string, c: Cell): boolean {
    const b = layout.rooms.get(room);
    return !!b && c.cx >= b.x0 && c.cx < b.x0 + b.w && c.cy >= b.y0 && c.cy < b.y0 + b.h && layout.walkable.has(cellKey(c.cx, c.cy));
  }
}
