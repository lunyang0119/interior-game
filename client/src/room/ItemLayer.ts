import Phaser from "phaser";
import { Z_HUNG, Z_HUNG_PAPER, Z_SCALE, canHang, collisionLayer, isFloorPaper, onWall, widthOf, type Catalog, type Item, type Layer, type RoomItem } from "../catalog";
import { depthOf, sortRowFor } from "./depth";
import { CELL } from "./grid";
import { footprintOf } from "./rules";
import { buildOccupancy } from "./walk";

export const ATLAS = "interiors";

export type ItemSprite = Phaser.GameObjects.Image | Phaser.GameObjects.TileSprite | Phaser.GameObjects.Container;
/** `shape`: what the sprite was built for (wallpaper: anchor + span); a change rebuilds it. */
interface Entry { row: RoomItem; sprite: ItemSprite; shape: string }

/** A wallpaper pasted on the floor rows: its anchor and footprint (paperCells: one painted run per column). */
export interface Pasted { x: number; y: number; cells: [number, number][] }

/** Wallpaper repeats its frame horizontally across the chosen span (pasted on the floor rows: one strip per
 *  column, see makePaperStrips); everything else is a plain image. */
export function makeItemSprite(scene: Phaser.Scene, it: Item | undefined, span?: number | null, pasted?: Pasted | null): ItemSprite {
  if (it?.layer === "wallpaper") {
    if (pasted) return makePaperStrips(scene, it, pasted);
    const frame = scene.textures.getFrame(ATLAS, it.sprite);
    return scene.add.tileSprite(0, 0, widthOf(it, span) * CELL, frame.height, ATLAS, it.sprite).setOrigin(0, onWall(it) ? 0 : 1);
  }
  return scene.add.image(0, 0, ATLAS, it?.sprite ?? "").setOrigin(0, onWall(it) ? 0 : 1);
}

/** Wallpaper on painted 벽지 칸: per column a 1-cell-wide strip as tall as that column's painted run, showing the
 *  texture's lower rows (the pattern stays continuous across columns). The container sits at the anchor cell. */
export function makePaperStrips(scene: Phaser.Scene, it: Item, p: Pasted): Phaser.GameObjects.Container {
  const full = scene.textures.getFrame(ATLAS, it.sprite).height;
  const runs = new Map<number, [number, number]>(); // column → [top, bottom]
  for (const [cx, cy] of p.cells) {
    const r = runs.get(cx);
    runs.set(cx, r ? [Math.min(r[0], cy), Math.max(r[1], cy)] : [cy, cy]);
  }
  const box = scene.add.container(0, 0);
  for (const [cx, [top, bottom]] of runs) {
    const h = Math.min((bottom - top + 1) * CELL, full);
    const strip = scene.add.tileSprite((cx - p.x) * CELL, (bottom + 1 - p.y) * CELL, CELL, h, ATLAS, it.sprite).setOrigin(0, 1);
    strip.tilePositionX = (cx - p.x) * CELL;
    strip.tilePositionY = full - h;
    box.add(strip);
  }
  return box;
}

/** setTint for any item sprite (a pasted wallpaper tints each strip). */
export function tintSprite(sprite: ItemSprite, color: number): void {
  if (sprite instanceof Phaser.GameObjects.Container) {
    for (const c of sprite.list) (c as Phaser.GameObjects.TileSprite).setTint(color);
  } else sprite.setTint(color);
}

/** Keeps one sprite per room item and diffs against server snapshots. */
export class ItemLayer {
  private entries = new Map<number, Entry>();
  rows: RoomItem[] = [];
  private hidden = new Set<number>();
  /** Cells covered by furniture avatars must walk around (see walk.ts). Rebuilt on every sync. */
  occupied: ReadonlySet<number> = new Set();

  constructor(private scene: Phaser.Scene, private cat: Catalog) {}

