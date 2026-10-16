/** Data-driven train-car layout: engine rooms {id, col, row, device, neighbors} → cells.
 *
 * Every room becomes one compartment: a back-wall band (`wall` rows) over a floor block (`w` × `h`). Compartments
 * sit on a grid with a `gap`-cell partition between them and around the outside. A door is a gap cut into the
 * partition between two neighbouring rooms: on the vertical partition for side-by-side rooms, and through the
 * partition row(s) plus the lower room's wall band for stacked rooms (so avatars can actually walk through it).
 * Where a door opens comes from each template's `doors` (world editor "열차 칸" → 문 위치; default = centred,
 * 2 cells): two facing openings share the rows/columns they overlap on, else the left/upper room's opening wins.
 *
 * The compartment size and furniture come from the catalog's `train` interiors (one Room-shaped template per engine
 * device, edited as "열차 칸" in the world editor, data/train_interiors.json); `trainLayout` gives the gap and the
 * corridor art. Without them every compartment is the built-in 7×4 one with a bench and the device sprite. Pure
 * functions, no Phaser: the walk grid and the renderer both read the result.
 */

import { collisionLayer, floorKeyAt, hasTag, TAG_DOOR, type Catalog, type Room, type TrainLayout } from "../../catalog";
import { cellKey, type Cell } from "../../room/walk";

export const DEFAULT_GAP = 1; // partition thickness
const DOOR_H = 2;             // cells tall (side doors) when a template names no opening
const DOOR_W = 2;             // cells wide (stacked doors)

/** The rows (left/right) or columns (top/bottom) a compartment opens on, in world cells. */
export function opening(b: RoomBox, side: "left" | "right" | "top" | "bottom"): number[] {
  const d = b.tpl?.doors?.[side];
  if (side === "left" || side === "right") {
    const spec = d as { y: number; h: number } | null | undefined;
    const y0 = spec ? b.wallY0 + spec.y : b.y0 + Math.floor((b.h - DOOR_H) / 2);
    const h = spec ? spec.h : DOOR_H;
    const out: number[] = [];
    for (let y = Math.max(b.y0, y0); y < Math.min(b.y0 + b.h, y0 + h); y++) out.push(y);
    return out.length ? out : [b.y0 + Math.floor((b.h - 1) / 2)];
  }
  const spec = d as { x: number; w: number } | null | undefined;
  const x0 = spec ? b.x0 + spec.x : b.x0 + Math.floor((b.w - DOOR_W) / 2);
  const w = spec ? spec.w : DOOR_W;
  const out: number[] = [];
  for (let x = Math.max(b.x0, x0); x < Math.min(b.x0 + b.w, x0 + w); x++) out.push(x);
  return out.length ? out : [b.x0 + Math.floor((b.w - 1) / 2)];
}

/** The lines two facing openings share; when they do not overlap the first (left/upper room's) wins. */
function shared(a: number[], b: number[]): number[] {
  const both = a.filter((v) => b.includes(v));
  return both.length ? both : a;
}

/** Compartment size: floor cells w × h under `wall` back-wall rows. */
export interface Dims { w: number; h: number; wall: number }
export const DEFAULT_DIMS: Dims = { w: 7, h: 4, wall: 2 };

export interface RoomSpec { id: string; col: number; row: number; device: string; neighbors: string[] }

export interface RoomBox {
  id: string;
  device: string;
  col: number;        // engine grid position
  row: number;
  x0: number;         // floor origin (cells)
  y0: number;
  wallY0: number;     // top of the wall band
  w: number;          // floor size (same for every room)
  h: number;
  /** The device's interior template (template cell (x, y) = world (x0 + x, wallY0 + y)); null = built-in look. */
  tpl: Room | null;
  /** Floor cells avatars cannot enter (furniture, blocked cells): walkable = floor minus these. */
  furniture: Set<number>;
}

export interface Door {
  a: string;
  b: string;
  edge: string;       // engine edge key "A1-A2" (sorted)
  dir: "h" | "v";
  cells: Cell[];      // the gap, in walking order from a to b
}

export interface Layout {
  cols: number;
  rows: number;
  dims: Dims;
  gap: number;
  /** Corridor art from the catalog (train_interiors.json `layout`); null = CarMap's placeholders. */
  art: TrainLayout | null;
  cat: Catalog | null;
  rooms: Map<string, RoomBox>;
  doors: Door[];
  doorByEdge: Map<string, Door>;
  partition: Set<number>; // cells that are solid partition (never walkable, drawn dark)
  walkable: Set<number>;
}

