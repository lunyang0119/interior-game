import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { Footsteps, play, SFX, SFX_VOL, stepKindFor } from "../audio/sfx";
import { Avatar } from "../avatar/Avatar";
import { ensureAvatarTextures } from "../avatar/AvatarLoader";
import { RemoteAvatars } from "../avatar/RemoteAvatars";
import { bus, toast } from "../bus";
import { exitAt, floorKeyAt, hasTag, TAG_BOARD, TAG_FIXED, TAG_STAIRS, zoneAt, type Catalog, type Exit, type Layer, type Room } from "../catalog";
import { Gestures } from "../input/Gestures";
import { dirDelta, WalkKeys } from "../input/Keyboard";
import { InnCat } from "../npc/Cat";
import { GuestNpcs } from "../npc/GuestNpcs";
import { FX_DEPTH, TILE_DEPTH } from "../room/depth";
import { CELL, footprint, worldToCell } from "../room/grid";
import { ATLAS, ItemLayer } from "../room/ItemLayer";
import { MineFloor } from "../room/MineFloor";
import { PlacementController } from "../room/Placement";
import { footprintOf } from "../room/rules";
import { cellKey, pathToward, roomWalkGrid, type Cell, type WalkGrid } from "../room/walk";
import { catalog, isDebugAccount, setZone, state } from "../state";
import { socket } from "../ws";
import { CameraController } from "./CameraController";

const POLL_MS = 60_000;
const LONG_PRESS_MS = 400;
const TAP_SLOP = 14; // fingers wobble; keep the long-press alive within this radius
// a plain tap only opens the menu for these; rugs/wallpaper need a long press so tapping a rug still walks there
const TAP_MENU_LAYERS: ReadonlySet<Layer> = new Set<Layer>(["furniture", "surface_item"]);
const STEP_HEAR_CELLS = 10; // other people's footsteps fade out over this many cells

export interface RoomSceneData { id: string | null; room?: string; spawn?: { x: number; y: number }; floor?: number }

export class RoomScene extends Phaser.Scene {
  private cat!: Catalog;
  private room!: Room;
  private items!: ItemLayer;
  private placement!: PlacementController;
  private cam!: CameraController;
  private gestures!: Gestures;
  private keys!: WalkKeys;
  private steps = new Footsteps();
  private me: Avatar | null = null;
  private remotes!: RemoteAvatars;
  private guests!: GuestNpcs;
  /** The inn cat (only in the inn, only when the catalog carries a cat strip). */
  private innCat: InnCat | null = null;
  /** This mine floor's rocks/nodes/ladder (only in a room of kind "mine"); `pendingOre` = the node to pick once
   *  the walk toward it ends. `floor` is 1 outside the mine; the presence room is then just the room id. */
  private mine: MineFloor | null = null;
  private pendingOre: number | null = null;
  private floor = 1;
  private unsub: (() => void)[] = [];
  private pollTimer: number | null = null;
  private playerId: string | null = null;
  private spawn = { x: 0, y: 0 };
  private inflight: Promise<void> | null = null;
  /** Desktop: the ghost follows the mouse until the first click pins it; a drag moves it again. */
  private hoverFollow = false;
  private leaving = false;
  private ready = false;
  /** Bumped by init(): async work (avatar textures) started for an earlier run of this scene must not touch this one. */
  private gen = 0;
  /** Keyboard walking checks exits on every cell (there is no "arrival" while a key is held). */
  private keyWalking = false;

  constructor() {
    super("Room");
  }

  init(data: RoomSceneData): void {
    this.cat = catalog();
    this.playerId = data.id;
    this.room = this.cat.rooms.get(data.room ?? state.roomId) ?? this.cat.room;
    this.spawn = data.spawn ?? this.room.spawn;
    this.floor = this.room.kind === "mine" ? Math.max(1, data.floor ?? 1) : 1;
    state.roomId = this.room.id;
    state.mineFloor = this.floor;
    state.roomVersion = -1;
    state.ruined = 0; // the snapshot fills it in
    this.leaving = false;
    this.ready = false;
    this.gen++;
    this.inflight = null; // a request still running for the previous room must not be handed to this one
  }

