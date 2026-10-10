import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { play, SFX, SFX_VOL, type SfxHandle } from "../audio/sfx";
import { bus, toast } from "../bus";
import { ATLAS } from "../room/ItemLayer";
import { setZone, state } from "../state";
import { socket } from "../ws";
import { fitToView } from "./CameraController";
import { assetUrl } from "../assets";

/** Layout written by the world editor (부두 tab) → gen/dock.json. Layers are drawn back → front. */
interface DockLayer {
  kind: "image" | "slice";
  src?: number; // image: gen/dock/<src>.png
  atlas?: "interior" | "map"; // slice
  key?: string;
  x?: number;
  y?: number;
  scale?: number;
  visible?: boolean;
}
interface Rect { x: number; y: number; w: number; h: number }
// water: where bite markers may appear (editor: 부두 탭 "물 영역"); fish is the old single bobber point, unused now
interface DockLayout { w: number; h: number; layers: DockLayer[]; fish?: { x: number; y: number }; water?: Rect }

const MAP_ATLAS = "map";
const MARKER = "icon_exclamation";
const BOUNCE_PX = 6; // the hop a still marker does when it pops up
const WANDER_CHANCE = 0.4; // share of bites whose marker swims left/right or up/down
const WANDER_SPEED = 30; // px per second
const FINISH_GRACE_MS = 400; // after the last bite window: absorb timer drift before asking the server

interface Bite { at_ms: number; window_ms: number; hold_ms: number }
interface Cast { session: string; bites: Bite[] }
type FishMode = "idle" | "wait" | "bite" | "hold";

/** The dock: a layered backdrop with no avatar. Buttons (나가기 / 낚시) live in the DOM (#dockbar / #fishbar). */
export class DockScene extends Phaser.Scene {
  private layout: DockLayout | null = null;
  private unsub: (() => void)[] = [];
  private marker: Phaser.GameObjects.Image | Phaser.GameObjects.Text | null = null;
  private timers: number[] = [];
  // --- one cast ---
  private cast: Cast | null = null;
  private t0 = 0; // performance.now() when the schedule arrived
  private holds: { start_ms: number; end_ms: number }[] = [];
  private tried = new Set<number>(); // bite indexes already pressed on (pulled up or let go too soon)
  private pulls = 0;
  private current: number | null = null; // bite index whose "!" is showing and not pressed yet
  private holding: { bite: number; start: number } | null = null;
  private busy = false; // start/finish request in flight
  private cooldownUntil = 0;
  private reel: SfxHandle | null = null;
  private unfit: (() => void) | null = null;

  constructor() {
    super("Dock");
  }

  preload(): void {
    this.load.json("dock-layout", `/gen/dock.json?t=${Date.now()}`);
    if (!this.textures.exists(MAP_ATLAS)) this.load.atlas(MAP_ATLAS, assetUrl("/gen/map.png"), assetUrl("/gen/map.json")); // bite marker + rod slices
  }

  create(): void {
    setZone(null); // currentUnit() must not keep pointing at the room:zone we came from
    // presence: leave the room we came from (nobody is drawn here, but the room's head count should drop)
    if (state.token) {
      if (socket.connected) socket.sendEnter("dock");
      this.unsub.push(
        socket.on("hello", () => socket.sendEnter("dock")),
        socket.on("money", (m) => { if (m.balance !== state.balance) { state.balance = m.balance; bus.emit("money", { balance: m.balance }); } }),
        socket.on("room", (m) => { if (typeof m.balance === "number" && m.balance !== state.balance) { state.balance = m.balance; bus.emit("money", { balance: m.balance }); } }),
      );
    }
    this.unsub.push(
      bus.on("fish:press", () => this.press()),
      bus.on("fish:release", () => this.release()),
    );
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.teardown());
    this.publishState("눌러서 낚싯대를 던져요", "idle");

    this.layout = (this.cache.json.get("dock-layout") as DockLayout | undefined) ?? null;
    if (!this.layout || !this.layout.layers?.length) {
      this.add.text(8, 8, "부두 배경이 없어요 (빌드 필요)", { color: "#ffffff", fontSize: "10px" });
      bus.emit("dock:ready");
      return;
    }
    const { w, h } = this.layout;
    // the layout has a fixed pixel size; scale it to fill the window (cropping the sides in portrait),
    // keeping the water band centred, and re-fit on resize
    this.cameras.main.setBackgroundColor("#1b1b24");
    const water = this.waterRect();
    this.unfit = fitToView(this, w, h, { cover: true, focus: { x: water.x + water.w / 2, y: water.y + water.h / 2 } });

