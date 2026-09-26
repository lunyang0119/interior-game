import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { Avatar } from "../avatar/Avatar";
import { ensureAvatarTextures } from "../avatar/AvatarLoader";
import { RemoteAvatars } from "../avatar/RemoteAvatars";
import { bus, toast } from "../bus";
import type { Catalog, Layer } from "../catalog";
import { TILE_DEPTH } from "../room/depth";
import { CELL, worldToCell } from "../room/grid";
import { ATLAS, ItemLayer } from "../room/ItemLayer";
import { PlacementController } from "../room/Placement";
import { catalog, state } from "../state";
import { socket } from "../ws";

const POLL_MS = 60_000;
const LONG_PRESS_MS = 400;
const TAP_SLOP = 14; // fingers wobble; keep the long-press alive within this radius
// a plain tap only opens the menu for these; rugs/wallpaper need a long press so tapping a rug still walks there
const TAP_MENU_LAYERS: ReadonlySet<Layer> = new Set<Layer>(["furniture", "surface_item"]);

export class RoomScene extends Phaser.Scene {
  private cat!: Catalog;
  private items!: ItemLayer;
  private placement!: PlacementController;
  private me: Avatar | null = null;
  private remotes!: RemoteAvatars;
  private unsub: (() => void)[] = [];
  private pollTimer: number | null = null;
  private press: { x: number; y: number; t: number; timer: number | null; moved: boolean } | null = null;
  private playerId: string | null = null;
  private inflight: Promise<void> | null = null;
  /** Desktop: the ghost follows the mouse until the first click pins it; a drag moves it again. */
  private hoverFollow = false;
  private onContextMenu = (e: Event) => e.preventDefault();

  constructor() {
    super("Room");
  }

  init(data: { id: string | null }): void {
    this.playerId = data.id;
  }

