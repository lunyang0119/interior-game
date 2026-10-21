/** Draws a Layout (layout.ts) with atlas tiles: partitions, door gaps with a door sprite, the room label, and per
 *  room either its device's interior template (wall/floor tiles + seeded items, drawn like the room scenes do) or the
 *  built-in look (plain tiles, windows, a bench and the device sprite). Nothing here knows about the game state. */

import Phaser from "phaser";
import { CELL } from "../../room/grid";
import { canHang, collisionLayer, floorKeyAt, onWall, Z_HUNG, Z_HUNG_PAPER, Z_SCALE, type Item, type Room, type Seed } from "../../catalog";
import { depthOf, FX_DEPTH, sortRowFor, TILE_DEPTH } from "../../room/depth";
import { fitPaper } from "../../room/ItemLayer";
import { cellKey } from "../../room/walk";
import { DEVICE_KO } from "../strings";
import { benchCells, deviceCell, type Door, type Layout, type RoomBox } from "./layout";
import { ATLAS, DEVICES, DOOR_FRAME, PARTITION_EDGE, PARTITION_FILL, TRAIN_FRAMES, type TrainKey } from "./tiles";

const Z_FURNITURE = 10; // below avatars (Z_AVATAR = 15) on the same row

export class CarMap {
  private objects: Phaser.GameObjects.GameObject[] = [];
  private gridLayer: Phaser.GameObjects.Graphics | null = null;
  /** Door sprites by engine edge key (the lock marker and the fugitive's doorlock picker hang off them). */
  readonly doorSprites = new Map<string, Phaser.GameObjects.Image>();
  /** Template effects that show only while a gimmick is active (`Fx.when`): tag → [{room, sprite}]. */
  private condFx = new Map<string, { room: string; sprite: Phaser.GameObjects.Sprite }[]>();

  constructor(private scene: Phaser.Scene, readonly layout: Layout) {
    this.drawTiles();
    this.drawPartitions();
    for (const d of layout.doors) this.drawDoor(d);
    for (const b of layout.rooms.values()) this.drawRoom(b);
  }

  get widthPx(): number { return this.layout.cols * CELL; }
  get heightPx(): number { return this.layout.rows * CELL; }

  private has(key: TrainKey): boolean {
    return this.hasFrame(TRAIN_FRAMES[key]);
  }

  private hasFrame(frame: string): boolean {
    return this.scene.textures.get(ATLAS).has(frame);
  }

  /** Atlas frame for a corridor part: the catalog's train layout art when it names one that is built, else the
   *  placeholder of tiles.ts (null when neither exists). */
  private art(part: "partition" | "corridor" | "side_door" | "back_door"): string | null {
    const custom = this.layout.art?.tiles?.[part];
    if (custom && this.hasFrame(custom)) return custom;
    const fallback: Record<typeof part, TrainKey | null> = { partition: null, corridor: "train_floor_door", side_door: "train_side_door", back_door: "train_back_door" };
    const k = fallback[part];
    return k && this.has(k) ? TRAIN_FRAMES[k] : null;
  }

  private image(x: number, y: number, key: TrainKey): Phaser.GameObjects.Image {
    return this.frameImage(x, y, TRAIN_FRAMES[key]);
  }

  private frameImage(x: number, y: number, frame: string): Phaser.GameObjects.Image {
    const img = this.scene.add.image(x, y, ATLAS, frame).setOrigin(0, 1);
    this.objects.push(img);
    return img;
  }

  private drawTiles(): void {
    const { cols, rows } = this.layout;
    const rt = this.scene.add.renderTexture(0, 0, cols * CELL, rows * CELL).setOrigin(0).setDepth(TILE_DEPTH);
    this.objects.push(rt);
    const draw = (key: TrainKey, cx: number, cy: number) => rt.drawFrame(ATLAS, TRAIN_FRAMES[key], cx * CELL, cy * CELL);
    // the partition as a tile when the layout names one (else drawPartitions paints it flat)
    const part = this.art("partition");
    if (part) for (const k of this.layout.partition) rt.drawFrame(ATLAS, part, (k % 10_000) * CELL, Math.floor(k / 10_000) * CELL);
    for (const b of this.layout.rooms.values()) {
      if (b.tpl) { this.drawTemplateTiles(rt, b, b.tpl); continue; }
      for (let x = b.x0; x < b.x0 + b.w; x++) {
        draw("train_wall_top", x, b.wallY0);
        for (let y = b.wallY0 + 1; y < b.y0; y++) draw("train_wall_bottom", x, y);
        for (let y = b.y0; y < b.y0 + b.h; y++) draw("train_floor", x, y);
      }
      if (this.has("train_window")) for (const wx of [b.x0 + 1, b.x0 + b.w - 3]) draw("train_window", wx, b.wallY0);
    }
    const corridor = this.art("corridor");
    if (corridor) for (const d of this.layout.doors) for (const c of d.cells) rt.drawFrame(ATLAS, corridor, c.cx * CELL, c.cy * CELL);
  }

