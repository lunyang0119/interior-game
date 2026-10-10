/** Client mirror of server/app/placement.py. Only used to colour the ghost; the server decides. */

import { canHang, collisionLayer, faceRows, isPartition, onWall, tileWalkable, widthOf, type Catalog, type Room, type RoomItem } from "../catalog";
import { footprint } from "./grid";

export interface Check { ok: boolean; code?: string; parentUid: number | null }

function key(c: [number, number]): number {
  return c[1] * 10_000 + c[0];
}

export function footprintOf(cat: Catalog, row: RoomItem): [number, number][] {
  const it = cat.byId.get(row.item_id);
  if (!it) return [[row.x, row.y]];
  return footprint(row.x, row.y, widthOf(it, row.span), it.h);
}

/** Cells of a partition's visible wall face (its columns, `faceRows` rows up from the footprint bottom); empty otherwise. */
export function partitionFace(cat: Catalog, row: RoomItem): [number, number][] {
  const it = cat.byId.get(row.item_id);
  if (!it || !isPartition(it)) return [];
  const bottom = row.y + it.h - 1;
  const rows = faceRows(it);
  return footprint(row.x, bottom - rows + 1, it.w, rows);
}

/** The partition a wall decor with this footprint hangs on (every cell on some partition's face; the one under
 *  the first cell is the parent), or null. Mirrors placement.hanger_of. */
export function hangerOf(cat: Catalog, others: RoomItem[], cells: [number, number][]): RoomItem | null {
  let first: RoomItem | null = null;
  const covered = new Set<number>();
  for (const o of others) {
    const face = partitionFace(cat, o);
    if (!face.length) continue;
    if (!first && face.some((c) => c[0] === cells[0][0] && c[1] === cells[0][1])) first = o;
    for (const c of face) covered.add(key(c));
  }
  return first && cells.every((c) => covered.has(key(c))) ? first : null;
}

export function checkPlace(cat: Catalog, room: Room, others: RoomItem[], itemId: string, x: number, y: number, span?: number | null): Check {
  const it = cat.byId.get(itemId);
  if (!it) return { ok: false, code: "unknown_item", parentUid: null };
  if (span != null && (it.layer !== "wallpaper" || span < 1 || span > room.cols)) return { ok: false, code: "bad_span", parentUid: null };
  const cells = footprint(x, y, widthOf(it, span), it.h);
  const blocked = new Set(room.blocked.map((b) => key([b[0], b[1]])));
  for (const c of cells) {
    if (c[0] < 0 || c[1] < 0 || c[0] >= room.cols || c[1] >= room.rows || blocked.has(key(c))) {
      return { ok: false, code: "out_of_bounds", parentUid: null };
    }
    // furniture, partitions, floor patterns and rugs cannot sit on unwalkable tiles (water etc.) — mirrors placement.py
    const group = collisionLayer(it);
    if ((group === "furniture" || group === "floor" || group === "rug") && !tileWalkable(cat, room, c[0], c[1])) {
      return { ok: false, code: "out_of_bounds", parentUid: null };
    }
  }
  const types = cells.map((c) => (c[1] < room.wall_rows ? "wall" : "floor"));
  const want = onWall(it) ? "wall" : "floor";
  // wall decor off the wall rows may hang on a partition's face instead; that partition becomes its parent
  let hanger: RoomItem | null = null;
  if (types.some((t) => t !== want)) {
    if (canHang(it) && types.every((t) => t === "floor")) hanger = hangerOf(cat, others, cells);
    if (!hanger) return { ok: false, code: "bad_cell_type", parentUid: null };
  }
  const cellSet = new Set(cells.map(key));

  if (it.layer !== "surface_item") {
    for (const o of others) {
      const oi = cat.byId.get(o.item_id);
      if (!oi || collisionLayer(oi) !== collisionLayer(it)) continue;
      if (footprintOf(cat, o).some((c) => cellSet.has(key(c)))) return { ok: false, code: "collision", parentUid: null };
    }
    return { ok: true, parentUid: hanger?.uid ?? null };
  }

  const surfaces = others.filter((o) => { const oi = cat.byId.get(o.item_id); return oi?.layer === "furniture" && oi.is_surface; });
  const surfaceItems = others.filter((o) => cat.byId.get(o.item_id)?.layer === "surface_item");
  const parents = new Set<number>();
  for (const c of cells) {
    const under = surfaces.filter((o) => footprintOf(cat, o).some((oc) => oc[0] === c[0] && oc[1] === c[1]));
    if (under.length !== 1) return { ok: false, code: "needs_surface", parentUid: null };
    parents.add(under[0].uid);
    if (surfaceItems.some((o) => footprintOf(cat, o).some((oc) => oc[0] === c[0] && oc[1] === c[1]))) {
      return { ok: false, code: "surface_occupied", parentUid: null };
    }
  }
  if (parents.size !== 1) return { ok: false, code: "spans_multiple_surfaces", parentUid: null };
  return { ok: true, parentUid: [...parents][0] };
}

export function hasChildren(uid: number, rows: RoomItem[]): boolean {
  return rows.some((r) => r.parent_uid === uid);
}