  create(): void {
    this.drawRoom();
    // minZoom 1: zoom out as far as the room still fills the view; overscroll: drag a corner out from under the UI
    this.cam = new CameraController(this, { worldW: this.room.cols * CELL, worldH: this.room.rows * CELL, zoomHint: this.room.zoom, minZoom: 1, overscroll: 0.4 });
    this.items = new ItemLayer(this, this.cat);
    this.placement = new PlacementController(this, this.cat, this.room, this.items);
    this.placement.onRestart = () => { this.hoverFollow = true; }; // "+1": the fresh ghost follows the mouse again
    this.remotes = new RemoteAvatars(this, this.cat.chars);
    this.remotes.onCell = (id, cx, cy) => this.footstep(id, cx, cy, this.hearing(cx, cy));
    this.guests = new GuestNpcs(this, this.cat, this.room, () => this.walkGrid(), () => this.items.rows);
    if (this.cat.cat && this.room.id === this.cat.room.id) {
      this.innCat = new InnCat(this, this.cat.cat, this.room, () => this.walkGrid());
      void this.innCat.spawn();
    }
    if (this.room.kind === "mine") {
      this.mine = new MineFloor(this, this.floor, () => this.me?.footCell() ?? null, (b) => this.setBalance(b));
      this.mine.onLadder = () => this.checkLadder(); // a ladder opened under my feet counts right away
      void this.mine.load();
    }
    setZone(null); // until the avatar stands somewhere
    this.emitRoomChanged(state.ruined);

    this.bindBus();
    this.bindInput();
    void this.refreshRoom();
    this.pollTimer = window.setInterval(() => { if (!socket.connected) void this.refreshRoom(); }, POLL_MS);

    if (this.playerId && state.token) {
      void this.spawnMe();
      this.bindSocket();
      // the socket belongs to main.ts and outlives scenes: tell the server which room we are in now
      if (socket.connected) this.enterPresence();
    }
    this.publishOnline();

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.teardown());
  }

  // ---------------------------------------------------------------- room base

  /** Bakes the wall/floor tiles into one RenderTexture: 1 game object instead of cols×rows images per frame. */
  private drawRoom(): void {
    const { cols, rows, wall_rows, tiles } = this.room;
    const atlas = this.textures.get(ATLAS);
    const rt = this.add.renderTexture(0, 0, cols * CELL, rows * CELL).setOrigin(0).setDepth(TILE_DEPTH);
    rt.beginDraw();
    for (let cy = 0; cy < rows; cy++) {
      for (let cx = 0; cx < cols; cx++) {
        let key = floorKeyAt(this.room, cx, cy);
        if (cy < wall_rows) {
          const edge = cx === 0 && tiles.wall_left.length ? tiles.wall_left
            : cx === cols - 1 && tiles.wall_right.length ? tiles.wall_right : tiles.wall;
          key = edge[cy] ?? tiles.wall[cy];
        } else if (!atlas.has(key)) {
          key = tiles.floor; // painted tile not in this build of the atlas: fall back to the room default
        }
        rt.batchDrawFrame(ATLAS, key, cx * CELL, cy * CELL);
      }
    }
    rt.endDraw();
    this.cameras.main.setBackgroundColor("#1b1b24");
    this.drawFx();
  }

  /** Pixel-placed decorations from the room data (steam over the kettle…): static frames, or looping when the
   *  sprite is an anim slice (frames `<key>#i`, speed from catalog.anims). Always above items and avatars.
   *  Effects tied to a gimmick (`when`) belong to the train page; rooms have no gimmick state, so they are skipped. */
  private drawFx(): void {
    const atlas = this.textures.get(ATLAS);
    for (const f of this.room.fx ?? []) {
      if (f.when || !atlas.has(f.sprite)) continue; // placed with a newer build than this atlas: skip quietly
      const s = this.add.sprite(f.x, f.y, ATLAS, f.sprite).setOrigin(0).setDepth(FX_DEPTH);
      const spec = this.cat.anims[f.sprite];
      if (!spec || spec.frames < 2) continue;
      const key = `fx:${f.sprite}`;
      if (!this.anims.exists(key)) {
        const frames = Array.from({ length: spec.frames }, (_, i) => ({ key: ATLAS, frame: `${f.sprite}#${i}` }))
          .filter((fr) => atlas.has(fr.frame));
        if (frames.length < 2) continue;
        this.anims.create({ key, frames, frameRate: spec.fps, repeat: -1 });
      }
      s.play(key);
    }
  }

  // ---------------------------------------------------------------- data

  /** Fetches the room snapshot; concurrent calls share one request (place response + WS notify both ask). */
  refreshRoom(): Promise<void> {
    if (!this.inflight) {
      const p = this.doRefresh().finally(() => { if (this.inflight === p) this.inflight = null; });
      this.inflight = p;
    }
    return this.inflight;
  }

  private async doRefresh(): Promise<void> {
    let stale = false;
    try {
      const r = await api.room(this.room.id, state.roomVersion);
      if (!r) return; // 304
      if (r.room !== this.room.id) { stale = true; return; } // answer for a room we already left: say nothing about readiness
      state.roomVersion = r.version;
      this.items.sync(r.items);
      this.placement.revalidate();
      this.guests.sync();
      this.setRuined(r.ruined);
    } catch (e) {
      if (e instanceof ApiError && e.code !== "network") toast(msgFor(e.code));
    } finally {
      if (!stale) this.markReady();
    }
  }

  private markReady(): void {
    if (this.ready || !this.scene.isActive()) return;
    this.ready = true;
    bus.emit("scene:ready");
  }

  private setRuined(n: number | undefined): void {
    if (typeof n !== "number" || n === state.ruined) return;
    state.ruined = n;
    this.emitRoomChanged(n);
  }

  private emitRoomChanged(ruined: number): void {
    bus.emit("room:changed", { id: this.room.id, name: this.room.name, ruined, kind: this.room.kind ?? "room",
      floor: this.room.kind === "mine" ? this.floor : undefined });
  }

  /** The presence room: a mine floor is its own room ("mine#3"), everything else is the room id. */
  private presenceRoom(): string {
    return this.room.kind === "mine" ? `${this.room.id}#${this.floor}` : this.room.id;
  }

  private async spawnMe(): Promise<void> {
    const gen = this.gen;
    await ensureAvatarTextures(this, state.avatar, this.cat.chars);
    if (!this.scene.isActive() || gen !== this.gen || this.me) return; // the scene restarted meanwhile: that run spawns its own
    const s = this.spawn;
    this.me = new Avatar(this, this.cat.chars, state.avatar, s.x, s.y, this.playerId ?? "");
    this.me.onStep = (x, y, dir, moving) => socket.sendMove(x, y, dir, moving);
    this.me.onArrive = () => {
      this.keyWalking = false;
      this.checkExit();
      // walked up to an ore node: it becomes the 채광 target if we got close enough
      if (this.pendingOre !== null) { const seq = this.pendingOre; this.pendingOre = null; this.mine?.select(seq); }
      this.checkLadder();
    };
    this.me.onCell = (cx, cy) => {
      this.footstep(this.playerId ?? "me", cx, cy, 1);
      setZone(zoneAt(this.room, cx, cy)?.id ?? null);
      this.mine?.refreshTarget();
      if (this.keyWalking) { this.checkExit(); this.checkLadder(); }
    };
    const foot = this.me.footCell();
    setZone(zoneAt(this.room, foot.cx, foot.cy)?.id ?? null);
    this.cam.follow(this.me);
    this.publishOnline();
  }

  // ---------------------------------------------------------------- socket

  private enterPresence(): void {
    const s = this.me ? { x: this.me.cellX, y: this.me.cellY } : { x: this.spawn.x + 0.5, y: this.spawn.y + 1 };
    socket.sendEnter(this.presenceRoom(), s.x, s.y);
  }

  private bindSocket(): void {
    const offs = [
      // hello puts us in the base room; answer with where we actually are and wait for "entered"
      socket.on("hello", () => this.enterPresence()),
      socket.on("entered", (m) => {
        if (m.room !== this.presenceRoom()) return;
        this.remotes.reset(m.online);
        this.publishOnline();
        if (m.room_version !== state.roomVersion) void this.refreshRoom();
        if (this.me) socket.sendMove(this.me.cellX, this.me.cellY, this.me.dir, false);
      }),
      socket.on("join", (m) => { void this.remotes.join(m).then(() => this.publishOnline()); this.publishOnline(); }),
      socket.on("leave", (m) => { this.remotes.leave(m.id); this.steps.forget(m.id); this.publishOnline(); }),
      socket.on("move", (m) => this.remotes.move(m.id, m.x, m.y, m.dir, m.moving)),
      socket.on("avatar_look", (m) => void this.remotes.look(m.id, m.avatar)),
      socket.on("room", (m) => {
        if (typeof m.balance === "number") this.setBalance(m.balance);
        if (m.room !== undefined && m.room !== this.room.id) return; // another room changed: only the balance matters
        if (typeof m.ruined === "number") this.setRuined(m.ruined);
        if (m.version !== state.roomVersion) void this.refreshRoom();
      }),
      socket.on("money", (m) => this.setBalance(m.balance)),
      socket.on("mine", (m) => this.mine?.onMessage(m)),
      socket.on("mine_reset", () => void this.mine?.load()),
      // a chat line said in this room (or floor): a bubble over the speaker
      socket.on("chat", (m) => { if (m.room !== this.presenceRoom()) return; if (m.player === this.playerId) this.me?.say(m.text); else this.remotes.say(m.player, m.text); }),
      socket.on("open", () => this.publishOnline()),
      socket.on("close", () => { this.remotes.reset([]); this.publishOnline(); }),
    ];
    this.unsub.push(...offs);
  }

  /** Shared pool: everyone's balance moves when anyone buys/sells or the sheet updates. */
  private setBalance(balance: number): void {
    if (state.balance === balance) return;
    state.balance = balance;
    bus.emit("money", { balance });
  }

  private publishOnline(): void {
    const n = this.remotes.count + (this.me && socket.connected ? 1 : 0);
    state.online = n;
    bus.emit("online", { count: n });
  }

  // ---------------------------------------------------------------- bus

  private bindBus(): void {
    this.unsub.push(
      bus.on("place:begin", ({ itemId }) => { this.hoverFollow = true; this.placement.begin(itemId, this.ghostStart()); }),
      bus.on("place:move", ({ uid }) => { const row = this.items.get(uid); if (row) { this.hoverFollow = false; this.placement.beginMove(row); } }), // a move starts pinned where the item is
      bus.on("place:confirm", () => void this.placement.confirm()),
      bus.on("place:confirm-again", () => void this.placement.confirm(true)),
      bus.on("place:cancel", () => this.placement.cancel()),
      bus.on("place:span", ({ delta }) => this.placement.setSpan(delta)),
      bus.on("room:refresh", () => void this.refreshRoom()),
      bus.on("item:remove", ({ uid }) => void this.removeItem(uid)),
      bus.on("item:walk", ({ uid }) => this.walkToItem(uid)),
      bus.on("avatar:saved", (look) => void this.applyMyLook(look)),
      bus.on("comfort:changed", () => this.guests.sync()),
      bus.on("mine:press", () => this.mine?.hitTarget()),
    );
  }

  /** A fresh ghost appears next to the avatar (or in the middle of the view), not at the room spawn. */
  private ghostStart(): Cell {
    if (this.me) return this.me.footCell();
    const w = this.cam.screenToWorld(this.cam.viewW / 2, this.cam.viewH / 2);
    const c = worldToCell(w.x, w.y);
    return { cx: Phaser.Math.Clamp(c.cx, 0, this.room.cols - 1), cy: Phaser.Math.Clamp(c.cy, this.room.wall_rows, this.room.rows - 1) };
  }

  private async removeItem(uid: number): Promise<void> {
    const it = this.cat.byId.get(this.items.get(uid)?.item_id ?? "");
    try {
      const r = await api.remove(uid);
      state.balance = r.balance;
      bus.emit("money", { balance: r.balance });
      if (typeof r.ruined === "number" && r.room === this.room.id) this.setRuined(r.ruined);
      play(SFX.sell, { volume: SFX_VOL.ui });
      toast(it && hasTag(it, "ruined") ? `팔았어요 (+${it.price}{coin})` : "치웠어요 (환불됨)");
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
    void this.refreshRoom();
  }

  private async applyMyLook(look: typeof state.avatar): Promise<void> {
    await ensureAvatarTextures(this, look, this.cat.chars);
    this.me?.setLook(look);
  }

  // ---------------------------------------------------------------- walking

  private walkGrid(): WalkGrid {
    const base = roomWalkGrid(this.cat, this.room, this.items.occupied);
    const solid = this.mine?.blocked;
    if (!solid?.size) return base;
    return { cols: base.cols, rows: base.rows, isWalkable: (cx, cy) => base.isWalkable(cx, cy) && !solid.has(cellKey(cx, cy)) }; // rocks and ore block
  }

  /** Walk to a cell along furniture-free cells; an unreachable target walks as close as it can. */
  private walkTo(cx: number, cy: number): boolean {
    if (!this.me) return false;
    this.pendingOre = null; // a new destination forgets the ore we were walking to (the ore tap sets it again after)
    const path = pathToward(this.walkGrid(), this.me.footCell(), { cx, cy });
    if (!path.length) return false;
    this.keyWalking = false;
    this.me.walkPath(path);
    this.cam.follow(this.me);
    return true;
  }

  /** Context menu "여기로 가기": head for the item's footprint cell nearest to me (the path stops beside it when it blocks). */
  private walkToItem(uid: number): void {
    const row = this.items.get(uid);
    if (!row || !this.me) return;
    const me = this.me.footCell();
    let best: Cell | null = null, bestD = Infinity;
    for (const [cx, cy] of footprintOf(this.cat, row)) {
      const d = Math.abs(cx - me.cx) + Math.abs(cy - me.cy);
      if (d < bestD) { bestD = d; best = { cx, cy: Math.max(cy, this.room.wall_rows) }; } // wall decor: walk to the floor below it
    }
    if (best && !this.walkTo(best.cx, best.cy)) toast("거긴 갈 수 없어요");
  }

  /** WASD: one cell at a time while the key is held (the queue is extended before the avatar stops, so the run stays smooth). */
  private walkByKeys(): void {
    const d = this.keys.held();
    if (!d || !this.me || this.placement.active) return;
    if (this.me.walking && this.me.pending > 0) return;
    const from = this.me.walking ? this.me.targetCell()! : this.me.footCell();
    const [dx, dy] = dirDelta(d);
    const next = { cx: from.cx + dx, cy: from.cy + dy };
    if (this.walkGrid().isWalkable(next.cx, next.cy)) {
      this.keyWalking = true;
      if (this.me.walking) this.me.extend(next); else this.me.walkPath([next]);
      this.cam.follow(this.me);
    } else if (!this.me.walking) {
      this.me.face(d);
    }
  }

  private footstep(id: string, cx: number, cy: number, gain: number): void {
    const kind = stepKindFor(this.cat.tiles.interior[floorKeyAt(this.room, cx, cy)], "wood");
    this.steps.trigger(id, kind, SFX_VOL.step * gain);
  }

  /** How loudly someone else's step is heard from where I stand (1 next to me, 0 far away). */
  private hearing(cx: number, cy: number): number {
    if (!this.me) return 0;
    const c = this.me.footCell();
    const d = Math.abs(c.cx - cx) + Math.abs(c.cy - cy);
    return Phaser.Math.Clamp(1 - d / STEP_HEAR_CELLS, 0, 1);
  }

  // ---------------------------------------------------------------- exits

  /** Arrived on an exit cell → leave through it (main.ts swaps the scene). */
  private checkExit(): void {
    if (!this.me || this.leaving) return;
    const { cx, cy } = this.me.footCell();
    // an exit drawn entirely on the wall rows (stairs going up) is entered from the floor cell right below it
    const exit = exitAt(this.room, cx, cy) ?? (cy === this.room.wall_rows ? exitAt(this.room, cx, cy - 1) : null);
    if (!exit) return;
    // main.ts restarts the scene — unless the target is still locked (then it only toasts, and we must stay walkable)
    const locked = state.locked.has(exit.to) && !isDebugAccount();
    if (this.cat.rooms.has(exit.to) && !locked) this.leaving = true;
    bus.emit("room:exit", { from: this.room.id, to: exit.to, spawn: exit.spawn });
  }

  /** Standing on the mine's open ladder → the next floor (main.ts restarts the scene with floor + 1). */
  private checkLadder(): void {
    if (!this.me || !this.mine || this.leaving) return;
    const { cx, cy } = this.me.footCell();
    if (!this.mine.ladderAt(cx, cy)) return;
    this.leaving = true;
    bus.emit("mine:descend", { floor: this.floor + 1 });
  }

  // ---------------------------------------------------------------- input

  private bindInput(): void {
    this.keys = new WalkKeys();
    this.gestures = new Gestures(this, {
      // placement mode owns the single pointer: the ghost follows the finger / the mouse until pinned
      claim: (p, phase) => {
        if (!this.placement.active) return false;
        const w = this.cam.screenToWorld(p.x, p.y);
        if (phase === "down") { this.hoverFollow = false; this.placement.pointer(w.x, w.y); }
        else if (phase === "move") { if (p.isDown || (!p.wasTouch && this.hoverFollow)) this.placement.pointer(w.x, w.y); }
        else if (phase === "up") this.placement.pointer(w.x, w.y);
        // "up-outside": the click landed on the 놓기 button; leave the ghost pinned where it was (its cell is what confirm() sends)
        return true;
      },
      tap: (p) => this.onTap(p),
      longPress: (p) => { const w = this.cam.screenToWorld(p.x, p.y); if (this.openMenu(w.x, w.y)) navigator.vibrate?.(15); },
      rightClick: (p) => { const w = this.cam.screenToWorld(p.x, p.y); this.openMenu(w.x, w.y); },
      pan: (dx, dy) => this.cam.panBy(dx, dy),
      pinch: (ratio, mid) => this.cam.pinch(ratio, mid),
      pinchEnd: () => this.cam.pinchEnd(),
      wheel: (dy, p) => this.cam.wheel(dy, p),
    }, { longPressMs: LONG_PRESS_MS, slop: TAP_SLOP });
  }

  private onTap(p: Phaser.Input.Pointer): void {
    const w = this.cam.screenToWorld(p.x, p.y);
    const { cx, cy } = worldToCell(w.x, w.y);
    if (this.innCat?.tap(w.x, w.y)) return; // the cat is petted before anything under it
    if (this.guests.tap(w.x, w.y)) return; // a guest answers before anything under them
    // an ore node: pick it when I stand next to it, else walk up to it first (the path stops beside the rock;
    // a wall ore is mined from the floor cell right below it)
    const node = this.mine?.nodeAt(cx, cy);
    if (node && this.mine) {
      if (this.mine.select(node.seq, true)) return;
      const to = this.mine.standCell(node);
      if (this.walkTo(to.cx, to.cy)) this.pendingOre = node.seq; else toast("거긴 갈 수 없어요");
      return;
    }
    // the open ladder: walk onto it (checkLadder takes it from there); already on it → go down now
    if (this.mine?.ladderAt(cx, cy)) {
      const me = this.me?.footCell();
      if (me && me.cx === cx && me.cy === cy) this.checkLadder();
      else if (!this.walkTo(cx, cy)) toast("거긴 갈 수 없어요");
      return;
    }
    // stairs: a tap walks through them (long press still opens the menu)
    const tapped = this.items.itemAt(cx, cy, TAP_MENU_LAYERS);
    const stairs = tapped ?? this.items.itemAt(cx, cy); // stairs may also be a wall-layer item
    if (stairs && hasTag(this.cat.byId.get(stairs.item_id), TAG_STAIRS) && this.walkThrough(stairs.x, stairs.y, stairs.item_id)) return;
    // the 📋 board on the wall: a tap opens the quest / reservation list
    if (stairs && hasTag(this.cat.byId.get(stairs.item_id), TAG_BOARD)) { bus.emit("board:open"); return; }
    // a plain tap on a placed item opens its menu too (easier than holding on a phone)
    if (tapped && this.openMenu(w.x, w.y)) return;
    if (this.me && cx >= 0 && cx < this.room.cols && cy >= 0 && cy < this.room.rows && !this.walkTo(cx, cy) && cy < this.room.wall_rows) {
      /* tapped the wall with nowhere closer to go: nothing to do */
    }
  }

  /** Walk to the exit a stairs item stands on (its footprint overlaps the exit rect, or the exit is right below it).
   *  Returns false when no exit belongs to it, so the tap falls through to the menu. */
  private walkThrough(x: number, y: number, itemId: string): boolean {
    if (!this.me) return false;
    const it = this.cat.byId.get(itemId);
    const cells = footprint(x, y, it?.w ?? 1, it?.h ?? 1);
    const touches = (e: Exit) => cells.some(([cx, cy]) => cx >= e.x && cx < e.x + e.w && cy >= e.y - 1 && cy < e.y + e.h);
    const exit = this.room.exits.find(touches);
    if (!exit) return false;
    // nearest walkable cell of the exit (floor rows only); an exit fully on the wall is entered from the row below it
    const grid = this.walkGrid();
    let best: { x: number; y: number } | null = null;
    let bestD = Infinity;
    const me = this.me.footCell();
    for (let cy = Math.max(exit.y, this.room.wall_rows); cy < exit.y + exit.h; cy++) {
      for (let cx = exit.x; cx < exit.x + exit.w; cx++) {
        if (!grid.isWalkable(cx, cy)) continue;
        const d = Math.abs(cx - me.cx) + Math.abs(cy - me.cy);
        if (d < bestD) { bestD = d; best = { x: cx, y: cy }; }
      }
    }
    if (!best) best = { x: Math.min(Math.max(me.cx, exit.x), exit.x + exit.w - 1), y: Math.min(exit.y + exit.h, this.room.rows - 1) };
    this.walkTo(best.x, best.y);
    return true;
  }

  /** Opens the item menu at a world position. Returns false when there is no item there (or it is part of the room). */
  private openMenu(wx: number, wy: number): boolean {
    const { cx, cy } = worldToCell(wx, wy);
    const row = this.items.itemAt(cx, cy);
    if (!row || !this.playerId || this.room.kind === "mine") return false; // the mine's props are part of the room
    if (hasTag(this.cat.byId.get(row.item_id), TAG_FIXED)) return false; // stairs etc.: tapping them walks there
    const s = this.cam.toClient(wx, wy);
    bus.emit("item:menu", { item: row, screenX: s.x, screenY: s.y });
    return true;
  }

  // ---------------------------------------------------------------- loop

  update(time: number, delta: number): void {
    this.walkByKeys();
    this.me?.update(time, delta);
    this.remotes.update(time, delta);
    this.guests.update(time, delta);
    this.innCat?.update(time, delta);
    this.cam.update();
  }

  private teardown(): void {
    for (const off of this.unsub) off();
    this.unsub = [];
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    this.gestures.destroy();
    this.keys.destroy();
    this.cam.destroy();
    this.placement.cancel();
    this.remotes.destroy();
    this.guests.destroy();
    this.innCat?.destroy();
    this.innCat = null;
    this.mine?.destroy();
    this.mine = null;
    this.pendingOre = null;
    this.items.destroy();
    this.me?.destroy();
    this.me = null;
    state.roomVersion = -1;
  }
}