  /** Wall rows (wall_left / wall_right on the edge columns) and the floor (painted grid, else tiles.floor),
   *  exactly like a room scene. */
  private drawTemplateTiles(rt: Phaser.GameObjects.RenderTexture, b: RoomBox, t: Room): void {
    for (let ly = 0; ly < t.rows; ly++) for (let lx = 0; lx < t.cols; lx++) {
      let key: string | undefined;
      if (ly < t.wall_rows) {
        const edge = lx === 0 ? t.tiles.wall_left : lx === t.cols - 1 ? t.tiles.wall_right : null;
        key = (edge && edge.length > ly ? edge : t.tiles.wall)[ly];
      } else {
        key = floorKeyAt(t, lx, ly);
      }
      if (key && this.hasFrame(key)) rt.drawFrame(ATLAS, key, (b.x0 + lx) * CELL, (b.wallY0 + ly) * CELL);
    }
  }

  /** A template's seeded items, positioned and depth-sorted like room/ItemLayer.ts does for placed items. */
  private drawTemplateItems(b: RoomBox, t: Room): void {
    const cat = this.layout.cat;
    if (!cat) return;
    const seeds = (t.seed ?? []).map((s) => ({ s, it: cat.byId.get(s.item_id) })).filter((o): o is { s: Seed; it: Item } => !!o.it);
    for (const { s, it } of seeds) {
      if (!this.hasFrame(it.sprite)) continue;
      const cl = collisionLayer(it);
      const row = b.wallY0 + s.y;
      let y = (onWall(it) ? row * CELL : (row + it.h) * CELL) + (it.offset_y ?? 0);
      let sortRow = sortRowFor(cl, row + it.h - 1);
      let z = Z_SCALE[cl];
      if (it.layer === "surface_item") {
        // on the surface furniture under its bottom row, like a cup on a table
        const by = s.y + it.h - 1;
        const p = seeds.find((o) => o.it.is_surface && s.x >= o.s.x && s.x < o.s.x + o.it.w && by >= o.s.y && by < o.s.y + o.it.h);
        if (p) { y = (row + it.h) * CELL - p.it.surface_offset_y + (it.offset_y ?? 0); sortRow = b.wallY0 + p.s.y + p.it.h - 1; }
      } else if (canHang(it) && s.y >= t.wall_rows) {
        z = it.layer === "wallpaper" ? Z_HUNG_PAPER : Z_HUNG; // hung on a partition's face
      }
      const x = (b.x0 + s.x) * CELL;
      const depth = depthOf(sortRow, z);
      if (it.layer === "wallpaper") {
        const ts = this.scene.add.tileSprite(x, y, (s.span || it.w) * CELL, this.scene.textures.getFrame(ATLAS, it.sprite).height, ATLAS, it.sprite)
          .setOrigin(0, 0).setDepth(depth);
        fitPaper(this.scene, ts, it, s.span, s.y >= t.wall_rows);
        this.objects.push(ts);
      } else {
        const img = this.scene.add.image(x, y, ATLAS, it.sprite).setOrigin(0, onWall(it) ? 0 : 1).setDepth(depth);
        this.objects.push(img);
      }
    }
  }

  /** A template's pixel-placed effects (steam over the coffeepot…), like RoomScene.drawFx: on top of everything,
   *  looping when the sprite is an anim slice. Ones with `when` start hidden and follow setCondition(). */
  private drawTemplateFx(b: RoomBox, t: Room): void {
    const cat = this.layout.cat;
    if (!cat) return;
    const atlas = this.scene.textures.get(ATLAS);
    for (const f of t.fx ?? []) {
      if (!atlas.has(f.sprite)) continue;
      const s = this.scene.add.sprite(b.x0 * CELL + f.x, b.wallY0 * CELL + f.y, ATLAS, f.sprite).setOrigin(0).setDepth(FX_DEPTH);
      this.objects.push(s);
      const spec = cat.anims[f.sprite];
      if (spec && spec.frames >= 2) {
        const key = `fx:${f.sprite}`;
        if (!this.scene.anims.exists(key)) {
          const frames = Array.from({ length: spec.frames }, (_, i) => ({ key: ATLAS, frame: `${f.sprite}#${i}` })).filter((fr) => atlas.has(fr.frame));
          if (frames.length >= 2) this.scene.anims.create({ key, frames, frameRate: spec.fps, repeat: -1 });
        }
        if (this.scene.anims.exists(key)) s.play(key);
      }
      if (f.when) {
        s.setVisible(false);
        const list = this.condFx.get(f.when) ?? [];
        list.push({ room: b.id, sprite: s });
        this.condFx.set(f.when, list);
      }
    }
  }

  /** Show the effects tagged `tag` in exactly these rooms (e.g. "steam" → the rooms the public view lists as steamy). */
  setCondition(tag: string, rooms: string[]): void {
    for (const { room, sprite } of this.condFx.get(tag) ?? []) sprite.setVisible(rooms.includes(room));
  }

