/** Tonight's guests, shown as NPC avatars inside their guest unit (the room, or one of its zones).
 *
 * Client-only: the server only says how many guests a unit expects (`ComfortView.guests`, in state.comfort).
 * Every client draws the same guests because looks, spawn cells and speech lines come from a PRNG seeded with
 * the unit key + the KST guest day. Guests idle and wander a few cells inside their unit over the room's walk
 * grid (never through player furniture), never block the player and never make footsteps. Tapping one shows
 * a line chosen by the unit's comfort band.
 */

import type { ComfortView } from "../api";
import { Avatar, type Dir } from "../avatar/Avatar";
import { ensureAvatarTextures } from "../avatar/AvatarLoader";
import { toast } from "../bus";
import { hasTag, type AvatarLook, type Catalog, type Room, type RoomItem } from "../catalog";
import { CELL } from "../room/grid";
import { footprintOf } from "../room/rules";
import { pathToward, type Cell, type WalkGrid } from "../room/walk";
import { state } from "../state";

const MAX_PER_UNIT = 3;
const TAG_BED = "bed";
const GUEST_NAME = "손님";
const WANDER_RADIUS = 4; // cells
const IDLE_MIN_MS = 3000, IDLE_MAX_MS = 9000;
const WALK_CHANCE = 0.6; // else just turn around
const BED_CHANCE = 0.35; // of the walks, head for the bed
// guest day = KST day ending at checkout 09:00 (mirrors server guests.day_key)
const KST_OFFSET_H = 9, CHECKOUT_H = 9;

/** Speech lines by comfort band (score < 34 / < 67 / ≥ 67). */
const LINES: readonly (readonly string[])[] = [
  ["좀 썰렁하네요…", "가구가 더 있으면 좋겠어요.", "하룻밤만 묵고 갈게요.", "밤에 좀 춥더라고요."],
  ["편안하게 묵고 있어요.", "아침밥은 없나요?", "이 동네 조용해서 좋네요.", "침대가 꽤 푹신해요."],
  ["여기 정말 아늑해요!", "다음에 친구도 데려올게요.", "이렇게 예쁜 방은 처음이에요.", "하루 더 묵어도 될까요?"],
];

function bandOf(score: number): number {
  return score < 34 ? 0 : score < 67 ? 1 : 2;
}

/** Tiny string hash (FNV-1a) → mulberry32 PRNG. */
function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return h >>> 0;
}

function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function guestDay(now = Date.now()): number {
  return Math.floor((now / 1000 + (KST_OFFSET_H - CHECKOUT_H) * 3600) / 86400);
}

function lookFrom(rnd: () => number, cat: Catalog): AvatarLook {
  const look: AvatarLook = { preset: 0, skin: 0, eyes: 0, hair: 0, hair_color: 0, outfit: 0, acc: 0 };
  for (const layer of ["skin", "eyes", "hair", "outfit", "acc"] as const) {
    const count = cat.chars.layers[layer]?.count ?? 0;
    if (count > 0) look[layer] = Math.floor(rnd() * count);
  }
  return look;
}

const DIRS: Dir[] = ["right", "up", "left", "down"];

interface Guest {
  unit: string;
  idx: number;
  avatar: Avatar;
  rnd: () => number;
  grid: WalkGrid; // the room grid restricted to the unit's cells
  cells: Cell[]; // floor cells of the unit
  bedSpots: Cell[]; // cells on / next to a bed in the unit
  nextAt: number;
}

export class GuestNpcs {
  private guests: Guest[] = [];
  private gen = 0;
  private counts = ""; // last applied "unit=n" picture, to skip no-op rebuilds

  constructor(private scene: Phaser.Scene, private cat: Catalog, private room: Room,
              private walkGrid: () => WalkGrid, private items: () => RoomItem[]) {}

  /** Match the avatars to state.comfort. Same counts as before → keep the guests where they are (the walk
   *  grid may have changed, so guests standing in new furniture step out of it). */
  sync(): void {
    const wanted: [string, ComfortView][] = [];
    for (const [key, v] of Object.entries(state.comfort)) {
      if (v.room === this.room.id && v.guests > 0 && !v.skipped) wanted.push([key, v]);
    }
    const day = guestDay();
    const picture = `${day}|` + wanted.map(([k, v]) => `${k}=${Math.min(v.guests, MAX_PER_UNIT)}`).sort().join(",");
    if (picture === this.counts) { this.refreshGrids(); return; }
    this.counts = picture;
    this.clear();
    const gen = ++this.gen;
    for (const [key, v] of wanted) {
      for (let i = 0; i < Math.min(v.guests, MAX_PER_UNIT); i++) void this.spawn(gen, key, v, i, day);
    }
  }

  private unitCells(v: ComfortView): Cell[] {
    const z = v.zone ? this.room.zones?.find((q) => q.id === v.zone) : null;
    const x0 = z ? z.x : 0, x1 = z ? z.x + z.w : this.room.cols;
    const y0 = Math.max(z ? z.y : 0, this.room.wall_rows), y1 = z ? z.y + z.h : this.room.rows;
    const out: Cell[] = [];
    for (let cy = y0; cy < y1; cy++) for (let cx = x0; cx < x1; cx++) out.push({ cx, cy });
    return out;
  }

  private restrict(base: WalkGrid, cells: Cell[]): WalkGrid {
    const inside = new Set(cells.map((c) => c.cy * 10_000 + c.cx));
    return { cols: base.cols, rows: base.rows, isWalkable: (cx, cy) => inside.has(cy * 10_000 + cx) && base.isWalkable(cx, cy) };
  }

