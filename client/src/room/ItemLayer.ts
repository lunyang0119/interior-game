import Phaser from "phaser";
import { Z_SCALE, widthOf, type Catalog, type Item, type Layer, type RoomItem } from "../catalog";
import { depthOf, isWallLayer, sortRowFor } from "./depth";
import { CELL } from "./grid";
import { footprintOf } from "./rules";

export const ATLAS = "interiors";

type ItemSprite = Phaser.GameObjects.Image | Phaser.GameObjects.TileSprite;
interface Entry { row: RoomItem; sprite: ItemSprite }

/** Wallpaper repeats its frame horizontally across the chosen span; everything else is a plain image. */
export function makeItemSprite(scene: Phaser.Scene, it: Item | undefined, span?: number | null): ItemSprite {
  if (it?.layer === "wallpaper") {
    const frame = scene.textures.getFrame(ATLAS, it.sprite);
    return scene.add.tileSprite(0, 0, widthOf(it, span) * CELL, frame.height, ATLAS, it.sprite).setOrigin(0, 0);
  }
  return scene.add.image(0, 0, ATLAS, it?.sprite ?? "").setOrigin(0, isWallLayer(it?.layer) ? 0 : 1);
}

/** Keeps one sprite per room item and diffs against server snapshots. */
export class ItemLayer {
  private entries = new Map<number, Entry>();
  rows: RoomItem[] = [];
  private hidden = new Set<number>();

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
      if (!e) {
        this.entries.set(row.uid, { row, sprite: makeItemSprite(this.scene, it, row.span) });
      } else {
        if (it && (e.row.span ?? null) !== (row.span ?? null) && "setSize" in e.sprite) {
          e.sprite.setSize(widthOf(it, row.span) * CELL, e.sprite.height); // wallpaper resized while moving
        }
        e.row = row;
      }
    }
    for (const e of this.entries.values()) this.layout(e);
  }

  /** Position + depth for a row, using the parent for stacked surface items. */
  placement(row: RoomItem): { x: number; y: number; depth: number } {
    const it = this.cat.byId.get(row.item_id);
    const h = it?.h ?? 1;
    let x = row.x * CELL;
    let y = isWallLayer(it?.layer) ? row.y * CELL : (row.y + h) * CELL;
    let sortRow = sortRowFor(it?.layer, row.y + h - 1);
    if (it?.layer === "surface_item" && row.parent_uid != null) {
      const parent = this.entries.get(row.parent_uid)?.row ?? this.rows.find((r) => r.uid === row.parent_uid);
      const pit = parent && this.cat.byId.get(parent.item_id);
      if (parent && pit) {
        sortRow = parent.y + pit.h - 1;
        y = (row.y + h) * CELL - pit.surface_offset_y;
      }
    }
    return { x, y, depth: depthOf(sortRow, Z_SCALE[it?.layer ?? "furniture"]) + (row.uid % 97) / 100 };
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