  create(): void {
    this.cat = catalog();
    this.drawRoom();
    this.items = new ItemLayer(this, this.cat);
    this.placement = new PlacementController(this, this.cat, this.items);
    this.placement.onRestart = () => { this.hoverFollow = true; }; // "+1": the fresh ghost follows the mouse again
    this.remotes = new RemoteAvatars(this, this.cat.chars);

    this.bindBus();
    this.bindInput();
    void this.refreshRoom();
    this.pollTimer = window.setInterval(() => { if (!socket.connected) void this.refreshRoom(); }, POLL_MS);

    if (this.playerId && state.token) {
      void this.spawnMe();
      this.bindSocket();
      socket.connect(state.token);
    }

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.teardown());
  }

  // ---------------------------------------------------------------- room base

  /** Bakes the wall/floor tiles into one RenderTexture: 1 game object instead of cols×rows images per frame. */
  private drawRoom(): void {
    const { cols, rows, wall_rows, tiles } = this.cat.room;
    const rt = this.add.renderTexture(0, 0, cols * CELL, rows * CELL).setOrigin(0).setDepth(TILE_DEPTH);
    rt.beginDraw();
    for (let cy = 0; cy < rows; cy++) {
      for (let cx = 0; cx < cols; cx++) {
        let key = tiles.floor;
        if (cy < wall_rows) {
          const edge = cx === 0 && tiles.wall_left.length ? tiles.wall_left
            : cx === cols - 1 && tiles.wall_right.length ? tiles.wall_right : tiles.wall;
          key = edge[cy] ?? tiles.wall[cy];
        }
        rt.batchDrawFrame(ATLAS, key, cx * CELL, cy * CELL);
      }
    }
    rt.endDraw();
    this.cameras.main.setBounds(0, 0, cols * CELL, rows * CELL);
  }

  // ---------------------------------------------------------------- data

  /** Fetches the room snapshot; concurrent calls share one request (place response + WS notify both ask). */
  refreshRoom(): Promise<void> {
    if (!this.inflight) this.inflight = this.doRefresh().finally(() => { this.inflight = null; });
    return this.inflight;
  }

  private async doRefresh(): Promise<void> {
    try {
      const r = await api.room(state.roomVersion);
      if (!r) return; // 304
      state.roomVersion = r.version;
      this.items.sync(r.items);
      this.placement.revalidate();
    } catch (e) {
      if (e instanceof ApiError && e.code !== "network") toast(msgFor(e.code));
    }
  }

  private async spawnMe(): Promise<void> {
    await ensureAvatarTextures(this, state.avatar, this.cat.chars);
    if (!this.scene.isActive()) return;
    const s = this.cat.room.spawn;
    this.me = new Avatar(this, this.cat.chars, state.avatar, s.x, s.y, this.playerId ?? "");
    this.me.onStep = (x, y, dir, moving) => socket.sendMove(x, y, dir, moving);
    this.publishOnline();
  }

  // ---------------------------------------------------------------- socket

  private bindSocket(): void {
    const offs = [
      socket.on("hello", (m) => {
        this.remotes.reset(m.online);
        this.publishOnline();
        if (m.room_version !== state.roomVersion) void this.refreshRoom();
        if (this.me) socket.sendMove(this.me.cellX, this.me.cellY, this.me.dir, false);
      }),
      socket.on("join", (m) => { void this.remotes.join(m).then(() => this.publishOnline()); this.publishOnline(); }),
      socket.on("leave", (m) => { this.remotes.leave(m.id); this.publishOnline(); }),
      socket.on("move", (m) => this.remotes.move(m.id, m.x, m.y, m.dir, m.moving)),
      socket.on("avatar_look", (m) => void this.remotes.look(m.id, m.avatar)),
      socket.on("room", (m) => {
        if (typeof m.balance === "number") this.setBalance(m.balance);
        if (m.version !== state.roomVersion) void this.refreshRoom();
      }),
      socket.on("money", (m) => this.setBalance(m.balance)),
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
      bus.on("place:begin", ({ itemId }) => { this.hoverFollow = true; this.placement.begin(itemId); }),
      bus.on("place:move", ({ uid }) => { const row = this.items.get(uid); if (row) { this.hoverFollow = false; this.placement.beginMove(row); } }), // a move starts pinned where the item is
      bus.on("place:confirm", () => void this.placement.confirm()),
      bus.on("place:confirm-again", () => void this.placement.confirm(true)),
      bus.on("place:cancel", () => this.placement.cancel()),
      bus.on("place:span", ({ delta }) => this.placement.setSpan(delta)),
      bus.on("room:refresh", () => void this.refreshRoom()),
      bus.on("item:remove", ({ uid }) => void this.removeItem(uid)),
      bus.on("avatar:saved", (look) => void this.applyMyLook(look)),
    );
  }

  private async removeItem(uid: number): Promise<void> {
    try {
      const r = await api.remove(uid);
      state.balance = r.balance;
      bus.emit("money", { balance: r.balance });
      toast("치웠어요 (환불됨)");
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
    void this.refreshRoom();
  }

  private async applyMyLook(look: typeof state.avatar): Promise<void> {
    await ensureAvatarTextures(this, look, this.cat.chars);
    this.me?.setLook(look);
  }

  // ---------------------------------------------------------------- input

  private bindInput(): void {
    // no browser context menu / iOS callout on long press over the canvas
    this.game.canvas.addEventListener("contextmenu", this.onContextMenu);
    this.input.on(Phaser.Input.Events.POINTER_DOWN, (p: Phaser.Input.Pointer) => {
      if (this.placement.active) { this.hoverFollow = false; this.placement.pointer(p.worldX, p.worldY); return; }
      const press = { x: p.x, y: p.y, t: p.downTime, moved: false, timer: null as number | null };
      press.timer = window.setTimeout(() => {
        if (this.press === press && !press.moved) {
          this.press = null;
          if (this.openMenu(p.worldX, p.worldY, p.x, p.y)) navigator.vibrate?.(15);
        }
      }, LONG_PRESS_MS);
      this.press = press;
    });
    this.input.on(Phaser.Input.Events.POINTER_MOVE, (p: Phaser.Input.Pointer) => {
      // touch: ghost follows the finger while pressed. mouse: follows hover only until the first click pins it,
      // otherwise moving to the "놓기" button would drag the ghost along
      if (this.placement.active) {
        if (p.isDown || (!p.wasTouch && this.hoverFollow)) this.placement.pointer(p.worldX, p.worldY);
        return;
      }
      if (this.press && Phaser.Math.Distance.Between(p.x, p.y, this.press.x, this.press.y) > TAP_SLOP) this.press.moved = true;
    });
    this.input.on(Phaser.Input.Events.POINTER_UP, (p: Phaser.Input.Pointer) => {
      if (this.placement.active) { this.placement.pointer(p.worldX, p.worldY); return; }
      const press = this.press;
      this.press = null;
      if (!press) return;
      if (press.timer !== null) clearTimeout(press.timer);
      if (press.moved) return;
      const { cx, cy } = worldToCell(p.worldX, p.worldY);
      // a plain tap on a placed item opens its menu too (easier than holding on a phone)
      if (this.items.itemAt(cx, cy, TAP_MENU_LAYERS) && this.openMenu(p.worldX, p.worldY, p.x, p.y)) return;
      if (this.me && cy >= this.cat.room.wall_rows && cx >= 0 && cx < this.cat.room.cols && cy < this.cat.room.rows) {
        this.me.walkToCell(cx, cy);
      }
    });
  }

  /** Opens the item menu at a world position. Returns false when there is no item there. */
  private openMenu(wx: number, wy: number, sx: number, sy: number): boolean {
    const { cx, cy } = worldToCell(wx, wy);
    const row = this.items.itemAt(cx, cy);
    if (!row || !this.playerId) return false;
    const rect = this.game.canvas.getBoundingClientRect();
    const scale = rect.width / this.scale.width;
    bus.emit("item:menu", { item: row, screenX: rect.left + sx * scale, screenY: rect.top + sy * scale });
    return true;
  }

  // ---------------------------------------------------------------- loop

  update(time: number, delta: number): void {
    this.me?.update(time, delta);
    this.remotes.update(time, delta);
  }

  private teardown(): void {
    for (const off of this.unsub) off();
    this.unsub = [];
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    this.game.canvas.removeEventListener("contextmenu", this.onContextMenu);
    socket.close();
    this.placement.cancel();
    this.remotes.destroy();
    this.items.destroy();
    this.me?.destroy();
    this.me = null;
    state.roomVersion = -1;
  }
}
