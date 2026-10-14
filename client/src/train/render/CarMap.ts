/** Draws a Layout (layout.ts) with atlas tiles: floors, wall bands with windows, partitions, door gaps with a door
 *  sprite, the device sprite and a bench per room, and the room label. Nothing here knows about the game state. */

import Phaser from "phaser";
import { CELL } from "../../room/grid";
import { depthOf, TILE_DEPTH } from "../../room/depth";
import { cellKey } from "../../room/walk";
import { DEVICE_KO } from "../strings";
import { benchCells, deviceCell, ROOM_H, ROOM_W, type Door, type Layout, type RoomBox } from "./layout";
import { ATLAS, DEVICES, DOOR_FRAME, PARTITION_EDGE, PARTITION_FILL, TRAIN_FRAMES, type TrainKey } from "./tiles";

const Z_FURNITURE = 10; // below avatars (Z_AVATAR = 15) on the same row

export class CarMap {
  private objects: Phaser.GameObjects.GameObject[] = [];
  private gridLayer: Phaser.GameObjects.Graphics | null = null;
  /** Door sprites by engine edge key (the lock marker and the fugitive's doorlock picker hang off them). */
  readonly doorSprites = new Map<string, Phaser.GameObjects.Image>();

  constructor(private scene: Phaser.Scene, readonly layout: Layout) {
    this.drawTiles();
    this.drawPartitions();
    for (const d of layout.doors) this.drawDoor(d);
    for (const b of layout.rooms.values()) this.drawRoom(b);
  }

  get widthPx(): number { return this.layout.cols * CELL; }
  get heightPx(): number { return this.layout.rows * CELL; }

  private has(key: TrainKey): boolean {
    return this.scene.textures.get(ATLAS).has(TRAIN_FRAMES[key]);
  }

  private image(x: number, y: number, key: TrainKey): Phaser.GameObjects.Image {
    const img = this.scene.add.image(x, y, ATLAS, TRAIN_FRAMES[key]).setOrigin(0, 1);
    this.objects.push(img);
    return img;
  }

  private drawTiles(): void {
    const { cols, rows } = this.layout;
    const rt = this.scene.add.renderTexture(0, 0, cols * CELL, rows * CELL).setOrigin(0).setDepth(TILE_DEPTH);
    this.objects.push(rt);
    const draw = (key: TrainKey, cx: number, cy: number) => rt.drawFrame(ATLAS, TRAIN_FRAMES[key], cx * CELL, cy * CELL);
    for (const b of this.layout.rooms.values()) {
      for (let x = b.x0; x < b.x0 + ROOM_W; x++) {
        draw("train_wall_top", x, b.wallY0);
        for (let y = b.wallY0 + 1; y < b.y0; y++) draw("train_wall_bottom", x, y);
        for (let y = b.y0; y < b.y0 + ROOM_H; y++) draw("train_floor", x, y);
      }
      if (this.has("train_window")) for (const wx of [b.x0 + 1, b.x0 + ROOM_W - 3]) draw("train_window", wx, b.wallY0);
    }
    for (const d of this.layout.doors) for (const c of d.cells) draw("train_floor_door", c.cx, c.cy);
  }

  private drawPartitions(): void {
    const g = this.scene.add.graphics().setDepth(TILE_DEPTH + 1);
    this.objects.push(g);
    for (const k of this.layout.partition) {
      const cx = k % 10_000, cy = Math.floor(k / 10_000);
      g.fillStyle(PARTITION_FILL, 1).fillRect(cx * CELL, cy * CELL, CELL, CELL);
      // lighter top edge so the partition reads as a raised wall seen from above
      if (!this.layout.partition.has(cellKey(cx, cy - 1))) g.fillStyle(PARTITION_EDGE, 1).fillRect(cx * CELL, cy * CELL, CELL, 3);
    }
  }

