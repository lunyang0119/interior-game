/** Client mirror of server/app/placement.py. Only used to colour the ghost; the server decides. */

import type { Catalog, RoomItem } from "../catalog";
import { isWallLayer } from "./depth";
import { footprint } from "./grid";

export interface Check { ok: boolean; code?: string; parentUid: number | null }

function key(c: [number, number]): number {
  return c[1] * 10_000 + c[0];
}

export function footprintOf(cat: Catalog, row: RoomItem): [number, number][] {
  const it = cat.byId.get(row.item_id);
  if (!it) return [[row.x, row.y]];
  return footprint(row.x, row.y, it.w, it.h);
}

export function checkPlace(cat: Catalog, others: RoomItem[], itemId: string, x: number, y: number): Check {
  const it = cat.byId.get(itemId);
  if (!it) return { ok: false, code: "unknown_item", parentUid: null };
  const room = cat.room;
  const cells = footprint(x, y, it.w, it.h);
  const blocked = new Set(room.blocked.map((b) => key([b[0], b[1]])));
  for (const c of cells) {
    if (c[0] < 0 || c[1] < 0 || c[0] >= room.cols || c[1] >= room.rows || blocked.has(key(c))) {
      return { ok: false, code: "out_of_bounds", parentUid: null };
    }
    const type = c[1] < room.wall_rows ? "wall" : "floor";
    if (isWallLayer(it.layer) !== (type === "wall")) return { ok: false, code: "bad_cell_type", parentUid: null };
  }
  const cellSet = new Set(cells.map(key));

  if (it.layer !== "surface_item") {
    for (const o of others) {
      const oi = cat.byId.get(o.item_id);
      if (!oi || oi.layer !== it.layer) continue;
      if (footprintOf(cat, o).some((c) => cellSet.has(key(c)))) return { ok: false, code: "collision", parentUid: null };
    }
    return { ok: true, parentUid: null };
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