  sync(rows: RoomItem[]): void {
    this.rows = rows;
    const byUid = new Map(rows.map((r) => [r.uid, r]));
    for (const [uid, e] of this.entries) {
      if (!byUid.has(uid)) {
        e.sprite.destroy();
        this.entries.delete(uid);
      }
    }
    for (const row of rows) {
      const e = this.entries.get(row.uid);
      const it = this.cat.byId.get(row.item_id);
      const shape = it?.layer === "wallpaper" ? `${row.x},${row.y},${row.span ?? ""}` : "";
      if (e && e.shape === shape) {
        e.row = row;
        continue;
      }
      // new, or a wallpaper resized / moved (its strips depend on where it is pasted)
      e?.sprite.destroy();
      this.entries.set(row.uid, { row, sprite: makeItemSprite(this.scene, it, row.span, this.pasted(row)), shape });
    }
    for (const e of this.entries.values()) this.layout(e);
    this.occupied = buildOccupancy(this.cat, rows);
  }

  /** Footprint of a wallpaper pasted on this room's floor rows, else null. */
  private pasted(row: RoomItem): Pasted | null {
    const it = this.cat.byId.get(row.item_id);
    const room = row.room_id ? this.cat.rooms.get(row.room_id) : undefined;
    return isFloorPaper(it, room, row.y) ? { x: row.x, y: row.y, cells: footprintOf(this.cat, row) } : null;
  }

  /** Position + depth for a row, using the parent for stacked surface items and for wall decor hung on a partition. */
  placement(row: RoomItem): { x: number; y: number; depth: number } {
    const it = this.cat.byId.get(row.item_id);
    const h = it?.h ?? 1;
    let x = row.x * CELL;
    let y = (onWall(it) ? row.y * CELL : (row.y + h) * CELL) + (it?.offset_y ?? 0);
    let sortRow = sortRowFor(it && collisionLayer(it), row.y + h - 1);
    let z = Z_SCALE[it ? collisionLayer(it) : "furniture"];
    const parent = row.parent_uid != null ? (this.entries.get(row.parent_uid)?.row ?? this.rows.find((r) => r.uid === row.parent_uid)) : undefined;
    const pit = parent && this.cat.byId.get(parent.item_id);
    if (parent && pit && it?.layer === "surface_item") {
      sortRow = parent.y + pit.h - 1;
      y = (row.y + h) * CELL - pit.surface_offset_y + (it.offset_y ?? 0);
    } else if (parent && pit && canHang(it)) {
      // hung on a partition: sorted with the partition's feet, just above it
      sortRow = parent.y + pit.h - 1;
      z = Z_HUNG;
    } else if (it?.layer === "wallpaper" && row.room_id && isFloorPaper(it, this.cat.rooms.get(row.room_id), row.y)) {
      // pasted on 벽지 칸 (a partition's face): sorted with its lowest row, over the partition, under hung decor
      sortRow = Math.max(...footprintOf(this.cat, row).map((c) => c[1]));
      z = Z_HUNG_PAPER;
    }
    return { x, y, depth: depthOf(sortRow, z) + (row.uid % 97) / 100 };
  }

  private layout(e: Entry): void {
    const p = this.placement(e.row);
    e.sprite.setPosition(p.x, p.y).setDepth(p.depth).setVisible(!this.hidden.has(e.row.uid));
  }

  setHidden(uid: number, hidden: boolean): void {
    if (hidden) this.hidden.add(uid); else this.hidden.delete(uid);
    const e = this.entries.get(uid);
    if (e) this.layout(e);
  }

  /** Topmost item whose footprint covers the cell (surface items before furniture before floor).
   *  `layers` restricts which item layers count (e.g. ignore rugs so a tap on one still walks there). */
  itemAt(cx: number, cy: number, layers?: ReadonlySet<Layer>): RoomItem | null {
    let best: RoomItem | null = null;
    let bestZ = -1;
    for (const row of this.rows) {
      if (this.hidden.has(row.uid)) continue;
      if (layers && !layers.has(this.cat.byId.get(row.item_id)?.layer ?? "furniture")) continue;
      if (!footprintOf(this.cat, row).some((c) => c[0] === cx && c[1] === cy)) continue;
      if (row.z > bestZ) { best = row; bestZ = row.z; }
    }
    return best;
  }

  get(uid: number): RoomItem | undefined {
    return this.entries.get(uid)?.row;
  }

  destroy(): void {
    for (const e of this.entries.values()) e.sprite.destroy();
    this.entries.clear();
  }
}