export function edgeKey(a: string, b: string): string {
  return [a, b].sort().join("-");
}

/** Compartment size of the catalog's train interiors (all templates share it; the server checks). */
export function dimsOf(cat: Catalog | null): Dims {
  const t = cat?.train ? Object.values(cat.train)[0] : undefined;
  return t ? { w: t.cols, h: t.rows - t.wall_rows, wall: t.wall_rows } : DEFAULT_DIMS;
}

export function buildLayout(rooms: RoomSpec[], cat: Catalog | null = null): Layout {
  const dims = dimsOf(cat);
  const art = cat?.trainLayout ?? null;
  const GAP = Math.max(1, Math.min(4, art?.gap ?? DEFAULT_GAP));
  const pitchX = dims.w + GAP, pitchY = dims.wall + dims.h + GAP;
  const minC = Math.min(...rooms.map((r) => r.col));
  const minR = Math.min(...rooms.map((r) => r.row));
  const maxC = Math.max(...rooms.map((r) => r.col));
  const maxR = Math.max(...rooms.map((r) => r.row));
  const cols = GAP + (maxC - minC + 1) * pitchX;
  const rows = GAP + (maxR - minR + 1) * pitchY;

  const boxes = new Map<string, RoomBox>();
  for (const r of rooms) {
    const x0 = GAP + (r.col - minC) * pitchX;
    const wallY0 = GAP + (r.row - minR) * pitchY;
    boxes.set(r.id, { id: r.id, device: r.device, col: r.col, row: r.row, x0, y0: wallY0 + dims.wall, wallY0, w: dims.w, h: dims.h,
                      tpl: cat?.train?.[r.device] ?? null, furniture: new Set() });
  }

  // everything that is not a room's wall band or floor is partition
  const inside = new Set<number>();
  for (const b of boxes.values()) {
    for (let y = b.wallY0; y < b.y0 + b.h; y++) for (let x = b.x0; x < b.x0 + b.w; x++) inside.add(cellKey(x, y));
  }
  const partition = new Set<number>();
  for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) if (!inside.has(cellKey(x, y))) partition.add(cellKey(x, y));

  const doors: Door[] = [];
  const doorByEdge = new Map<string, Door>();
  for (const r of rooms) {
    const a = boxes.get(r.id)!;
    for (const nid of r.neighbors) {
      const b = boxes.get(nid);
      if (!b || doorByEdge.has(edgeKey(r.id, nid))) continue;
      const edge = edgeKey(r.id, nid);
      let door: Door | null = null;
      if (a.row === b.row && Math.abs(a.col - b.col) === 1) {
        const left = a.col < b.col ? a : b, right = left === a ? b : a;
        const ys = shared(opening(left, "right"), opening(right, "left"));
        const cells: Cell[] = [];
        // the partition column(s) between them, walking order from a to b
        for (let x = left.x0 + left.w; x < right.x0; x++) for (const y of ys) cells.push({ cx: x, cy: y });
        if (a !== left) cells.reverse();
        door = { a: r.id, b: nid, edge, dir: "h", cells };
      } else if (a.col === b.col && Math.abs(a.row - b.row) === 1) {
        const upper = a.row < b.row ? a : b;
        const lower = upper === a ? b : a;
        const xs = shared(opening(upper, "bottom"), opening(lower, "top"));
        const cells: Cell[] = [];
        // partition row(s) below the upper room, then down through the lower room's wall band
        for (let y = upper.y0 + upper.h; y < lower.y0; y++) for (const x of xs) cells.push({ cx: x, cy: y });
        door = { a: upper.id, b: lower.id, edge, dir: "v", cells };
      }
      if (!door) continue; // non-adjacent neighbours: app/train/maps.py refuses them; nothing to draw
      doors.push(door);
      doorByEdge.set(edge, door);
      for (const c of door.cells) partition.delete(cellKey(c.cx, c.cy));
    }
  }

  for (const b of boxes.values()) {
    if (b.tpl && cat) {
      for (const k of templateBlocks(cat, b, b.tpl)) b.furniture.add(k);
    } else {
      // built-in: a bench along the bottom-left, the device at the top-right of the floor
      for (const c of benchCells(b)) b.furniture.add(cellKey(c.cx, c.cy));
      const d = deviceCell(b);
      b.furniture.add(cellKey(d.cx, d.cy));
    }
  }
  // the floor cell right inside every door stays free, whatever the template put there
  for (const d of doors) {
    for (const c of d.cells) {
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const k = cellKey(c.cx + dx, c.cy + dy);
        for (const b of [boxes.get(d.a)!, boxes.get(d.b)!]) b.furniture.delete(k);
      }
    }
  }

  const walkable = new Set<number>();
  for (const b of boxes.values()) {
    for (let y = b.y0; y < b.y0 + b.h; y++) for (let x = b.x0; x < b.x0 + b.w; x++) {
      const k = cellKey(x, y);
      if (!b.furniture.has(k)) walkable.add(k);
    }
  }
  for (const d of doors) for (const c of d.cells) walkable.add(cellKey(c.cx, c.cy));

  return { cols, rows, dims, gap: GAP, art, cat, rooms: boxes, doors, doorByEdge, partition, walkable };
}

