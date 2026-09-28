/** Where an avatar may stand, and how to get there. Client-only: the server just clamps positions to the room.
 *
 * A WalkGrid answers "can I stand on this cell". Rooms: floor rows only, not `room.blocked`, not a tile
 * with walk:false (water…), not under furniture a player placed (rugs, wallpaper, wall decor and surface items
 * never block; stairs sit on exits so they stay enterable). Designer seeds ($seed) and ruined junk do not block
 * either: seeds are placed "relaxed" — overlapping and off-grid for perspective — and a ruined inn is packed
 * with junk wall to wall, so treating them as solid would leave nowhere to stand. The map: not `blocked`
 * (map cells + building footprints minus doors) and not an unwalkable ground/deco tile.
 */

import { exitAt, floorKeyAt, hasTag, SEED_PLAYER, TAG_RUINED, TAG_STAIRS, type Catalog, type MapData, type Room, type RoomItem } from "../catalog";
import { footprintOf } from "./rules";

export interface Cell { cx: number; cy: number }

/** Same encoding rules.ts and MapScene use for cell sets. */
export const cellKey = (cx: number, cy: number): number => cy * 10_000 + cx;

export interface WalkGrid {
  cols: number;
  rows: number;
  isWalkable(cx: number, cy: number): boolean;
}

/** Cells covered by player-placed furniture that avatars walk around (rebuilt by ItemLayer.sync). */
export function buildOccupancy(cat: Catalog, rows: RoomItem[]): Set<number> {
  const occ = new Set<number>();
  for (const row of rows) {
    const it = cat.byId.get(row.item_id);
    if (!it || it.layer !== "furniture" || hasTag(it, TAG_STAIRS) || hasTag(it, TAG_RUINED)) continue;
    if (row.placed_by === SEED_PLAYER) continue;
    for (const [x, y] of footprintOf(cat, row)) occ.add(cellKey(x, y));
  }
  return occ;
}

export function roomWalkGrid(cat: Catalog, room: Room, occupied: ReadonlySet<number>): WalkGrid {
  const blocked = new Set(room.blocked.map(([x, y]) => cellKey(x, y)));
  return {
    cols: room.cols,
    rows: room.rows,
    isWalkable(cx, cy) {
      if (cx < 0 || cy < room.wall_rows || cx >= room.cols || cy >= room.rows) return false;
      const k = cellKey(cx, cy);
      if (blocked.has(k)) return false;
      if (cat.tiles.interior[floorKeyAt(room, cx, cy)]?.walk === false) return false;
      // furniture blocks unless the cell is an exit (stairs and doors are furniture you step onto)
      return !occupied.has(k) || exitAt(room, cx, cy) !== null;
    },
  };
}

export function mapWalkGrid(cat: Catalog, map: MapData, blocked: ReadonlySet<number>): WalkGrid {
  const ground = map.layers.ground, deco = map.layers.deco;
  return {
    cols: map.cols,
    rows: map.rows,
    isWalkable(cx, cy) {
      if (cx < 0 || cy < 0 || cx >= map.cols || cy >= map.rows) return false;
      if (blocked.has(cellKey(cx, cy))) return false;
      const key = deco?.[cy]?.[cx] ?? ground?.[cy]?.[cx];
      return !key || cat.tiles.map[key]?.walk !== false;
    },
  };
}

/** The tile key an avatar stands on in the map (deco over ground), for footsteps. */
export function mapTileAt(map: MapData, cx: number, cy: number): string | null {
  return map.layers.deco?.[cy]?.[cx] ?? map.layers.ground?.[cy]?.[cx] ?? null;
}

const DIRS4: [number, number][] = [[1, 0], [-1, 0], [0, 1], [0, -1]];

/** Shortest 4-neighbour path from `from` to `to` (waypoints, excluding `from`). When `to` cannot be
 *  reached (furniture, water, another room) the path leads to the reachable cell closest to it, so
 *  tapping a table walks up to the table. Empty when there is nowhere better to go. */
export function pathToward(grid: WalkGrid, from: Cell, to: Cell): Cell[] {
  const W = grid.cols, H = grid.rows;
  if (from.cx < 0 || from.cy < 0 || from.cx >= W || from.cy >= H) return [];
  const idx = (cx: number, cy: number) => cy * W + cx;
  const prev = new Int32Array(W * H).fill(-1);
  const dist = new Int32Array(W * H).fill(-1);
  const start = idx(from.cx, from.cy);
  dist[start] = 0;
  const queue: number[] = [start];
  let head = 0;
  const target = to.cx >= 0 && to.cy >= 0 && to.cx < W && to.cy < H ? idx(to.cx, to.cy) : -1;
  // best fallback: (manhattan distance to `to`, then bfs distance)
  let best = start, bestM = Math.abs(from.cx - to.cx) + Math.abs(from.cy - to.cy);
  while (head < queue.length) {
    const cur = queue[head++];
    if (cur === target) { best = cur; break; }
    const cx = cur % W, cy = (cur - cx) / W;
    for (const [dx, dy] of DIRS4) {
      const nx = cx + dx, ny = cy + dy;
      if (!grid.isWalkable(nx, ny)) continue;
      const n = idx(nx, ny);
      if (dist[n] >= 0) continue;
      dist[n] = dist[cur] + 1;
      prev[n] = cur;
      queue.push(n);
      const m = Math.abs(nx - to.cx) + Math.abs(ny - to.cy);
      if (m < bestM) { bestM = m; best = n; }
    }
  }
  const out: Cell[] = [];
  for (let n = best; n !== start && n >= 0; n = prev[n]) out.push({ cx: n % W, cy: Math.floor(n / W) });
  return out.reverse();
}
