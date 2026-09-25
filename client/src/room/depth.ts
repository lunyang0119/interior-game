import type { Layer } from "../catalog";

/** depth = sortRow * 100 + zScale. sortRow is the bottom row of the footprint (feet row for avatars). */
export function depthOf(sortRow: number, zScale: number): number {
  return sortRow * 100 + zScale;
}

/** Room base tiles sit below every item and avatar. */
export const TILE_DEPTH = -1000;

/** Row used for y-sorting an item. Rugs and wallpaper never overlap anything standing on / in front of
 *  them, so they ignore their footprint row and always sort below avatars (which start at row 0). */
export function sortRowFor(layer: Layer | undefined, bottomRow: number): number {
  return layer === "floor" || layer === "wall" ? -1 : bottomRow;
}