  /** Cells a guest may stand on that touch a `bed` item anchored in the unit (on it when the bed is a seed). */
  private bedSpots(grid: WalkGrid, cells: Cell[]): Cell[] {
    const inside = new Set(cells.map((c) => c.cy * 10_000 + c.cx));
    const spots = new Map<number, Cell>();
    for (const row of this.items()) {
      const it = this.cat.byId.get(row.item_id);
      if (!hasTag(it, TAG_BED) || !inside.has(row.y * 10_000 + row.x)) continue;
      for (const [x, y] of footprintOf(this.cat, row)) {
        for (const [dx, dy] of [[0, 0], [1, 0], [-1, 0], [0, 1], [0, -1]]) {
          const cx = x + dx, cy = y + dy;
          if (grid.isWalkable(cx, cy)) spots.set(cy * 10_000 + cx, { cx, cy });
        }
      }
    }
    return [...spots.values()];
  }

  private async spawn(gen: number, unit: string, v: ComfortView, idx: number, day: number): Promise<void> {
    const rnd = prng(hash(`${unit}#${day}#${idx}`));
    const look = lookFrom(rnd, this.cat);
    const cells = this.unitCells(v);
    const grid = this.restrict(this.walkGrid(), cells);
    const free = cells.filter((c) => grid.isWalkable(c.cx, c.cy));
    if (!free.length) return; // nowhere to stand (unit packed with furniture)
    const start = free[Math.floor(rnd() * free.length)];
    await ensureAvatarTextures(this.scene, look, this.cat.chars);
    if (gen !== this.gen) return; // destroy()/rebuild bumps gen; scene.isActive() is false while still creating
    const avatar = new Avatar(this.scene, this.cat.chars, look, start.cx, start.cy, GUEST_NAME);
    avatar.onStep = () => { /* facing is derived from movement; nothing is sent */ };
    avatar.face(DIRS[Math.floor(rnd() * DIRS.length)]);
    this.guests.push({
      unit, idx, avatar, rnd, grid, cells, bedSpots: this.bedSpots(grid, cells),
      nextAt: this.scene.time.now + IDLE_MIN_MS + rnd() * (IDLE_MAX_MS - IDLE_MIN_MS),
    });
  }

  /** Furniture moved: rebuild each guest's grid and bed spots; a guest now inside furniture steps aside. */
  private refreshGrids(): void {
    const base = this.walkGrid();
    for (const g of this.guests) {
      g.grid = this.restrict(base, g.cells);
      g.bedSpots = this.bedSpots(g.grid, g.cells);
      const c = g.avatar.footCell();
      if (g.avatar.walking || g.grid.isWalkable(c.cx, c.cy)) continue;
      const free = g.cells.filter((q) => g.grid.isWalkable(q.cx, q.cy));
      if (!free.length) continue;
      let best = free[0], bestD = Infinity;
      for (const q of free) {
        const d = Math.abs(q.cx - c.cx) + Math.abs(q.cy - c.cy);
        if (d < bestD) { bestD = d; best = q; }
      }
      g.avatar.setPosition((best.cx + 0.5) * CELL, (best.cy + 1) * CELL);
      g.avatar.update(0, 0);
    }
  }

  private wander(g: Guest, now: number): void {
    g.nextAt = now + IDLE_MIN_MS + g.rnd() * (IDLE_MAX_MS - IDLE_MIN_MS);
    if (g.rnd() >= WALK_CHANCE) { g.avatar.face(DIRS[Math.floor(g.rnd() * DIRS.length)]); return; }
    const from = g.avatar.footCell();
    let to: Cell | undefined;
    if (g.bedSpots.length && g.rnd() < BED_CHANCE) {
      to = g.bedSpots[Math.floor(g.rnd() * g.bedSpots.length)];
    } else {
      const near = g.cells.filter((c) => Math.abs(c.cx - from.cx) + Math.abs(c.cy - from.cy) <= WANDER_RADIUS
        && g.grid.isWalkable(c.cx, c.cy));
      if (near.length) to = near[Math.floor(g.rnd() * near.length)];
    }
    if (!to) return;
    const path = pathToward(g.grid, from, to);
    if (path.length) g.avatar.walkPath(path);
  }

  update(time: number, delta: number): void {
    const now = this.scene.time.now;
    for (const g of this.guests) {
      g.avatar.update(time, delta);
      if (!g.avatar.walking && now >= g.nextAt) this.wander(g, now);
    }
  }

  /** The guest drawn under a world position (the frontmost when several overlap). */
  guestAt(wx: number, wy: number): Guest | null {
    const { frameW, frameH } = this.cat.chars;
    let hit: Guest | null = null;
    for (const g of this.guests) {
      const a = g.avatar;
      if (wx < a.x - frameW / 2 || wx > a.x + frameW / 2 || wy < a.y - frameH || wy > a.y) continue;
      if (!hit || a.depth > hit.avatar.depth) hit = g;
    }
    return hit;
  }

  /** A plain tap on a guest: they say something about the stay. Returns false when no guest is there. */
  tap(wx: number, wy: number): boolean {
    const g = this.guestAt(wx, wy);
    if (!g) return false;
    const lines = LINES[bandOf(state.comfort[g.unit]?.score ?? 0)];
    toast(`${GUEST_NAME}: ${lines[(hash(g.unit) + g.idx) % lines.length]}`);
    return true;
  }

  private clear(): void {
    for (const g of this.guests) g.avatar.destroy();
    this.guests = [];
  }

  destroy(): void {
    this.gen++;
    this.clear();
    this.counts = "";
  }
}
