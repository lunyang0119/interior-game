export type Layer = "wall" | "floor" | "furniture" | "surface_item";

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

/** One avatar layer. `groups` = indices that share a style (colour variants); `none` = index 0 means "nothing". */
export interface LayerSpec { count: number; label?: string; none?: boolean; groups?: number[][]; names?: string[] }

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
}

export interface AvatarLook {
  skin: number;
  eyes: number;
  hair: number;
  hair_color: number; // legacy, always 0
  outfit: number;
  acc: number;
}

export const AVATAR_LAYERS: (keyof AvatarLook)[] = ["skin", "eyes", "outfit", "hair", "acc"];
export const DEFAULT_LOOK: AvatarLook = { skin: 0, eyes: 0, hair: 0, hair_color: 0, outfit: 0, acc: 0 };

export const Z_SCALE: Record<Layer, number> = { wall: 0, floor: 0, furniture: 10, surface_item: 20 };
export const Z_AVATAR = 15;

export function makeCatalog(raw: { items: Item[]; room: Room; chars: Chars }): Catalog {
  return { items: raw.items, byId: new Map(raw.items.map((i) => [i.id, i])), room: raw.room, chars: raw.chars };
}
