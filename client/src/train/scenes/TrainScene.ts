import Phaser from "phaser";
import { Gestures } from "../../input/Gestures";
import { CELL } from "../../room/grid";
import { cellKey } from "../../room/walk";
import { CameraController } from "../../scenes/CameraController";
import { state } from "../../state";
import type { MapRoom, Report } from "../api";
import { tbus } from "../bus";
import { CarMap } from "../render/CarMap";
import { FugitiveSprite } from "../render/Fugitive";
import { Fx } from "../render/Fx";
import { Hunters } from "../render/Hunters";
import { buildLayout, roomAt, type Layout } from "../render/layout";
import { playRound } from "../render/Playback";
import { isFugitive, isOver, me, tstate } from "../state";

export interface TrainSceneData {
  rooms: MapRoom[];
  preview?: boolean;
}

/** The train car. Preview: just the data-driven layout. Game: hunters, the fugitive silhouette, markers and the
 *  round playback, all driven from tstate.payload (what the server sent to this role). */
export class TrainScene extends Phaser.Scene {
  private carMap!: CarMap;
  private layout!: Layout;
  private camCtl!: CameraController;
  private gestures!: Gestures;
  private hunters: Hunters | null = null;
  private fugitive: FugitiveSprite | null = null;
  private fx: Fx | null = null;
  private data_!: TrainSceneData;
  private offs: (() => void)[] = [];
  private busy = false;
  /** the sync() still in flight (avatar textures loading): a playback waits for it so it cannot re-place the sprites mid-walk */
  private syncing: Promise<void> | null = null;

  constructor() {
    super("Train");
  }

  init(data: TrainSceneData): void {
    this.data_ = data;
  }

