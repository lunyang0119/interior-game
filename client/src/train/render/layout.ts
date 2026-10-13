/** Data-driven train-car layout: engine rooms {id, col, row, device, neighbors} → cells.
 *
 * Every room becomes one compartment: a back-wall band (WALL_ROWS) over a floor block (ROOM_W × ROOM_H). Compartments
 * sit on a grid with a one-cell partition between them and around the outside. A door is a gap cut into the
 * partition between two neighbouring rooms: on the vertical partition for side-by-side rooms, and through the
 * partition row plus the lower room's wall band for stacked rooms (so avatars can actually walk through it).
 * Pure functions, no Phaser: the walk grid and the renderer both read the result.
 */

import { cellKey, type Cell } from "../../room/walk";

export const ROOM_W = 7;      // floor cells per compartment
export const ROOM_H = 4;
export const WALL_ROWS = 2;   // back-wall band above the floor
export const GAP = 1;         // partition thickness
export const PITCH_X = ROOM_W + GAP;
export const PITCH_Y = WALL_ROWS + ROOM_H + GAP;
const DOOR_H = 2;             // cells tall (side doors)
const DOOR_W = 2;             // cells wide (stacked doors)

export interface RoomSpec { id: string; col: number; row: number; device: string; neighbors: string[] }

export interface RoomBox {
  id: string;
  device: string;
  col: number;        // engine grid position
  row: number;
  x0: number;         // floor origin (cells)
  y0: number;
  wallY0: number;     // top of the wall band
  /** Cells covered by fixed furniture (bench, device): walkable = floor minus these. */
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
  rooms: Map<string, RoomBox>;
  doors: Door[];
  doorByEdge: Map<string, Door>;
  partition: Set<number>; // cells that are solid partition (never walkable, drawn dark)
  walkable: Set<number>;
}

export function edgeKey(a: string, b: string): string {
  return [a, b].sort().join("-");
}

export function buildLayout(rooms: RoomSpec[]): Layout {
  const minC = Math.min(...rooms.map((r) => r.col));
  const minR = Math.min(...rooms.map((r) => r.row));
  const maxC = Math.max(...rooms.map((r) => r.col));
  const maxR = Math.max(...rooms.map((r) => r.row));
  const cols = GAP + (maxC - minC + 1) * PITCH_X;
  const rows = GAP + (maxR - minR + 1) * PITCH_Y;

  const boxes = new Map<string, RoomBox>();
  for (const r of rooms) {
    const x0 = GAP + (r.col - minC) * PITCH_X;
    const wallY0 = GAP + (r.row - minR) * PITCH_Y;
    boxes.set(r.id, { id: r.id, device: r.device, col: r.col, row: r.row, x0, y0: wallY0 + WALL_ROWS, wallY0, furniture: new Set() });
  }

  // everything that is not a room's wall band or floor is partition
  const inside = new Set<number>();
  for (const b of boxes.values()) {
    for (let y = b.wallY0; y < b.y0 + ROOM_H; y++) for (let x = b.x0; x < b.x0 + ROOM_W; x++) inside.add(cellKey(x, y));
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
        const left = a.col < b.col ? a : b;
        const x = left.x0 + ROOM_W;                       // the partition column between them
        const y = left.y0 + Math.floor((ROOM_H - DOOR_H) / 2);
        const cells: Cell[] = [];
        for (let i = 0; i < DOOR_H; i++) cells.push({ cx: x, cy: y + i });
        door = { a: r.id, b: nid, edge, dir: "h", cells };
      } else if (a.col === b.col && Math.abs(a.row - b.row) === 1) {
        const upper = a.row < b.row ? a : b;
        const lower = upper === a ? b : a;
        const x = upper.x0 + Math.floor((ROOM_W - DOOR_W) / 2);
        const cells: Cell[] = [];
        // partition row below the upper room, then down through the lower room's wall band
        for (let y = upper.y0 + ROOM_H; y < lower.y0; y++) for (let i = 0; i < DOOR_W; i++) cells.push({ cx: x + i, cy: y });
        door = { a: upper.id, b: lower.id, edge, dir: "v", cells };
      }
      if (!door) continue; // non-adjacent neighbours do not occur in the built-in maps; nothing to draw
      doors.push(door);
      doorByEdge.set(edge, door);
      for (const c of door.cells) partition.delete(cellKey(c.cx, c.cy));
    }
  }

  // fixed furniture: a bench along the bottom-left, the device at the top-right of the floor
  for (const b of boxes.values()) {
    for (const c of benchCells(b)) b.furniture.add(cellKey(c.cx, c.cy));
    const d = deviceCell(b);
    b.furniture.add(cellKey(d.cx, d.cy));
  }

  const walkable = new Set<number>();
  for (const b of boxes.values()) {
    for (let y = b.y0; y < b.y0 + ROOM_H; y++) for (let x = b.x0; x < b.x0 + ROOM_W; x++) {
      const k = cellKey(x, y);
      if (!b.furniture.has(k)) walkable.add(k);
    }
  }
  for (const d of doors) for (const c of d.cells) walkable.add(cellKey(c.cx, c.cy));

  return { cols, rows, rooms: boxes, doors, doorByEdge, partition, walkable };
}

/** Cells of the bench (3 wide) on the bottom row, left side. */
export function benchCells(b: RoomBox): Cell[] {
  const y = b.y0 + ROOM_H - 1;
  return [0, 1, 2].map((i) => ({ cx: b.x0 + i, cy: y }));
}

/** The device's floor cell: top-right corner against the back wall. */
export function deviceCell(b: RoomBox): Cell {
  return { cx: b.x0 + ROOM_W - 2, cy: b.y0 };
}

/** Where a standing avatar is put inside a room: slot i of up to ROOM_H*2 spots in the free middle. */
export function standCell(b: RoomBox, slot: number): Cell {
  const spots: Cell[] = [];
  for (let y = b.y0 + 1; y < b.y0 + ROOM_H - 1; y++) for (let x = b.x0 + 1; x < b.x0 + ROOM_W - 2; x += 2) spots.push({ cx: x, cy: y });
  return spots[slot % spots.length];
}

/** Room containing a cell (floor or wall band), if any. */
export function roomAt(layout: Layout, cx: number, cy: number): RoomBox | null {
  for (const b of layout.rooms.values()) {
    if (cx >= b.x0 && cx < b.x0 + ROOM_W && cy >= b.wallY0 && cy < b.y0 + ROOM_H) return b;
  }
  return null;
}
