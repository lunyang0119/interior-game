/** depth = sortRow * 100 + zScale. sortRow is the bottom row of the footprint (feet row for avatars). */
export function depthOf(sortRow: number, zScale: number): number {
  return sortRow * 100 + zScale;
}
