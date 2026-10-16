/** Hunter avatars standing in their rooms; walked along the layout's walk grid during playback. */

import Phaser from "phaser";
import { Avatar } from "../../avatar/Avatar";
import { ensureAvatarTextures } from "../../avatar/AvatarLoader";
import { DEFAULT_LOOK, type AvatarLook, type Chars } from "../../catalog";
import { CELL } from "../../room/grid";
import { label } from "../state";
import { cellKey, pathToward, type Cell, type WalkGrid } from "../../room/walk";
import { standCell, type Door, type Layout } from "./layout";

export function walkGrid(layout: Layout): WalkGrid {
  return { cols: layout.cols, rows: layout.rows, isWalkable: (cx, cy) => layout.walkable.has(cellKey(cx, cy)) };
}

export class Hunters {
  readonly avatars = new Map<string, Avatar>();
  private order: string[] = [];
  private grid: WalkGrid;

  constructor(private scene: Phaser.Scene, private chars: Chars, private layout: Layout) {
    this.grid = walkGrid(layout);
  }

  slot(id: string): number {
    const i = this.order.indexOf(id);
    return i < 0 ? 0 : i;
  }

  cellFor(id: string, room: string): Cell {
    const b = this.layout.rooms.get(room);
    return b ? standCell(this.layout, b, this.slot(id)) : { cx: 0, cy: 0 };
  }

  /** Create/destroy avatars to match `ids` (in tag order) and stand them in `rooms` (unless `keepPositions`). */
  async sync(ids: string[], looks: Record<string, AvatarLook>, rooms: Record<string, string>, keepPositions = false): Promise<void> {
    this.order = ids;
    for (const id of [...this.avatars.keys()]) if (!ids.includes(id)) { this.avatars.get(id)!.destroy(); this.avatars.delete(id); }
    for (const id of ids) {
      const look = looks[id] ?? DEFAULT_LOOK;
      let a = this.avatars.get(id);
      if (!a) {
        await ensureAvatarTextures(this.scene, look, this.chars);
        if (this.avatars.has(id) || !this.order.includes(id)) continue; // raced with another sync
        const c = this.cellFor(id, rooms[id]);
        a = new Avatar(this.scene, this.chars, look, c.cx, c.cy, label(id), true);
        // Avatar only derives the facing from the movement when an onStep handler exists (the "local" mode);
        // a no-op handler makes a walking hunter face the way it goes instead of sliding sideways
        a.onStep = () => { /* facing only */ };
        a.update(0, 1_000_000);
        this.avatars.set(id, a);
      } else if (!keepPositions && rooms[id]) {
        this.place(a, this.cellFor(id, rooms[id]));
      }
    }
  }

  private place(a: Avatar, c: Cell): void {
    a.walkPath([]);
    a.setPosition((c.cx + 0.5) * CELL, (c.cy + 1) * CELL);
    a.update(0, 1_000_000);
  }

  /** Teleport everyone to `rooms` (start of a playback: the round's `from` rooms). */
  placeAll(rooms: Record<string, string>): void {
    for (const [id, a] of this.avatars) if (rooms[id]) this.place(a, this.cellFor(id, rooms[id]));
  }

  position(id: string): { x: number; y: number } | null {
    const a = this.avatars.get(id);
    return a ? { x: a.x, y: a.y } : null;
  }

  private walkTo(a: Avatar, to: Cell): Promise<void> {
    const path = pathToward(this.grid, a.footCell(), to);
    if (!path.length) return Promise.resolve();
    return new Promise((resolve) => {
      a.onArrive = () => { a.onArrive = null; resolve(); };
      a.walkPath(path);
    });
  }

  /** Walk `id` from its current spot into `room`. */
  async walk(id: string, room: string): Promise<void> {
    const a = this.avatars.get(id);
    if (!a) return;
    await this.walkTo(a, this.cellFor(id, room));
  }

  /** Walk up to the locked door (own side), bump, and return to the stand cell. */
  async bump(id: string, room: string, door: Door): Promise<void> {
    const a = this.avatars.get(id);
    if (!a) return;
    const mine = door.a === room ? door.cells[0] : door.cells[door.cells.length - 1];
    // the cell just before the door on this room's side
    const path = pathToward(this.grid, a.footCell(), mine);
    const stop = path.length >= 2 ? path[path.length - 2] : null;
    if (stop) await this.walkTo(a, stop);
    await new Promise<void>((resolve) => {
      const dx = Math.sign(mine.cx - a.footCell().cx) * 5, dy = Math.sign(mine.cy - a.footCell().cy) * 5;
      this.scene.tweens.add({ targets: a, x: a.x + dx, y: a.y + dy, duration: 120, yoyo: true, repeat: 1, onComplete: () => resolve() });
    });
    await this.walkTo(a, this.cellFor(id, room));
  }

  update(time: number, delta: number): void {
    for (const a of this.avatars.values()) a.update(time, delta);
  }

  destroy(): void {
    for (const a of this.avatars.values()) a.destroy();
    this.avatars.clear();
  }
}