    // second pass: fetch the images this layout needs, then draw
    for (const l of this.layout.layers) {
      if (l.kind === "image" && l.src != null && !this.textures.exists(`dock-${l.src}`)) this.load.image(`dock-${l.src}`, assetUrl(`/gen/dock/${l.src}.png`));
    }
    this.load.once(Phaser.Loader.Events.COMPLETE, () => this.draw());
    this.load.start();
  }

  private draw(): void {
    if (!this.layout) return;
    this.layout.layers.forEach((l, i) => {
      if (l.visible === false) return;
      const x = l.x ?? 0, y = l.y ?? 0;
      if (l.kind === "image" && l.src != null && this.textures.exists(`dock-${l.src}`)) {
        this.add.image(x, y, `dock-${l.src}`).setOrigin(0).setDepth(i);
      } else if (l.kind === "slice" && l.key) {
        const atlas = l.atlas === "map" ? MAP_ATLAS : ATLAS;
        if (this.textures.exists(atlas) && this.textures.get(atlas).has(l.key)) {
          this.add.image(x, y, atlas, l.key).setOrigin(0).setScale(l.scale ?? 1).setDepth(i);
        }
      }
    });
    // bite marker, hidden until a bite; showBite() moves it somewhere in the water each time
    this.marker = this.textures.exists(MAP_ATLAS) && this.textures.get(MAP_ATLAS).has(MARKER)
      ? this.add.image(0, 0, MAP_ATLAS, MARKER).setOrigin(0.5, 1)
      : this.add.text(0, 0, "!", { color: "#ffffff", fontSize: "16px", fontStyle: "bold" }).setOrigin(0.5, 1);
    if (this.marker instanceof Phaser.GameObjects.Image) this.marker.setTintFill(0xffffff); // the icon is black; show it white on the water
    this.marker.setDepth(this.layout.layers.length + 1).setVisible(false);
    bus.emit("dock:ready");
  }

  // ---------------------------------------------------------------- fishing

  private publishState(status: string, mode: FishMode): void {
    bus.emit("fish:state", { status, mode });
  }

  private now(): number {
    return performance.now() - this.t0;
  }

  /**
   * One button. Idle → cast. While a bite is up it is "낚아올리기": press and keep holding for that bite's
   * hold_ms to pull it up (letting go early loses just that bite). A press at any other time (no bite yet, or
   * this bite was already tried) scares the fish away. Judged on what the player sees; the server re-checks
   * the hold times with some slack.
   */
  private press(): void {
    if (this.busy || this.holding) return;
    if (!this.cast) { void this.startCast(); return; }
    const t = Math.round(this.now());
    const i = this.current;
    if (i === null || this.tried.has(i)) {
      this.holds.push({ start_ms: t, end_ms: t });
      void this.finishCast(true);
      return;
    }
    this.tried.add(i);
    this.current = null;
    this.holding = { bite: i, start: t };
    navigator.vibrate?.(20);
    this.reel?.stop();
    this.reel = play(SFX.reel, { loop: true, volume: SFX_VOL.reel });
    this.publishState("꾹 누르고 버텨요!", "hold");
    bus.emit("fish:meter", { meter: 0 });
  }

  private release(): void {
    if (this.holding) this.endHold(false);
  }

  /** `full`: held for the bite's whole hold_ms (called from update()); otherwise the player let go early. */
  private endHold(full: boolean): void {
    const cast = this.cast, h = this.holding;
    if (!cast || !h) return;
    this.holding = null;
    this.holds.push({ start_ms: h.start, end_ms: Math.round(this.now()) });
    this.hideMarker();
    this.stopReel();
    if (full) {
      this.pulls++;
      navigator.vibrate?.(40);
      play(SFX.splash, { volume: SFX_VOL.ui });
      this.publishState(`낚아올렸어요! (${this.pulls}/${cast.bites.length})`, "wait");
    } else {
      this.publishState("너무 일찍 놓았어요… 다음 입질을 기다려요", "wait");
    }
    if (h.bite === cast.bites.length - 1) {
      // last bite settled: wrap up once its window is over too (the server checks that)
      const last = cast.bites[h.bite];
      const wait = Math.max(0, last.at_ms + last.window_ms - this.now()) + FINISH_GRACE_MS;
      this.timers.push(window.setTimeout(() => void this.finishCast(false), wait));
    }
  }

  private async startCast(): Promise<void> {
    if (!state.token) { toast("먼저 계정을 골라주세요"); return; }
    if (performance.now() < this.cooldownUntil) { this.publishState("잠깐 쉬었다가 다시 던져요", "idle"); return; }
    this.busy = true;
    try {
      const cast = await api.fishStart();
      if (!this.scene.isActive()) return;
      this.cast = cast;
      this.t0 = performance.now();
      this.holds = [];
      this.tried.clear();
      this.pulls = 0;
      this.current = null;
      this.holding = null;
      this.publishState("찌를 보고 있어요…", "wait");
      play(SFX.rod, { volume: SFX_VOL.ui }); // whoosh, then the bobber lands
      this.timers.push(window.setTimeout(() => play(SFX.splash, { volume: SFX_VOL.ui * 0.7 }), 600));
      cast.bites.forEach((b, i) => {
        this.timers.push(window.setTimeout(() => this.showBite(i), b.at_ms));
        this.timers.push(window.setTimeout(() => this.hideBite(i), b.at_ms + b.window_ms));
      });
      const last = cast.bites[cast.bites.length - 1];
      this.timers.push(window.setTimeout(() => void this.finishCast(false), last.at_ms + last.window_ms + FINISH_GRACE_MS));
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "network";
      this.publishState(msgFor(code), "idle");
      if (!(e instanceof ApiError)) toast(String(e));
    } finally {
      this.busy = false;
    }
  }

  private waterRect(): Rect {
    const L = this.layout!;
    return L.water ?? { x: 0, y: Math.round(L.h * 0.45), w: L.w, h: Math.round(L.h * 0.4) };
  }

  /**
   * The part of the water that is actually on screen and not hidden under the DOM bars (dock buttons at the
   * top, fish status/button at the bottom). Falls back to the whole water rect when nothing is left.
   */
  private visibleWater(): Rect {
    const water = this.waterRect();
    const cam = this.cameras.main;
    const sw = this.scale.width, sh = this.scale.height;
    const top = document.getElementById("dockbar")?.getBoundingClientRect().bottom ?? 0;
    const bottom = document.getElementById("fishbar")?.getBoundingClientRect().top ?? sh;
    const pad = 4; // screen px of breathing room next to the bars / edges
    const tl = cam.getWorldPoint(pad, Math.max(0, top) + pad);
    const br = cam.getWorldPoint(sw - pad, Math.min(sh, bottom) - pad);
    const x0 = Math.max(water.x, tl.x), y0 = Math.max(water.y, tl.y);
    const x1 = Math.min(water.x + water.w, br.x), y1 = Math.min(water.y + water.h, br.y);
    if (x1 - x0 < 24 || y1 - y0 < 16) return water;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  /** Where the marker's anchor (bottom centre) may go so the whole icon, hop included, stays in the visible water. */
  private markerRange(m: Phaser.GameObjects.Image | Phaser.GameObjects.Text): { x0: number; x1: number; y0: number; y1: number } {
    const w = this.visibleWater();
    const hw = m.displayWidth / 2;
    const x0 = w.x + hw, y0 = w.y + m.displayHeight + BOUNCE_PX;
    return { x0, x1: Math.max(x0, w.x + w.w - hw), y0, y1: Math.max(y0, w.y + w.h) };
  }

  /** A point `min..max` px away from p along one axis, kept inside lo..hi (turns around at the edge). */
  private wanderTo(p: number, lo: number, hi: number, min: number, max: number): number {
    const d = Phaser.Math.FloatBetween(min, max);
    const fwd = p + d <= hi, back = p - d >= lo;
    if (fwd && back) return Math.round(Math.random() < 0.5 ? p + d : p - d);
    if (fwd) return Math.round(p + d);
    if (back) return Math.round(p - d);
    return Math.round(hi - p > p - lo ? hi : lo); // the water is narrower than d: swim to the far side
  }

  private showMarker(): void {
    const m = this.marker;
    if (!m || !this.layout) return;
    const r = this.markerRange(m);
    const x = Math.round(Phaser.Math.FloatBetween(r.x0, r.x1)), y = Math.round(Phaser.Math.FloatBetween(r.y0, r.y1));
    this.tweens.killTweensOf(m);
    m.setPosition(x, y).setVisible(true);
    if (Math.random() >= WANDER_CHANCE) {
      this.tweens.add({ targets: m, y: y - BOUNCE_PX, duration: 120, yoyo: true, repeat: 3 });
      return;
    }
    const horizontal = Math.random() < 0.5;
    const to = horizontal ? this.wanderTo(x, r.x0, r.x1, 24, 80) : this.wanderTo(y, r.y0, r.y1, 8, 28);
    const dist = Math.abs(to - (horizontal ? x : y));
    if (dist < 1) return;
    this.tweens.add({ targets: m, [horizontal ? "x" : "y"]: to, duration: (dist / WANDER_SPEED) * 1000,
      ease: "Sine.easeInOut", yoyo: true, repeat: -1 });
  }

  private hideMarker(): void {
    if (!this.marker) return;
    this.tweens.killTweensOf(this.marker);
    this.marker.setVisible(false);
  }

  private showBite(i: number): void {
    if (!this.cast) return;
    this.current = i;
    this.showMarker();
    navigator.vibrate?.(30);
    play(SFX.splash, { volume: SFX_VOL.ui });
    this.publishState("입질이 왔어요! 지금 낚아올려요!", "bite");
  }

  /** The window closed without a press (a press moves the bite into `holding`, so this is a plain miss). */
  private hideBite(i: number): void {
    if (!this.cast || this.current !== i) return;
    this.current = null;
    this.hideMarker();
    this.publishState("놓쳤어요… 다음 입질을 기다려요", "wait");
  }

  /** `escaped`: the player pressed with no bite up, so the cast ends right away (and can't pay out). */
  private async finishCast(escaped: boolean): Promise<void> {
    const cast = this.cast;
    if (!cast) return;
    if (!escaped && this.holding) return; // still holding the last bite: endHold() finishes
    for (const t of this.timers) clearTimeout(t);
    this.timers = [];
    this.cast = null;
    this.current = null;
    this.holding = null;
    this.hideMarker();
    this.stopReel();
    this.busy = true;
    this.publishState(escaped ? "앗, 물고기가 놀라서 도망갔어요" : "…", "wait");
    try {
      const r = await api.fishFinish(cast.session, this.holds, escaped);
      if (typeof r.balance === "number" && r.balance !== state.balance) { state.balance = r.balance; bus.emit("money", { balance: r.balance }); }
      bus.emit("loot:got", { ok: r.ok, kind: "fish", id: r.id, name: r.name, value: r.value, who: state.id ?? "", seq: r.seq, deliverable: r.deliverable });
      this.publishState(
        r.ok ? `${r.name}을(를) 낚았어요! +${r.value}💰`
          : r.escaped ? `놀라서 도망갔어요… ${r.name}이었는데`
          : `${cast.bites.length}번 중 ${r.pulls}번 낚아올렸지만 ${r.name}이(가) 도망쳤어요`,
        "idle",
      );
    } catch (e) {
      this.publishState(e instanceof ApiError ? msgFor(e.code) : String(e), "idle");
    } finally {
      this.busy = false;
    }
    this.cooldownUntil = performance.now() + 3000;
    this.timers.push(window.setTimeout(() => { if (!this.cast) this.publishState("눌러서 낚싯대를 던져요", "idle"); }, 3200));
  }

  private stopReel(): void {
    this.reel?.stop();
    this.reel = null;
  }

  update(): void {
    if (!this.cast || !this.holding) return;
    const need = this.cast.bites[this.holding.bite].hold_ms;
    const held = this.now() - this.holding.start;
    bus.emit("fish:meter", { meter: Math.min(1, held / need) });
    if (held >= need) this.endHold(true);
  }

  private teardown(): void {
    for (const t of this.timers) clearTimeout(t);
    this.timers = [];
    for (const off of this.unsub) off();
    this.unsub = [];
    this.cast = null;
    this.current = null;
    this.holding = null;
    this.busy = false;
    this.marker = null;
    this.stopReel();
    this.unfit?.();
    this.unfit = null;
    bus.emit("fish:state", { status: "", mode: "idle" });
  }
}