  /** Every door gap gets a door sprite (placeholder art, see tiles.ts) plus thin frame posts. */
  private drawDoor(d: Door): void {
    const g = this.scene.add.graphics().setDepth(TILE_DEPTH + 1);
    this.objects.push(g);
    g.fillStyle(DOOR_FRAME, 1);
    const first = d.cells[0], last = d.cells[d.cells.length - 1];
    let img: Phaser.GameObjects.Image | null = null;
    if (d.dir === "h") {
      g.fillRect(first.cx * CELL, first.cy * CELL - 2, CELL, 2);
      g.fillRect(last.cx * CELL, (last.cy + 1) * CELL, CELL, 2);
      if (this.has("train_side_door")) {
        img = this.image(first.cx * CELL, (last.cy + 1) * CELL, "train_side_door").setAlpha(0.85);
        img.setDepth(TILE_DEPTH + 2); // avatars walk over it
      }
    } else {
      const x0 = Math.min(...d.cells.map((c) => c.cx)), x1 = Math.max(...d.cells.map((c) => c.cx));
      for (let y = first.cy; y <= last.cy; y++) {
        g.fillRect(x0 * CELL - 2, y * CELL, 2, CELL);
        g.fillRect((x1 + 1) * CELL, y * CELL, 2, CELL);
      }
      if (this.has("train_back_door")) {
        // the two wall-band rows of the lower room carry the door picture; the partition row above stays a threshold
        img = this.image(x0 * CELL, (last.cy + 1) * CELL, "train_back_door").setAlpha(0.85);
        img.setDepth(TILE_DEPTH + 2);
      }
    }
    if (img) this.doorSprites.set(d.edge, img);
  }

  private drawRoom(b: RoomBox): void {
    if (this.has("train_bench")) {
      const bc = benchCells(b)[0];
      this.image(bc.cx * CELL, (bc.cy + 1) * CELL, "train_bench").setDepth(depthOf(bc.cy, Z_FURNITURE));
    }
    const dev = DEVICES[b.device];
    const dc = deviceCell(b);
    if (dev && this.has(dev.key)) {
      this.image((dc.cx - dev.w + 1) * CELL, (dc.cy + 1 + (dev.dy ?? 0)) * CELL, dev.key).setDepth(depthOf(dc.cy, Z_FURNITURE));
    }
    const label = this.scene.add.text(b.x0 * CELL + 2, b.wallY0 * CELL + 2, `${b.id} · ${DEVICE_KO[b.device] ?? b.device}`, {
      fontFamily: '"Label", "Stardust", sans-serif', fontSize: "8px", color: "#f0f0f5", stroke: "#000", strokeThickness: 2, resolution: 3,
    }).setOrigin(0, 0).setDepth(TILE_DEPTH + 3);
    this.objects.push(label);
  }

  /** Debug overlay: cell grid of every floor cell and the walkable cells (the preview's "칸 번호" toggle). */
  showGrid(on: boolean): void {
    if (this.gridLayer) { this.gridLayer.destroy(); this.gridLayer = null; }
    if (!on) return;
    const g = this.scene.add.graphics().setDepth(TILE_DEPTH + 3);
    g.lineStyle(1, 0xffffff, 0.15);
    for (const b of this.layout.rooms.values()) {
      for (let y = b.y0; y < b.y0 + ROOM_H; y++) for (let x = b.x0; x < b.x0 + ROOM_W; x++) g.strokeRect(x * CELL + 0.5, y * CELL + 0.5, CELL - 1, CELL - 1);
    }
    g.lineStyle(1, 0x4f8cff, 0.6);
    for (const k of this.layout.walkable) {
      const cx = k % 10_000, cy = Math.floor(k / 10_000);
      g.strokeRect(cx * CELL + 3, cy * CELL + 3, CELL - 6, CELL - 6);
    }
    this.gridLayer = g;
  }

  destroy(): void {
    for (const o of this.objects) o.destroy();
    this.objects = [];
    this.doorSprites.clear();
    this.showGrid(false);
  }
}
