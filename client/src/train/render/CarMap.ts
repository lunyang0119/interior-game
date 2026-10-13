/** Draws a Layout (layout.ts) with atlas tiles: floors, wall bands with windows, partitions, door gaps, the device
 *  sprite and a bench per room, and the room label. Nothing here knows about the game state. */

import Phaser from "phaser";
import { CELL } from "../../room/grid";
import { TILE_DEPTH } from "../../room/depth";
import { cellKey } from "../../room/walk";
import { DEVICE_KO } from "../strings";
import { benchCells, deviceCell, ROOM_H, ROOM_W, WALL_ROWS, type Layout, type RoomBox } from "./layout";
import { ATLAS, DEVICES, DOOR_FRAME, PARTITION_EDGE, PARTITION_FILL, TILES } from "./tiles";

export class CarMap {
  private objects: Phaser.GameObjects.GameObject[] = [];
  private gridLayer: Phaser.GameObjects.Graphics | null = null;

  constructor(private scene: Phaser.Scene, readonly layout: Layout) {
    this.drawTiles();
    this.drawPartitions();
    for (const b of layout.rooms.values()) this.drawRoom(b);
  }

  get widthPx(): number { return this.layout.cols * CELL; }
  get heightPx(): number { return this.layout.rows * CELL; }

  private frame(key: string): boolean {
    return this.scene.textures.get(ATLAS).has(key);
  }

  private drawTiles(): void {
    const { cols, rows } = this.layout;
    const rt = this.scene.add.renderTexture(0, 0, cols * CELL, rows * CELL).setOrigin(0).setDepth(TILE_DEPTH);
    this.objects.push(rt);
    const doorCells = new Set<number>();
    for (const d of this.layout.doors) for (const c of d.cells) doorCells.add(cellKey(c.cx, c.cy));
    for (const b of this.layout.rooms.values()) {
      for (let x = b.x0; x < b.x0 + ROOM_W; x++) {
        rt.drawFrame(ATLAS, TILES.wallTop, x * CELL, b.wallY0 * CELL);
        for (let y = b.wallY0 + 1; y < b.y0; y++) rt.drawFrame(ATLAS, TILES.wallBottom, x * CELL, y * CELL);
        for (let y = b.y0; y < b.y0 + ROOM_H; y++) rt.drawFrame(ATLAS, TILES.floor, x * CELL, y * CELL);
      }
      // windows on the wall band (two per compartment)
      if (this.frame(TILES.window)) {
        for (const wx of [b.x0 + 1, b.x0 + ROOM_W - 3]) rt.drawFrame(ATLAS, TILES.window, wx * CELL, b.wallY0 * CELL);
      }
    }
    for (const k of doorCells) {
      const cx = k % 10_000, cy = Math.floor(k / 10_000);
      rt.drawFrame(ATLAS, TILES.door, cx * CELL, cy * CELL);
    }
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
    // door frames: a thin post on each side of the gap
    for (const d of this.layout.doors) {
      g.fillStyle(DOOR_FRAME, 1);
      const first = d.cells[0], last = d.cells[d.cells.length - 1];
      if (d.dir === "h") {
        g.fillRect(first.cx * CELL, first.cy * CELL - 2, CELL, 2);
        g.fillRect(last.cx * CELL, (last.cy + 1) * CELL, CELL, 2);
      } else {
        const x0 = Math.min(...d.cells.map((c) => c.cx)), x1 = Math.max(...d.cells.map((c) => c.cx));
        for (let y = first.cy; y <= last.cy; y++) {
          g.fillRect(x0 * CELL - 2, y * CELL, 2, CELL);
          g.fillRect((x1 + 1) * CELL, y * CELL, 2, CELL);
        }
      }
    }
  }

  private drawRoom(b: RoomBox): void {
    const s = this.scene;
    // bench along the bottom-left
    if (this.frame(TILES.bench)) {
      const bc = benchCells(b)[0];
      const bench = s.add.image(bc.cx * CELL, (bc.cy + 1) * CELL, ATLAS, TILES.bench).setOrigin(0, 1);
      bench.setDepth((bc.cy + 1) * CELL);
      this.objects.push(bench);
    }
    // the room's device, top-right against the wall
    const dev = DEVICES[b.device];
    const dc = deviceCell(b);
    if (dev && this.frame(dev.key)) {
      const img = s.add.image((dc.cx - dev.w + 1) * CELL, (dc.cy + 1 + (dev.dy ?? 0)) * CELL, ATLAS, dev.key).setOrigin(0, 1);
      img.setDepth((dc.cy + 1) * CELL);
      this.objects.push(img);
    }
    // label: room id + device kind, on the wall band
    const label = s.add.text(b.x0 * CELL + 2, b.wallY0 * CELL + 2, `${b.id} · ${DEVICE_KO[b.device] ?? b.device}`, {
      fontFamily: '"Label", "Stardust", sans-serif', fontSize: "8px", color: "#f0f0f5", stroke: "#000", strokeThickness: 2, resolution: 3,
    }).setOrigin(0, 0).setDepth(TILE_DEPTH + 2);
    this.objects.push(label);
  }

  /** Debug overlay: cell coordinates of every floor cell (the preview's "칸 번호" toggle). */
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
    this.showGrid(false);
  }
}

export const WALL_BAND_ROWS = WALL_ROWS;