  create(): void {
    const layout = this.layout = buildLayout(this.data_.rooms, state.catalog);
    this.carMap = new CarMap(this, layout);
    this.cameras.main.setBackgroundColor("#14141c");
    this.camCtl = new CameraController(this, { worldW: this.carMap.widthPx, worldH: this.carMap.heightPx, minZoom: 1, maxZoom: 4, targetRows: layout.rows });

    // one-finger drag pans. Gestures only pans with a mouse drag or two fingers (the room scenes follow the
    // avatar instead); `claim` adds the pan as a side effect and never takes the event over, so Gestures still
    // cancels the tap by its own slop and releases the pointer normally.
    const drag = { id: -1, x: 0, y: 0, moved: false };
    const DRAG_SLOP = 14;
    this.gestures = new Gestures(this, {
      claim: (p, phase) => {
        const fingers = this.input.manager.pointers.filter((q) => q.isDown).length;
        if (phase === "down") {
          drag.id = p.wasTouch && fingers === 1 ? p.id : -1;
          drag.x = p.x; drag.y = p.y; drag.moved = false;
        } else if (phase === "move" && drag.id === p.id) {
          if (fingers !== 1) drag.id = -1;
          else if (drag.moved || Phaser.Math.Distance.Between(p.x, p.y, drag.x, drag.y) > DRAG_SLOP) {
            drag.moved = true;
            this.camCtl.panBy(p.x - drag.x, p.y - drag.y);
            drag.x = p.x; drag.y = p.y;
          }
        } else if (phase !== "move") {
          drag.id = -1;
        }
        return false;
      },
      tap: (p) => {
        const w = this.camCtl.screenToWorld(p.x, p.y);
        const cx = Math.floor(w.x / CELL), cy = Math.floor(w.y / CELL);
        const door = this.doorAtCell(cx, cy);
        const b = roomAt(layout, cx, cy);
        tbus.emit("room:tap", { room: b?.id ?? null, door });
      },
      pan: (dx, dy) => this.camCtl.panBy(dx, dy),
      pinch: (ratio, mid) => this.camCtl.pinch(ratio, mid),
      pinchEnd: () => this.camCtl.pinchEnd(),
      wheel: (dy, p) => this.camCtl.wheel(dy, { x: p.x, y: p.y }),
    });

    this.offs.push(tbus.on("preview:grid", ({ on }) => this.carMap.showGrid(on)));
    if (!this.data_.preview && state.catalog) {
      this.hunters = new Hunters(this, state.catalog.chars, layout);
      this.fugitive = new FugitiveSprite(this, state.catalog.chars, layout);
      this.fx = new Fx(this, layout, (edge) => this.doorPoint(edge));
      this.fx.onCondition = (tag, rooms) => this.carMap.setCondition(tag, rooms); // template effects tied to gimmicks
      this.offs.push(tbus.on("scene:sync", () => void this.sync()));
      this.offs.push(tbus.on("playback:start", ({ report }) => void this.play(report)));
      this.offs.push(tbus.on("playback:abort", () => { this.busy = false; void this.sync(); }));
      this.offs.push(tbus.on("camera:home", () => this.home()));
      this.offs.push(tbus.on("pick:changed", () => this.showPicks()));
      // idle (battery) mode pauses only the endless pulses: result bubbles must still fade out on time
      this.offs.push(tbus.on("throttle", ({ on }) => this.fx?.setPulsesPaused(on)));
      void this.sync().then(() => this.home());
    }
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.offs.forEach((f) => f());
      this.offs = [];
      this.gestures.destroy();
      this.camCtl.destroy();
      this.fx?.destroy();
      this.hunters?.destroy();
      this.fugitive?.destroy();
      this.carMap.destroy();
    });
    tbus.emit("scene:ready", { rooms: layout.rooms.size });
  }

  private doorAtCell(cx: number, cy: number): string | null {
    const k = cellKey(cx, cy);
    for (const d of this.layout.doors) if (d.cells.some((c) => cellKey(c.cx, c.cy) === k)) return d.edge;
    return null;
  }

  /** World point of a door (centre of its gap), for markers and highlights. */
  doorPoint(edge: string): { x: number; y: number } | null {
    const d = this.layout.doorByEdge.get(edge);
    if (!d) return null;
    const xs = d.cells.map((c) => c.cx), ys = d.cells.map((c) => c.cy);
    return { x: ((Math.min(...xs) + Math.max(...xs) + 1) / 2) * CELL, y: (Math.max(...ys) + 1) * CELL };
  }

  /** Redraw everyone from the payload (not while a playback is running). */
  private sync(): Promise<void> {
    const run = this.doSync().catch((e) => console.warn("train: sync failed", e));
    this.syncing = run;
    return run.finally(() => { if (this.syncing === run) this.syncing = null; });
  }

  private async doSync(): Promise<void> {
    const p = tstate.payload;
    if (!p || !this.hunters || !this.fugitive || !this.fx || this.busy) return;
    const view = p.view;
    if (!view) { this.hunters.destroy(); return; }
    const ids = view.hunters.map((h) => h.name);
    const rooms: Record<string, string> = {};
    for (const h of view.hunters) rooms[h.name] = h.room;
    await this.hunters.sync(ids, p.avatars ?? {}, rooms);
    if (this.busy) return;   // a playback started while the textures loaded: it owns the sprites now
    this.fx.setMarkers(view.markers);
    this.fx.setLocks(view.locks);
    this.fx.setSteam(view.steam);
    // post-game route reveal (server sends `route` only once the chase is over and the admin switched it on)
    const route = isOver(p.status) && p.route ? p.route : [];
    const stops: { round: number; room: string }[] = [];
    for (const r of route) for (const room of r.path) if (!stops.length || stops[stops.length - 1].room !== room) stops.push({ round: r.round, room });
    this.fx.drawRoute(stops, stops.length ? view.capture_room : null);
    if (p.fugitive) {
      this.fugitive.setTrace(p.fugitive.tier, p.fugitive.frozen);
      await this.fugitive.show(p.fugitive.room);
    } else if (view.capture_room) {
      await this.fugitive.show(view.capture_room);
      await this.fugitive.reveal();
    } else {
      this.fugitive.hide();
    }
    if (this.busy) return;
    this.showPicks();
  }

  /** Selectable rooms/doors for the current pick (hunter: neighbours; fugitive: reachable, lockable doors). */
  private showPicks(): void {
    const p = tstate.payload;
    if (!p || !this.fx || this.busy) return;
    if (p.status !== "ROUND_OPEN") { this.fx.highlightRooms([]); return; }
    if (isFugitive() && p.fugitive) {
      const sel = tstate.fpick;
      const rooms = sel.hack === "distract" ? [...this.layout.rooms.keys()] : sel.hack === "hide" ? [] : (p.reachable ?? []);
      const selected = sel.hack === "distract" ? sel.target : sel.move;
      const doors = sel.hack === "doorlock" ? (p.lockable_edges ?? []).map((e) => this.doorPoint(e)).filter((x): x is { x: number; y: number } => !!x) : [];
      this.fx.highlightRooms(rooms, sel.hack === "distract" ? 0xc792ea : 0x4f8cff, doors, selected);
      return;
    }
    const you = p.you;
    if (!you || !you.room || you.dazed) { this.fx.highlightRooms([]); return; }
    const here = this.data_.rooms.find((r) => r.id === you.room);
    const sel = tstate.pick?.type === "move" ? tstate.pick.target : null;
    this.fx.highlightRooms(here ? [...here.neighbors, here.id] : [], 0x4f8cff, [], sel);
  }

  /** Play a round. Always ends with playback:done (main.ts drives its queue off it), even when the animation threw. */
  private async play(report: Report): Promise<void> {
    if (!this.hunters || !this.fugitive || !this.fx) { tbus.emit("playback:done", { report }); return; }
    this.busy = true;
    this.fx.highlightRooms([]);
    try {
      if (this.syncing) await this.syncing;   // let a running sync finish placing sprites before we move them
      // make sure every hunter of the report exists before animating
      const ids = report.order.length ? report.order : Object.keys(report.hunters);
      const rooms: Record<string, string> = {};
      for (const h of report.playback.hunters) rooms[h.id] = h.from;
      await this.hunters.sync(ids, tstate.payload?.avatars ?? {}, rooms, true);
      await playRound({ scene: this, layout: this.layout, hunters: this.hunters, fugitive: this.fugitive, fx: this.fx,
        fugitiveView: isFugitive(), toast: (s, ms) => tbus.emit("toast", { text: s, ms: ms ?? 2600 }), skipped: () => tstate.skipping,
        captureRoom: () => tstate.payload?.view?.capture_room ?? null }, report);
    } catch (e) {
      console.error("train: playback failed", e);
    } finally {
      this.busy = false;
      tbus.emit("playback:done", { report });
    }
    void this.sync();
  }

  /** Centre the camera on my avatar (fugitive: the silhouette). */
  private home(): void {
    const p = tstate.payload;
    let pt: { x: number; y: number } | null = null;
    if (p?.fugitive && this.fx) pt = this.fx.roomCenter(p.fugitive.room);
    else if (me() && this.hunters) pt = this.hunters.position(me()!);
    if (pt) { this.camCtl.follow(pt); this.camCtl.update(); this.camCtl.follow(null); }
  }

  update(time: number, delta: number): void {
    this.camCtl.update();
    this.hunters?.update(time, delta);
    this.fugitive?.update(time, delta);
  }
}
