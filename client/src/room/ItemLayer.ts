import Phaser from "phaser";
import { Z_SCALE, type Catalog, type RoomItem } from "../catalog";
import { depthOf } from "./depth";
import { CELL } from "./grid";
import { footprintOf } from "./rules";

export const ATLAS = "interiors";

interface Entry { row: RoomItem; sprite: Phaser.GameObjects.Image }

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
      if (!e) {
        const sprite = this.scene.add.image(0, 0, ATLAS, this.cat.byId.get(row.item_id)?.sprite ?? "").setOrigin(0, 1);
        this.entries.set(row.uid, { row, sprite });
      } else {
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
    let y = (row.y + h) * CELL;
    let sortRow = row.y + h - 1;
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

  /** Topmost item whose footprint covers the cell (surface items before furniture before floor). */
  itemAt(cx: number, cy: number): RoomItem | null {
    let best: RoomItem | null = null;
    let bestZ = -1;
    for (const row of this.rows) {
      if (this.hidden.has(row.uid)) continue;
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
