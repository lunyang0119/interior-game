import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { Avatar } from "../avatar/Avatar";
import { ensureAvatarTextures } from "../avatar/AvatarLoader";
import { RemoteAvatars } from "../avatar/RemoteAvatars";
import { bus, toast } from "../bus";
import type { Catalog } from "../catalog";
import { CELL, worldToCell } from "../room/grid";
import { ATLAS, ItemLayer } from "../room/ItemLayer";
import { PlacementController } from "../room/Placement";
import { catalog, state } from "../state";
import { socket } from "../ws";

const POLL_MS = 60_000;
const LONG_PRESS_MS = 450;
const TAP_SLOP = 8;

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

  private drawRoom(): void {
    const { cols, rows, wall_rows, tiles } = this.cat.room;
    for (let cy = 0; cy < rows; cy++) {
      for (let cx = 0; cx < cols; cx++) {
        let key = tiles.floor;
        if (cy < wall_rows) {
          const edge = cx === 0 && tiles.wall_left.length ? tiles.wall_left
            : cx === cols - 1 && tiles.wall_right.length ? tiles.wall_right : tiles.wall;
          key = edge[cy] ?? tiles.wall[cy];
        }
        this.add.image(cx * CELL, cy * CELL, ATLAS, key).setOrigin(0).setDepth(-1);
      }
    }
    this.cameras.main.setBounds(0, 0, cols * CELL, rows * CELL);
  }

  // ---------------------------------------------------------------- data

  async refreshRoom(): Promise<void> {
    try {
      const r = await api.room(state.roomVersion);
      if (!r) return; // 304
      state.roomVersion = r.version;
      this.items.sync(r.items);
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
      socket.on("room", (m) => { if (m.version !== state.roomVersion) void this.refreshRoom(); }),
      socket.on("open", () => this.publishOnline()),
      socket.on("close", () => { this.remotes.reset([]); this.publishOnline(); }),
    ];
    this.unsub.push(...offs);
  }

  private publishOnline(): void {
    const n = this.remotes.count + (this.me && socket.connected ? 1 : 0);
    state.online = n;
    bus.emit("online", { count: n });
  }

  // ---------------------------------------------------------------- bus

  private bindBus(): void {
    this.unsub.push(
      bus.on("place:begin", ({ itemId }) => this.placement.begin(itemId)),
      bus.on("place:move", ({ uid }) => { const row = this.items.get(uid); if (row) this.placement.beginMove(row); }),
      bus.on("place:confirm", () => void this.placement.confirm()),
      bus.on("place:cancel", () => this.placement.cancel()),
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
      toast("치웠어 (환불됨)");
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
    this.input.on(Phaser.Input.Events.POINTER_DOWN, (p: Phaser.Input.Pointer) => {
      if (this.placement.active) { this.placement.pointer(p.worldX, p.worldY); return; }
      const press = { x: p.x, y: p.y, t: p.downTime, moved: false, timer: null as number | null };
      press.timer = window.setTimeout(() => {
        if (this.press === press && !press.moved) { this.press = null; this.openMenu(p.worldX, p.worldY, p.x, p.y); }
      }, LONG_PRESS_MS);
      this.press = press;
    });
    this.input.on(Phaser.Input.Events.POINTER_MOVE, (p: Phaser.Input.Pointer) => {
      if (this.placement.active) { if (p.isDown) this.placement.pointer(p.worldX, p.worldY); return; }
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
      if (this.me && cy >= this.cat.room.wall_rows && cx >= 0 && cx < this.cat.room.cols && cy < this.cat.room.rows) {
        this.me.walkToCell(cx, cy);
      }
    });
  }

  private openMenu(wx: number, wy: number, sx: number, sy: number): void {
    const { cx, cy } = worldToCell(wx, wy);
    const row = this.items.itemAt(cx, cy);
    if (!row || !this.playerId) return;
    const rect = this.game.canvas.getBoundingClientRect();
    const scale = rect.width / this.scale.width;
    bus.emit("item:menu", { item: row, screenX: rect.left + sx * scale, screenY: rect.top + sy * scale });
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
    socket.close();
    this.placement.cancel();
    this.remotes.destroy();
    this.items.destroy();
    this.me?.destroy();
    this.me = null;
    state.roomVersion = -1;
  }
}
