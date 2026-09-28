import Phaser from "phaser";
import { api } from "../api";
import { Footsteps, SFX_VOL, stepKindFor } from "../audio/sfx";
import { Avatar } from "../avatar/Avatar";
import { ensureAvatarTextures } from "../avatar/AvatarLoader";
import { RemoteAvatars } from "../avatar/RemoteAvatars";
import { bus, toast } from "../bus";
import { DOCK_ROOM, MAP_ROOM, type Catalog, type MapData, type MapPlace } from "../catalog";
import { Gestures } from "../input/Gestures";
import { dirDelta, WalkKeys } from "../input/Keyboard";
import { depthOf, TILE_DEPTH } from "../room/depth";
import { CELL, worldToCell } from "../room/grid";
import { cellKey, mapTileAt, mapWalkGrid, pathToward, type WalkGrid } from "../room/walk";
import { catalog, state } from "../state";
import { socket } from "../ws";
import { CameraController } from "./CameraController";

export const MAP_ATLAS = "map";
const MARKER = "icon_exclamation";
const CHUNK = 64; // cells per RenderTexture, keeps textures well under GPU limits on huge maps
const MARKER_REFRESH_MS = 60_000;
const BG_FADE_MS = 500;
const BG_DEPTH = TILE_DEPTH - 10; // under the tiles; the map's unpainted cells let it show through
const MAP_ZOOM_HINT = 3;
const STEP_HEAR_CELLS = 10;
const bgKey = (name: string) => `mapbg-${name}`;

export interface MapSceneData { from?: string }

/** Overworld: tiles + houses from data/map.json, walk to a door → "들어가시겠어요?" → room / dock. */
export class MapScene extends Phaser.Scene {
  private cat!: Catalog;
  private map!: MapData;
  private me: Avatar | null = null;
  private remotes!: RemoteAvatars;
  private cam!: CameraController;
  private gestures!: Gestures;
  private keys!: WalkKeys;
  private grid!: WalkGrid;
  private steps = new Footsteps();
  private unsub: (() => void)[] = [];
  private blocked = new Set<number>();
  private doors = new Map<number, MapPlace>();
  private markers = new Map<string, Phaser.GameObjects.Image>(); // by place room id
  private markerTimer: number | null = null;
  private spawn = { x: 0, y: 0 };
  private asking: MapPlace | null = null;
  private keyWalking = false;
  /** Fixed (screen-space) backdrop: `bgFront` is what shows, `bgBack` fades in on a zone change. */
  private bgFront: Phaser.GameObjects.Image | null = null;
  private bgBack: Phaser.GameObjects.Image | null = null;
  private bgName: string | null = null;
  private bgCell = { x: -1, y: -1 };

  constructor() {
    super("Map");
  }

  init(data: MapSceneData): void {
    this.cat = catalog();
    this.map = this.cat.map!;
    // come out of the door of the place we just left; otherwise the map's own spawn
    const place = data.from ? this.map.places.find((p) => p.room === data.from) : null;
    this.spawn = place?.spawn ?? this.map.spawn;
    state.roomId = MAP_ROOM;
    this.asking = null;
  }

  /** Backdrops are plain PNGs outside the atlas; fetch the ones this map mentions (once per texture). */
  preload(): void {
    const names = new Set<string>([...(this.map.bg_zones ?? []).map((z) => z.bg)]);
    if (this.map.bg_default) names.add(this.map.bg_default);
    for (const n of names) if (!this.textures.exists(bgKey(n))) this.load.image(bgKey(n), `/gen/mapbg/${n}.png`);
  }

