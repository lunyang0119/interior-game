export const CELL = 16;

export function cellToWorld(cx: number, cy: number): { x: number; y: number } {
  return { x: cx * CELL, y: cy * CELL };
}

export function worldToCell(wx: number, wy: number): { cx: number; cy: number } {
  return { cx: Math.floor(wx / CELL), cy: Math.floor(wy / CELL) };
}

/** Anchor cell so that a w×h footprint is centred under the pointer. */
export function anchorUnderPointer(wx: number, wy: number, w: number, h: number): { cx: number; cy: number } {
  return { cx: Math.floor(wx / CELL - (w - 1) / 2), cy: Math.floor(wy / CELL - (h - 1) / 2) };
}

export function footprint(x: number, y: number, w: number, h: number): [number, number][] {
  const out: [number, number][] = [];
  for (let cy = y; cy < y + h; cy++) for (let cx = x; cx < x + w; cx++) out.push([cx, cy]);
  return out;
}
