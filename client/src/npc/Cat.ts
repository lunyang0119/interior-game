/** The inn cat: one NPC that wanders the inn's walkable cells and idles (sits, looks around, lies down).
 *
 * Client-only movement: every client sees its own cat walking its own way; only petting goes to the server
 * (`POST /api/cat/pet`), which keeps the per-day affection that feeds the inn's comfort score. The cat never
 * blocks anybody (it is not in the walk grid) and never makes footsteps. Tapping it meows, pets it and
 * pauses it for a moment. Frames come from `gen/cat/<variant>.png` (catalog.cat, built by preprocess build).
 */

import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { assetUrl } from "../assets";
import { play, SFX, SFX_VOL } from "../audio/sfx";
import { toast } from "../bus";
import { Z_AVATAR, type CatSpec, type Room } from "../catalog";
import { depthOf } from "../room/depth";
import { CELL } from "../room/grid";
import { pathToward, type Cell, type WalkGrid } from "../room/walk";

const SPEED = 28; // px per second (a stroll; avatars walk at 48)
const IDLE_MIN_MS = 2500, IDLE_MAX_MS = 7000;
const WANDER_RADIUS = 5; // cells
const WALK_CHANCE = 0.55; // else pick another idle pose
const PET_PAUSE_MS = 4000; // stays put after being petted
const Z_CAT = Z_AVATAR - 1; // under an avatar standing on the same row

type Dir = "down" | "right" | "up" | "left";
type Idle = "sit" | "look" | "lay";
const DIRS: Dir[] = ["down", "right", "up", "left"];
// what the cat does while idle: looking around loops, sitting/lying hold their last frame
const IDLE_WEIGHTS: [Idle, number][] = [["look", 0.5], ["sit", 0.3], ["lay", 0.2]];
const FRAME_RATE: Record<string, number> = { walk: 8, run: 10, look: 4, sit: 6, lay: 6 };
const LOOPS = new Set(["walk", "run", "look"]);

export function catTexKey(spec: CatSpec): string {
  return `cat_${spec.variant}`;
}

function registerAnims(scene: Phaser.Scene, spec: CatSpec): void {
  const tex = catTexKey(spec);
  for (const [name, [start, end]] of Object.entries(spec.anims)) {
    const key = `${tex}:${name}`;
    if (scene.anims.exists(key)) continue;
    const kind = name.split("_")[0];
    scene.anims.create({
      key,
      frames: scene.anims.generateFrameNumbers(tex, { start, end }),
      frameRate: FRAME_RATE[kind] ?? 6,
      repeat: LOOPS.has(kind) ? -1 : 0,
    });
  }
}

/** Loads the strip once per game (textures and anims are global) and resolves even when the file is missing. */
function ensureTexture(scene: Phaser.Scene, spec: CatSpec): Promise<boolean> {
  const key = catTexKey(spec);
  return new Promise((resolve) => {
    const finish = () => {
      const ok = scene.textures.exists(key);
      if (ok) registerAnims(scene, spec);
      resolve(ok);
    };
    if (scene.textures.exists(key)) { finish(); return; }
    scene.load.spritesheet(key, assetUrl(`/${spec.file}`), { frameWidth: spec.frameW, frameHeight: spec.frameH });
    scene.load.once(Phaser.Loader.Events.COMPLETE, finish);
    scene.load.start();
  });
}

export class InnCat {
  private sprite: Phaser.GameObjects.Sprite | null = null;
  private path: { x: number; y: number }[] = [];
  private target: { x: number; y: number } | null = null;
  private dir: Dir = "down";
  private nextAt = 0;
  private petting = false;
  private alive = true;

  constructor(private scene: Phaser.Scene, private spec: CatSpec, private room: Room, private walkGrid: () => WalkGrid) {}

  /** Loads the strip and puts the cat on a random walkable floor cell (nothing when there is none). */
  async spawn(): Promise<void> {
    const ok = await ensureTexture(this.scene, this.spec);
    // no scene.isActive() here: spawn() is called from create(), when the scene is still CREATING, and a cached
    // texture resolves right away — `alive` (cleared by destroy()) is the only guard that matters
    if (!ok || !this.alive) return;
    const free = this.freeCells();
    if (!free.length) return;
    const start = free[Math.floor(Math.random() * free.length)];
    this.sprite = this.scene.add.sprite((start.cx + 0.5) * CELL, (start.cy + 1) * CELL, catTexKey(this.spec)).setOrigin(0.5, 1);
    this.dir = DIRS[Math.floor(Math.random() * DIRS.length)];
    this.idle("look");
    this.nextAt = this.scene.time.now + IDLE_MIN_MS + Math.random() * (IDLE_MAX_MS - IDLE_MIN_MS);
    this.refreshDepth();
  }

  get x(): number { return this.sprite?.x ?? 0; }
  get y(): number { return this.sprite?.y ?? 0; }
  get walking(): boolean { return this.target !== null; }