  create(): void {
    const { cols, rows } = this.map;
    this.cameras.main.setBackgroundColor("#1b1b24");
    this.cam = new CameraController(this, { worldW: cols * CELL, worldH: rows * CELL, zoomHint: MAP_ZOOM_HINT });
    this.cam.onZoom = () => this.refitBg();
    this.bgCell = { x: -1, y: -1 };
    this.bgName = null;
    this.bgFront = this.bgBack = null;
    this.setBackground(this.bgFor(this.spawn.x, this.spawn.y), false);
    this.drawTiles();
    this.drawObjects();
    this.grid = mapWalkGrid(this.cat, this.map, this.blocked);
    this.remotes = new RemoteAvatars(this, this.cat.chars);
    this.remotes.onCell = (id, cx, cy) => this.footstep(id, cx, cy, this.hearing(cx, cy));
    bus.emit("room:changed", { id: MAP_ROOM, name: "바깥", ruined: 0 });
    bus.emit("scene:changed", { scene: "map" });

    this.bindInput();
    this.bindBus();
    void this.refreshMarkers();
    this.markerTimer = window.setInterval(() => { if (!socket.connected) void this.refreshMarkers(); }, MARKER_REFRESH_MS);

    if (state.id && state.token) {
      void this.spawnMe();
      this.bindSocket();
      if (socket.connected) this.enterPresence();
    }
    this.publishOnline();
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.teardown());
    bus.emit("scene:ready");
  }

  // ---------------------------------------------------------------- fixed backdrop + zones

  private bgFor(cx: number, cy: number): string | null {
    let hit: string | null = this.map.bg_default ?? null;
    for (const z of this.map.bg_zones ?? []) if (cx >= z.x && cx < z.x + z.w && cy >= z.y && cy < z.y + z.h) hit = z.bg;
    return hit;
  }

  /** A screen-space image scaled to cover the viewport (it never scrolls with the map). */
  private makeBg(name: string): Phaser.GameObjects.Image | null {
    if (!this.textures.exists(bgKey(name))) return null;
    const img = this.add.image(0, 0, bgKey(name)).setScrollFactor(0).setDepth(BG_DEPTH);
    this.fitBg(img);
    return img;
  }

  /** scrollFactor-0 objects are still scaled by the camera zoom, so cover the view at 1/zoom. */
  private fitBg(img: Phaser.GameObjects.Image): void {
    const vw = this.scale.width, vh = this.scale.height;
    img.setPosition(vw / 2, vh / 2).setScale(Math.max(vw / img.width, vh / img.height) / this.cam.zoom);
  }

  private refitBg(): void {
    if (this.bgFront) this.fitBg(this.bgFront);
    if (this.bgBack) this.fitBg(this.bgBack);
  }

  private setBackground(name: string | null, fade: boolean): void {
    if (name === this.bgName) return;
    this.bgName = name;
    const next = name ? this.makeBg(name) : null;
    if (!fade) {
      this.bgFront?.destroy();
      this.bgBack?.destroy();
      this.bgBack = null;
      this.bgFront = next;
      return;
    }
    // cross-fade: the new one rises over the old one, then the old one goes
    this.bgBack?.destroy();
    this.bgBack = next;
    if (next) next.setAlpha(0).setDepth(BG_DEPTH + 1);
    const old = this.bgFront;
    this.bgFront = next;
    this.tweens.add({
      targets: [next, old].filter(Boolean),
      alpha: (t: Phaser.GameObjects.Image) => (t === next ? 1 : 0),
      duration: BG_FADE_MS,
      ease: "Sine.easeInOut",
      onComplete: () => { old?.destroy(); if (this.bgBack === next) this.bgBack = null; next?.setDepth(BG_DEPTH); },
    });
  }

  private updateBackground(): void {
    if (!this.me) return;
    const { cx, cy } = this.me.footCell();
    if (cx === this.bgCell.x && cy === this.bgCell.y) return;
    this.bgCell = { x: cx, y: cy };
    this.setBackground(this.bgFor(cx, cy), true);
  }

  // ---------------------------------------------------------------- drawing

  private drawTiles(): void {
    const { cols, rows, layers } = this.map;
    const order = ["ground", "deco", ...Object.keys(layers).filter((k) => k !== "ground" && k !== "deco")];
    for (let cy0 = 0; cy0 < rows; cy0 += CHUNK) {
      for (let cx0 = 0; cx0 < cols; cx0 += CHUNK) {
        const w = Math.min(CHUNK, cols - cx0), h = Math.min(CHUNK, rows - cy0);
        const rt = this.add.renderTexture(cx0 * CELL, cy0 * CELL, w * CELL, h * CELL).setOrigin(0).setDepth(TILE_DEPTH);
        rt.beginDraw();
        for (const name of order) {
          const grid = layers[name];
          if (!grid) continue;
          for (let cy = 0; cy < h; cy++) {
            const row = grid[cy0 + cy];
            if (!row) continue;
            for (let cx = 0; cx < w; cx++) {
              const key = row[cx0 + cx];
              if (key && this.textures.get(MAP_ATLAS).has(key)) rt.batchDrawFrame(MAP_ATLAS, key, cx * CELL, cy * CELL);
            }
          }
        }
        rt.endDraw();
      }
    }
    for (const [bx, by] of this.map.blocked) this.blocked.add(cellKey(bx, by));
  }

  /** Places and decos share the editor's rules: bottom-left anchored box, rot in 90° steps, flip = mirror. */
  private drawObj(sprite: string, x: number, y: number, hCells: number, rot: number, flip: boolean, depth: number): void {
    const frame = this.textures.get(MAP_ATLAS).get(sprite);
    if (!frame) return;
    const turned = rot % 180 !== 0;
    const bw = turned ? frame.height : frame.width, bh = turned ? frame.width : frame.height;
    const px = x * CELL + bw / 2, py = (y + hCells) * CELL - bh / 2;
    this.add.image(px, py, MAP_ATLAS, sprite).setAngle(rot).setFlipX(flip).setDepth(depth);
  }

  private cellsOf(sprite: string, rot: number): { w: number; h: number } {
    const f = this.textures.get(MAP_ATLAS).get(sprite);
    if (!f) return { w: 1, h: 1 };
    const turned = rot % 180 !== 0;
    return { w: Math.ceil((turned ? f.height : f.width) / CELL), h: Math.ceil((turned ? f.width : f.height) / CELL) };
  }

  private drawObjects(): void {
    for (const p of this.map.places) {
      if (p.sprite) this.drawObj(p.sprite, p.x, p.y, p.h, p.rot ?? 0, !!p.flip, depthOf(p.y + p.h - 1, 10));
      const doorSet = new Set(p.doors.map(([dx, dy]) => cellKey(dx, dy)));
      for (let cy = p.y; cy < p.y + p.h; cy++) for (let cx = p.x; cx < p.x + p.w; cx++) {
        const k = cellKey(cx, cy);
        if (!doorSet.has(k)) this.blocked.add(k); // the building itself is solid, its doors are not
      }
      for (const k of doorSet) this.doors.set(k, p);
    }
    for (const d of this.map.decos) {
      const c = this.cellsOf(d.sprite, d.rot ?? 0);
      // flat decos (paths, 1 cell tall) sit under everything; taller ones y-sort with avatars
      const depth = c.h <= 1 && c.w <= 1 ? TILE_DEPTH + 1 : depthOf(d.y + c.h - 1, 10);
      this.drawObj(d.sprite, d.x, d.y, c.h, d.rot ?? 0, !!d.flip, depth);
    }
  }

  // ---------------------------------------------------------------- markers (rooms with junk left)

  private async refreshMarkers(): Promise<void> {
    try {
      const { rooms } = await api.rooms();
      if (!this.scene.isActive()) return;
      const ruined = new Map(rooms.map((r) => [r.id, r.ruined]));
      for (const p of this.map.places) {
        const n = ruined.get(p.room) ?? 0;
        const has = this.markers.get(p.room);
        if (n > 0 && !has && this.textures.get(MAP_ATLAS).has(MARKER)) {
          const m = this.add.image((p.x + p.w / 2) * CELL, p.y * CELL - 2, MAP_ATLAS, MARKER).setOrigin(0.5, 1).setDepth(depthOf(p.y + p.h, 50));
          this.tweens.add({ targets: m, y: m.y - 4, duration: 600, yoyo: true, repeat: -1, ease: "Sine.easeInOut" });
          this.markers.set(p.room, m);
        } else if (n === 0 && has) {
          has.destroy();
          this.markers.delete(p.room);
        }
      }
    } catch { /* offline: markers just stay as they were */ }
  }

  // ---------------------------------------------------------------- avatar / presence

  private async spawnMe(): Promise<void> {
    await ensureAvatarTextures(this, state.avatar, this.cat.chars);
    if (!this.scene.isActive()) return;
    this.me = new Avatar(this, this.cat.chars, state.avatar, this.spawn.x, this.spawn.y, state.id ?? "");
    this.me.onStep = (x, y, dir, moving) => socket.sendMove(x, y, dir, moving);
    this.me.onArrive = () => { this.keyWalking = false; this.checkDoor(); };
    this.me.onCell = (cx, cy) => {
      this.footstep(state.id ?? "me", cx, cy, 1);
      if (this.keyWalking) this.checkDoor();
    };
    this.cam.follow(this.me);
    this.publishOnline();
  }

  private enterPresence(): void {
    const s = this.me ? { x: this.me.cellX, y: this.me.cellY } : { x: this.spawn.x + 0.5, y: this.spawn.y + 1 };
    socket.sendEnter(MAP_ROOM, s.x, s.y);
  }

  private bindSocket(): void {
    this.unsub.push(
      socket.on("hello", () => this.enterPresence()),
      socket.on("entered", (m) => {
        if (m.room !== MAP_ROOM) return;
        this.remotes.reset(m.online);
        this.publishOnline();
        if (this.me) socket.sendMove(this.me.cellX, this.me.cellY, this.me.dir, false);
      }),
      socket.on("join", (m) => { void this.remotes.join(m).then(() => this.publishOnline()); this.publishOnline(); }),
      socket.on("leave", (m) => { this.remotes.leave(m.id); this.steps.forget(m.id); this.publishOnline(); }),
      socket.on("move", (m) => this.remotes.move(m.id, m.x, m.y, m.dir, m.moving)),
      socket.on("avatar_look", (m) => void this.remotes.look(m.id, m.avatar)),
      socket.on("room", (m) => {
        if (typeof m.balance === "number" && m.balance !== state.balance) { state.balance = m.balance; bus.emit("money", { balance: m.balance }); }
        void this.refreshMarkers(); // somebody sold junk somewhere: a marker may go away
      }),
      socket.on("money", (m) => { if (m.balance !== state.balance) { state.balance = m.balance; bus.emit("money", { balance: m.balance }); } }),
      socket.on("open", () => this.publishOnline()),
      socket.on("close", () => { this.remotes.reset([]); this.publishOnline(); }),
    );
  }

  private publishOnline(): void {
    const n = this.remotes.count + (this.me && socket.connected ? 1 : 0);
    state.online = n;
    bus.emit("online", { count: n });
  }

  private bindBus(): void {
    this.unsub.push(
      bus.on("avatar:saved", (look) => void ensureAvatarTextures(this, look, this.cat.chars).then(() => this.me?.setLook(look))),
      bus.on("map:enter-answer", ({ yes }) => this.answer(yes)),
    );
  }

  // ---------------------------------------------------------------- walking

  private walkTo(cx: number, cy: number): boolean {
    if (!this.me) return false;
    const path = pathToward(this.grid, this.me.footCell(), { cx, cy });
    if (!path.length) return false;
    this.keyWalking = false;
    this.me.walkPath(path);
    this.cam.follow(this.me);
    return true;
  }

  private walkByKeys(): void {
    const d = this.keys.held();
    if (!d || !this.me || this.asking) return;
    if (this.me.walking && this.me.pending > 0) return;
    const from = this.me.walking ? this.me.targetCell()! : this.me.footCell();
    const [dx, dy] = dirDelta(d);
    const next = { cx: from.cx + dx, cy: from.cy + dy };
    if (this.grid.isWalkable(next.cx, next.cy)) {
      this.keyWalking = true;
      if (this.me.walking) this.me.extend(next); else this.me.walkPath([next]);
      this.cam.follow(this.me);
    } else if (!this.me.walking) {
      this.me.face(d);
    }
  }

  private footstep(id: string, cx: number, cy: number, gain: number): void {
    const key = mapTileAt(this.map, cx, cy);
    const kind = stepKindFor(key ? this.cat.tiles.map[key] : undefined, "grass");
    this.steps.trigger(id, kind, SFX_VOL.step * gain);
  }

  private hearing(cx: number, cy: number): number {
    if (!this.me) return 0;
    const c = this.me.footCell();
    return Phaser.Math.Clamp(1 - (Math.abs(c.cx - cx) + Math.abs(c.cy - cy)) / STEP_HEAR_CELLS, 0, 1);
  }

  // ---------------------------------------------------------------- input / doors

  private bindInput(): void {
    this.keys = new WalkKeys();
    this.gestures = new Gestures(this, {
      tap: (p) => {
        if (!this.me || this.asking) return;
        const w = this.cam.screenToWorld(p.x, p.y);
        const { cx, cy } = worldToCell(w.x, w.y);
        if (cx < 0 || cy < 0 || cx >= this.map.cols || cy >= this.map.rows) return;
        if (!this.walkTo(cx, cy)) toast("거긴 갈 수 없어요");
      },
      pan: (dx, dy) => this.cam.panBy(dx, dy),
      pinch: (ratio, mid) => this.cam.pinch(ratio, mid),
      pinchEnd: () => this.cam.pinchEnd(),
      wheel: (dy, p) => this.cam.wheel(dy, p),
    });
  }

  private checkDoor(): void {
    if (!this.me || this.asking) return;
    const { cx, cy } = this.me.footCell();
    const place = this.doors.get(cellKey(cx, cy));
    if (!place) return;
    this.asking = place;
    const room = this.cat.rooms.get(place.room);
    const name = place.room === DOCK_ROOM ? "부두" : room?.name || place.name || place.room;
    bus.emit("map:enter-ask", { name });
  }

  private answer(yes: boolean): void {
    const place = this.asking;
    this.asking = null;
    if (!place || !yes) return;
    bus.emit("map:enter", { room: place.room });
  }

  update(time: number, delta: number): void {
    this.walkByKeys();
    this.me?.update(time, delta);
    this.remotes.update(time, delta);
    this.cam.update();
    this.updateBackground();
  }

  private teardown(): void {
    for (const off of this.unsub) off();
    this.unsub = [];
    if (this.markerTimer !== null) clearInterval(this.markerTimer);
    this.gestures.destroy();
    this.keys.destroy();
    this.cam.destroy();
    this.remotes.destroy();
    this.me?.destroy();
    this.me = null;
    this.markers.clear();
    this.blocked.clear();
    this.doors.clear();
    bus.emit("map:enter-ask", { name: "" }); // closes the panel if it was open
  }
}
