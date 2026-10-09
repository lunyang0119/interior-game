export type Layer = "wallpaper" | "wall" | "floor" | "furniture" | "surface_item";

/** Tags with rules (mirror server/app/catalog.py): ruined = seeded junk, sell only; fixed = part of the room. */
export const TAG_RUINED = "ruined";
export const TAG_FIXED = "fixed";
/** Tapping a stairs item walks to the exit it sits on instead of opening its menu. */
export const TAG_STAIRS = "stairs";
export const TAG_NOTE = "note"; // carries a text anyone can rewrite (ui/note.ts)
/** Owner id of items pre-placed by the server (never a real player). */
export const SEED_PLAYER = "$seed";
export const MAP_ROOM = "map";
export const DOCK_ROOM = "dock";

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
  tags?: string[];
  pair?: string | null;
}

/** Cells that lead somewhere else; `to` is a room id or "map", `spawn` is the arrival cell there. */
export interface Exit { x: number; y: number; w: number; h: number; to: string; spawn: { x: number; y: number } }

export interface Room {
  id: string;
  name: string;
  cols: number;
  rows: number;
  wall_rows: number;
  spawn: { x: number; y: number };
  blocked: number[][];
  zoom: number;
  tiles: { wall: string[]; wall_left: string[]; wall_right: string[]; floor: string };
  /** Per-cell floor tiles painted in the world editor (rows × cols); null cells fall back to tiles.floor. */
  floor?: (string | null)[][] | null;
  exits: Exit[];
  /** Restoration stages (mirror server/app/restore.py); progress comes from /api/rooms and the ws `progress` message. */
  restore?: Stage[];
}

export type NeedType = "ruined_zero" | "placed" | "deliver" | "pool";
export interface Need { type: NeedType; count?: number; layer?: string | null; tag?: string | null; item_id?: string | null; id?: string | null; amount?: number | null; label?: string }
export interface Reward { type: "unlock"; room: string }
export interface Stage { id: string; name: string; need: Need[]; reward: Reward[] }

/** Which room's stage opens `target` (a room id, "map" or "dock"); null when nothing locks it. */
export function unlockerOf(cat: Catalog, target: string): { room: Room; stage: Stage; index: number } | null {
  for (const room of cat.rooms.values()) {
    const stages = room.restore ?? [];
    for (let index = 0; index < stages.length; index++) {
      if (stages[index].reward.some((r) => r.room === target)) return { room, stage: stages[index], index };
    }
  }
  return null;
}

/** Display name of a place: a room's name, or the two scene rooms. */
export function placeName(cat: Catalog, id: string): string {
  if (id === MAP_ROOM) return "바깥";
  if (id === DOCK_ROOM) return "부두";
  return cat.rooms.get(id)?.name || id;
}

/** Footstep sound kinds a tile can carry (mirror preprocess TILE_STEPS). "none" = silent. */
export type StepKind = "wood" | "tile" | "grass" | "water" | "none";
/** Metadata set on a slice in the editor and shipped through the manifest: which sound a step makes, and whether avatars can enter. */
export interface TileInfo { step?: StepKind; walk?: boolean }

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

/** Overworld from data/map.json (world editor). Coordinates are map cells; sprites live in the map atlas. */
export interface MapPlace {
  room: string; // room id or "dock"
  name: string;
  sprite?: string | null;
  x: number;
  y: number;
  w: number;
  h: number;
  rot?: number;
  flip?: boolean;
  doors: [number, number][];
  spawn?: { x: number; y: number } | null;
}
export interface MapDeco { sprite: string; x: number; y: number; rot?: number; flip?: boolean }
/** Cells where the fixed backdrop `bg` (gen/mapbg/<bg>.png) shows; later zones win. */
export interface BgZone { x: number; y: number; w: number; h: number; bg: string }
export interface MapData {
  cols: number;
  rows: number;
  spawn: { x: number; y: number };
  layers: Record<string, (string | null)[][]>;
  blocked: number[][];
  places: MapPlace[];
  decos: MapDeco[];
  bg_default?: string | null;
  bg_zones?: BgZone[];
}

export interface Catalog {
  items: Item[];
  byId: Map<string, Item>;
  /** The base room (inn): where a session starts. */
  room: Room;
  rooms: Map<string, Room>;
  map: MapData | null;
  chars: Chars;
  /** Tile metadata by atlas ("interior" = room tiles, "map" = overworld tiles); only keys that carry any. */
  tiles: { interior: Record<string, TileInfo>; map: Record<string, TileInfo> };
  /** see assets.ts */
  assetVersion: string;
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
  room_id?: string;
  // note items only
  note?: string | null;
  note_by?: string | null;
  note_ts?: number | null;
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

export function hasTag(it: Item | undefined, tag: string): boolean {
  return !!it?.tags?.includes(tag);
}

/** Buyable in the shop: not junk, not part of the room. */
export function forSale(it: Item): boolean {
  return !hasTag(it, TAG_RUINED) && !hasTag(it, TAG_FIXED);
}

/** Footprint width of a placed/ghost item: wallpaper stretches to `span`, everything else is fixed. */
export function widthOf(it: Item, span?: number | null): number {
  return it.layer === "wallpaper" && span ? span : it.w;
}

/** Wallpaper is priced per column; everything else per item. Mirrors server price_of(). */
export function priceOf(it: Item, span?: number | null): number {
  return it.layer === "wallpaper" ? it.price * widthOf(it, span) : it.price;
}

/** The floor tile key drawn at a cell (painted grid first, then the room default). */
export function floorKeyAt(room: Room, cx: number, cy: number): string {
  return room.floor?.[cy]?.[cx] ?? room.tiles.floor;
}

/** Can an avatar stand on (and can furniture/rugs be placed on) the floor tile at a cell? */
export function tileWalkable(cat: Catalog, room: Room, cx: number, cy: number): boolean {
  return cat.tiles.interior[floorKeyAt(room, cx, cy)]?.walk !== false;
}

/** The exit (if any) covering a cell. */
export function exitAt(room: Room, cx: number, cy: number): Exit | null {
  return room.exits.find((e) => cx >= e.x && cx < e.x + e.w && cy >= e.y && cy < e.y + e.h) ?? null;
}

export interface RawCatalog {
  items: Item[]; room: Room; rooms?: Room[]; map?: MapData | null; chars: Chars;
  tiles?: { interior?: Record<string, TileInfo>; map?: Record<string, TileInfo> } | null;
  /** hash of the generated atlases/theme on the server; appended to /gen and /media URLs (see assets.ts) */
  asset_version?: string;
}

export function makeCatalog(raw: RawCatalog): Catalog {
  const list = (raw.rooms?.length ? raw.rooms : [raw.room]).map((r) => ({ ...r, exits: r.exits ?? [], name: r.name ?? r.id ?? "" }));
  const rooms = new Map(list.map((r) => [r.id, r]));
  const room = rooms.get(raw.room.id ?? "inn") ?? list[0];
  const tiles = { interior: raw.tiles?.interior ?? {}, map: raw.tiles?.map ?? {} };
  return { items: raw.items, byId: new Map(raw.items.map((i) => [i.id, i])), room, rooms, map: raw.map ?? null, chars: raw.chars, tiles,
    assetVersion: raw.asset_version ?? "" };
}