/** Floor cells a template blocks: furniture-group seeds (partitions too, unless tagged door), the editor's
 *  "막힌 칸" cells and floor tiles marked walk: false. */
function templateBlocks(cat: Catalog, b: RoomBox, t: Room): number[] {
  const out: number[] = [];
  const add = (x: number, y: number) => { if (y >= t.wall_rows && x >= 0 && x < t.cols && y < t.rows) out.push(cellKey(b.x0 + x, b.wallY0 + y)); };
  for (const s of t.seed ?? []) {
    const it = cat.byId.get(s.item_id);
    if (!it || collisionLayer(it) !== "furniture" || hasTag(it, TAG_DOOR)) continue;
    for (let y = s.y; y < s.y + it.h; y++) for (let x = s.x; x < s.x + it.w; x++) add(x, y);
  }
  for (const [x, y] of t.blocked ?? []) add(x, y);
  for (let y = t.wall_rows; y < t.rows; y++) for (let x = 0; x < t.cols; x++) {
    if (cat.tiles.interior[floorKeyAt(t, x, y)]?.walk === false) add(x, y);
  }
  return out;
}

/** Cells of the built-in bench (3 wide) on the bottom row, left side. */
export function benchCells(b: RoomBox): Cell[] {
  const y = b.y0 + b.h - 1;
  return [0, 1, 2].map((i) => ({ cx: b.x0 + i, cy: y }));
}

/** The built-in device's floor cell: top-right corner against the back wall. */
export function deviceCell(b: RoomBox): Cell {
  return { cx: b.x0 + b.w - 2, cy: b.y0 };
}

function walkableIn(layout: Layout, b: RoomBox): Cell[] {
  const out: Cell[] = [];
  for (let y = b.y0; y < b.y0 + b.h; y++) for (let x = b.x0; x < b.x0 + b.w; x++) if (layout.walkable.has(cellKey(x, y))) out.push({ cx: x, cy: y });
  return out;
}

/** Where a standing avatar is put inside a room: slot i of the free spots in the middle (every other column). */
export function standCell(layout: Layout, b: RoomBox, slot: number): Cell {
  let spots: Cell[] = [];
  for (let y = b.y0 + 1; y < b.y0 + b.h - 1; y++) for (let x = b.x0 + 1; x < b.x0 + b.w - 2; x += 2) {
    if (layout.walkable.has(cellKey(x, y))) spots.push({ cx: x, cy: y });
  }
  if (!spots.length) spots = walkableIn(layout, b);
  return spots.length ? spots[slot % spots.length] : { cx: b.x0, cy: b.y0 };
}

/** The walkable cell of a room closest to `want` (the cell itself when free). */
export function nearestFree(layout: Layout, b: RoomBox, want: Cell): Cell {
  if (layout.walkable.has(cellKey(want.cx, want.cy))) return want;
  let best = want, bestD = Infinity;
  for (const c of walkableIn(layout, b)) {
    const d = Math.abs(c.cx - want.cx) + Math.abs(c.cy - want.cy);
    if (d < bestD) { best = c; bestD = d; }
  }
  return best;
}

/** Room containing a cell (floor or wall band), if any. */
export function roomAt(layout: Layout, cx: number, cy: number): RoomBox | null {
  for (const b of layout.rooms.values()) {
    if (cx >= b.x0 && cx < b.x0 + b.w && cy >= b.wallY0 && cy < b.y0 + b.h) return b;
  }
  return null;
}