  private drawPartitions(): void {
    if (this.art("partition")) return; // tiled in drawTiles
    const g = this.scene.add.graphics().setDepth(TILE_DEPTH + 1);
    this.objects.push(g);
    for (const k of this.layout.partition) {
      const cx = k % 10_000, cy = Math.floor(k / 10_000);
      g.fillStyle(PARTITION_FILL, 1).fillRect(cx * CELL, cy * CELL, CELL, CELL);
      // lighter top edge so the partition reads as a raised wall seen from above
      if (!this.layout.partition.has(cellKey(cx, cy - 1))) g.fillStyle(PARTITION_EDGE, 1).fillRect(cx * CELL, cy * CELL, CELL, 3);
    }
  }

  /** Every door gap gets a door sprite (the layout's art, else the placeholders of tiles.ts) plus thin frame posts
   *  along the gap's edges. The gap is a rectangle of corridor cells (gap columns × shared rows, or shared columns ×
   *  partition rows + the lower wall band). */
  private drawDoor(d: Door): void {
    const g = this.scene.add.graphics().setDepth(TILE_DEPTH + 1);
    this.objects.push(g);
    g.fillStyle(DOOR_FRAME, 1);
    const x0 = Math.min(...d.cells.map((c) => c.cx)), x1 = Math.max(...d.cells.map((c) => c.cx));
    const y0 = Math.min(...d.cells.map((c) => c.cy)), y1 = Math.max(...d.cells.map((c) => c.cy));
    let img: Phaser.GameObjects.Image | null = null;
    if (d.dir === "h") {
      g.fillRect(x0 * CELL, y0 * CELL - 2, (x1 - x0 + 1) * CELL, 2);
      g.fillRect(x0 * CELL, (y1 + 1) * CELL, (x1 - x0 + 1) * CELL, 2);
      const frame = this.art("side_door");
      if (frame) {
        img = this.frameImage(x0 * CELL, (y1 + 1) * CELL, frame).setAlpha(0.85);
        img.setDepth(TILE_DEPTH + 2); // avatars walk over it
      }
    } else {
      for (let y = y0; y <= y1; y++) {
        g.fillRect(x0 * CELL - 2, y * CELL, 2, CELL);
        g.fillRect((x1 + 1) * CELL, y * CELL, 2, CELL);
      }
      const frame = this.art("back_door");
      if (frame) {
        // the lower room's wall-band rows carry the door picture; the partition row(s) above stay a threshold
        img = this.frameImage(x0 * CELL, (y1 + 1) * CELL, frame).setAlpha(0.85);
        img.setDepth(TILE_DEPTH + 2);
      }
    }
    if (img) this.doorSprites.set(d.edge, img);
  }

  private drawRoom(b: RoomBox): void {
    if (b.tpl) { this.drawTemplateItems(b, b.tpl); this.drawTemplateFx(b, b.tpl); }
    else this.drawBuiltinFurniture(b);
    const label = this.scene.add.text((b.x0 + b.w) * CELL - 2, (b.y0 + b.h) * CELL - 2, `${b.id} · ${DEVICE_KO[b.device] ?? b.device}`, {
      fontFamily: '"Label", "Stardust", sans-serif', fontSize: "8px", color: "#f0f0f5", backgroundColor: "rgba(10,14,30,0.7)", padding: { x: 3, y: 1 }, resolution: 3,
    }).setOrigin(1, 1).setDepth(TILE_DEPTH + 3);
    this.objects.push(label);
  }

  private drawBuiltinFurniture(b: RoomBox): void {
    if (this.has("train_bench")) {
      const bc = benchCells(b)[0];
      this.image(bc.cx * CELL, (bc.cy + 1) * CELL, "train_bench").setDepth(depthOf(bc.cy, Z_FURNITURE));
    }
    const dev = DEVICES[b.device];
    const dc = deviceCell(b);
    if (dev && this.has(dev.key)) {
      this.image((dc.cx - dev.w + 1) * CELL, (dc.cy + 1 + (dev.dy ?? 0)) * CELL, dev.key).setDepth(depthOf(dc.cy, Z_FURNITURE));
    }
  }

  /** Debug overlay: cell grid of every floor cell and the walkable cells (the preview's "칸 번호" toggle). */
  showGrid(on: boolean): void {
    if (this.gridLayer) { this.gridLayer.destroy(); this.gridLayer = null; }
    if (!on) return;
    const g = this.scene.add.graphics().setDepth(TILE_DEPTH + 3);
    g.lineStyle(1, 0xffffff, 0.15);
    for (const b of this.layout.rooms.values()) {
      for (let y = b.y0; y < b.y0 + b.h; y++) for (let x = b.x0; x < b.x0 + b.w; x++) g.strokeRect(x * CELL + 0.5, y * CELL + 0.5, CELL - 1, CELL - 1);
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
    this.condFx.clear();
    this.showGrid(false);
  }
}
