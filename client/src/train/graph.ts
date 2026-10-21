/** Room-graph helpers over the engine's map rows (pure; the intruder bar and the clue overlay both use them). */

import type { MapRow } from "./api";

/** Rooms by BFS distance from `from` over the map's adjacency. */
export function distances(rows: MapRow[], from: string): Map<string, number> {
  const adj = new Map(rows.map((r) => [r.room, r.neighbors.split(",").filter(Boolean)]));
  const d = new Map<string, number>([[from, 0]]);
  const q = [from];
  while (q.length) {
    const cur = q.shift()!;
    for (const n of adj.get(cur) ?? []) if (!d.has(n)) { d.set(n, d.get(cur)! + 1); q.push(n); }
  }
  return d;
}

/** The door `edge` ("A1-A2") lies on a shortest way from `from` to `to`. */
export function edgeOnPath(rows: MapRow[], from: string, to: string, edge: string): boolean {
  const [a, b] = edge.split("-");
  const ds = distances(rows, from), dt = distances(rows, to);
  const total = ds.get(to);
  if (total === undefined) return false;
  const via = (x: string, y: string) => (ds.get(x) ?? Infinity) + 1 + (dt.get(y) ?? Infinity) === total;
  return via(a, b) || via(b, a);
}
