export type Layer = "wallpaper" | "wall" | "floor" | "furniture" | "surface_item";

export interface Item {
  id: string;
  name: string;
  price: number;
  sprite: string;
  w: number;
  h: number;
  layer: Layer;
  is_surface: boolean;
  surface_offset_y: number;
}

export interface Room {
  cols: number;
  rows: number;
  wall_rows: number;
  spawn: { x: number; y: number };
  blocked: number[][];
  zoom: number;
  tiles: { wall: string[]; wall_left: string[]; wall_right: string[]; floor: string };
}

/** One avatar layer. `groups` = indices that share a style (colour variants); `none` = index that means "nothing";
 *  `exclusive` = when not none, this layer is drawn alone (premade characters). */
export interface LayerSpec { count: number; label?: string; none?: number; exclusive?: boolean; groups?: number[][]; names?: string[] }

export interface Chars {
  frameW: number;
  frameH: number;
  anims: Record<string, [number, number]>;
  layerOrder: string[];
  layers: Record<string, LayerSpec>;
}

export interface Catalog {
  items: Item[];
  byId: Map<string, Item>;
  room: Room;
  chars: Chars;
}

export interface RoomItem {
  uid: number;
  item_id: string;
  x: number;
  y: number;
  z: number;
  parent_uid: number | null;
  placed_by: string;
  ts: number;
  span?: number | null; // wallpaper: width in cells chosen when placed (null → item.w)
}

export interface AvatarLook {
  preset: number; // premade character, 0 = none
  skin: number;
  eyes: number;
  hair: number;
  hair_color: number; // legacy, always 0
  outfit: number;
  acc: number;
}

export const AVATAR_LAYERS: (keyof AvatarLook)[] = ["preset", "skin", "eyes", "outfit", "hair", "acc"];
export const DEFAULT_LOOK: AvatarLook = { preset: 0, skin: 0, eyes: 0, hair: 0, hair_color: 0, outfit: 0, acc: 0 };

/** Which (layer, idx) a look draws, bottom → top; honours none / exclusive. */
export function drawList(look: AvatarLook, chars: Chars): { layer: string; idx: number }[] {
  const out: { layer: string; idx: number }[] = [];
  for (const layer of chars.layerOrder) {
    const spec = chars.layers[layer];
    const count = spec?.count ?? 0;
    if (count <= 0) continue;
    const idx = Math.min(Math.max((look as unknown as Record<string, number>)[layer] ?? 0, 0), count - 1);
    if (spec.none !== undefined && idx === spec.none) continue;
    if (spec.exclusive) return [{ layer, idx }];
    out.push({ layer, idx });
  }
  return out;
}

export const Z_SCALE: Record<Layer, number> = { wallpaper: 0, wall: 1, floor: 0, furniture: 10, surface_item: 20 };
export const Z_AVATAR = 15;

/** Footprint width of a placed/ghost item: wallpaper stretches to `span`, everything else is fixed. */
export function widthOf(it: Item, span?: number | null): number {
  return it.layer === "wallpaper" && span ? span : it.w;
}

/** Wallpaper is priced per column; everything else per item. Mirrors server price_of(). */
export function priceOf(it: Item, span?: number | null): number {
  return it.layer === "wallpaper" ? it.price * widthOf(it, span) : it.price;
}

export function makeCatalog(raw: { items: Item[]; room: Room; chars: Chars }): Catalog {
  return { items: raw.items, byId: new Map(raw.items.map((i) => [i.id, i])), room: raw.room, chars: raw.chars };
}