  footCell(): Cell {
    return { cx: Math.floor(this.x / CELL), cy: Math.floor((this.y - 1) / CELL) };
  }

  private freeCells(): Cell[] {
    const grid = this.walkGrid();
    const out: Cell[] = [];
    for (let cy = this.room.wall_rows; cy < this.room.rows; cy++) {
      for (let cx = 0; cx < this.room.cols; cx++) if (grid.isWalkable(cx, cy)) out.push({ cx, cy });
    }
    return out;
  }

  private anim(name: string): void {
    if (!this.sprite) return;
    const key = `${catTexKey(this.spec)}:${name}`;
    if (!this.scene.anims.exists(key)) return; // a direction/section the build did not cut: keep the last pose
    if (this.sprite.anims.currentAnim?.key === key && this.sprite.anims.isPlaying) return;
    this.sprite.play(key);
  }

  private idle(kind?: Idle): void {
    if (!kind) {
      let r = Math.random();
      kind = IDLE_WEIGHTS[IDLE_WEIGHTS.length - 1][0];
      for (const [k, w] of IDLE_WEIGHTS) { if (r < w) { kind = k; break; } r -= w; }
    }
    this.anim(`${kind}_${this.dir}`);
  }

  /** Every few seconds: walk somewhere nearby, or settle into another pose. A cat left inside freshly placed
   *  furniture walks out to the nearest free cell first. */
  private wander(now: number): void {
    this.nextAt = now + IDLE_MIN_MS + Math.random() * (IDLE_MAX_MS - IDLE_MIN_MS);
    const grid = this.walkGrid();
    const from = this.footCell();
    let to: Cell | undefined;
    if (!grid.isWalkable(from.cx, from.cy)) {
      let bestD = Infinity;
      for (const c of this.freeCells()) {
        const d = Math.abs(c.cx - from.cx) + Math.abs(c.cy - from.cy);
        if (d < bestD) { bestD = d; to = c; }
      }
    } else if (Math.random() < WALK_CHANCE) {
      const near = this.freeCells().filter((c) => Math.abs(c.cx - from.cx) + Math.abs(c.cy - from.cy) <= WANDER_RADIUS);
      if (near.length) to = near[Math.floor(Math.random() * near.length)];
    } else {
      if (Math.random() < 0.5) this.dir = DIRS[Math.floor(Math.random() * DIRS.length)];
      this.idle();
      return;
    }
    if (!to) return;
    const path = pathToward(grid, from, to);
    if (!path.length) return;
    this.path = path.map((c) => ({ x: (c.cx + 0.5) * CELL, y: (c.cy + 1) * CELL }));
    this.target = this.path.shift() ?? null;
  }

  update(_time: number, delta: number): void {
    if (!this.sprite) return;
    const now = this.scene.time.now;
    if (!this.target) {
      if (now >= this.nextAt) this.wander(now);
      return;
    }
    let budget = (SPEED * delta) / 1000;
    while (this.target && budget > 0) {
      const dx = this.target.x - this.sprite.x, dy = this.target.y - this.sprite.y;
      const dist = Math.hypot(dx, dy);
      if (dist <= budget) {
        this.sprite.setPosition(this.target.x, this.target.y);
        budget -= dist;
        this.target = this.path.shift() ?? null;
        if (!this.target) this.idle();
        continue;
      }
      this.sprite.setPosition(this.sprite.x + (dx / dist) * budget, this.sprite.y + (dy / dist) * budget);
      budget = 0;
      const nd: Dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
      this.dir = nd;
      this.anim(`walk_${nd}`);
    }
    this.refreshDepth();
  }

  private refreshDepth(): void {
    this.sprite?.setDepth(depthOf(Math.floor((this.y - 1) / CELL), Z_CAT));
  }

  /** Is a world position on the cat's frame? */
  hits(wx: number, wy: number): boolean {
    if (!this.sprite) return false;
    const { frameW, frameH } = this.spec;
    return wx >= this.x - frameW / 2 && wx <= this.x + frameW / 2 && wy >= this.y - frameH && wy <= this.y;
  }

  /** A plain tap on the cat: meow, stop for a moment and tell the server. Returns false when the tap missed. */
  tap(wx: number, wy: number): boolean {
    if (!this.hits(wx, wy)) return false;
    play(SFX.meow, { volume: SFX_VOL.ui });
    this.path = [];
    this.target = null;
    this.dir = "down";
    this.idle("look");
    this.nextAt = this.scene.time.now + PET_PAUSE_MS;
    if (this.petting) return true;
    this.petting = true;
    api.catPet()
      .then((r) => toast(r.first_today ? "고양이가 골골거려요" : "야옹"))
      .catch((e) => toast(e instanceof ApiError ? msgFor(e.code) : String(e)))
      .finally(() => { this.petting = false; });
    return true;
  }

  destroy(): void {
    this.alive = false;
    this.sprite?.destroy();
    this.sprite = null;
    this.target = null;
    this.path = [];
  }
}
