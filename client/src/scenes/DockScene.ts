import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { ATLAS } from "../room/ItemLayer";
import { state } from "../state";
import { socket } from "../ws";

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
interface DockLayout { w: number; h: number; layers: DockLayer[]; fish?: { x: number; y: number } }

const MAP_ATLAS = "map";
const MARKER = "icon_exclamation";
const FINISH_GRACE_MS = 400; // after the last bite window: let a late hold end, absorb latency

interface Bite { at_ms: number; window_ms: number; real: boolean }
interface Cast { session: string; hold_ms: number; bites: Bite[] }

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
  private holdStart: number | null = null;
  private busy = false;
  private cooldownUntil = 0;
  private currentBite: Bite | null = null;

  constructor() {
    super("Dock");
  }

  preload(): void {
    this.load.json("dock-layout", `/gen/dock.json?t=${Date.now()}`);
    if (!this.textures.exists(MAP_ATLAS)) this.load.atlas(MAP_ATLAS, "/gen/map.png", "/gen/map.json"); // bite marker + rod slices
  }

  create(): void {
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
    this.publishState("눌러서 낚싯대를 던져요", 0);

    this.layout = (this.cache.json.get("dock-layout") as DockLayout | undefined) ?? null;
    if (!this.layout || !this.layout.layers?.length) {
      this.add.text(8, 8, "부두 배경이 없어요 (빌드 필요)", { color: "#ffffff", fontSize: "10px" });
      bus.emit("dock:ready");
      return;
    }
    const { w, h } = this.layout;
    this.scale.resize(w, h);
    this.cameras.main.setBounds(0, 0, w, h).setBackgroundColor("#1b1b24");

    // second pass: fetch the images this layout needs, then draw
    for (const l of this.layout.layers) {
      if (l.kind === "image" && l.src != null && !this.textures.exists(`dock-${l.src}`)) this.load.image(`dock-${l.src}`, `/gen/dock/${l.src}.png`);
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
    // bite marker above the bobber position (editor: 부두 탭 "찌 위치"), hidden until a bite
    const fx = this.layout.fish?.x ?? Math.round(this.layout.w * 0.6), fy = this.layout.fish?.y ?? Math.round(this.layout.h * 0.55);
    this.marker = this.textures.exists(MAP_ATLAS) && this.textures.get(MAP_ATLAS).has(MARKER)
      ? this.add.image(fx, fy, MAP_ATLAS, MARKER).setOrigin(0.5, 1)
      : this.add.text(fx, fy, "!", { color: "#ffffff", fontSize: "16px", fontStyle: "bold" }).setOrigin(0.5, 1);
    this.marker.setDepth(this.layout.layers.length + 1).setVisible(false);
    bus.emit("dock:ready");
  }

  // ---------------------------------------------------------------- fishing

  private publishState(status: string, meter: number, extra: Partial<{ holding: boolean; active: boolean; real: boolean }> = {}): void {
    bus.emit("fish:state", { status, meter, holding: this.holdStart !== null, active: this.cast !== null, real: !!this.currentBite?.real, ...extra });
  }

  private now(): number {
    return performance.now() - this.t0;
  }

  /** Button down: no cast yet → cast; during a cast → start a hold. */
  private press(): void {
    if (!this.cast) { void this.startCast(); return; }
    if (this.holdStart !== null) return;
    this.holdStart = this.now();
    if (this.currentBite?.real) navigator.vibrate?.(20);
    this.publishState(this.currentBite ? (this.currentBite.real ? "꽉 잡아요!!" : "앗, 미끼만 건드린 거였는데…") : "아직 입질이 없어요", 0);
  }

  private release(): void {
    if (!this.cast || this.holdStart === null) return;
    const end = this.now();
    this.holds.push({ start_ms: Math.round(this.holdStart), end_ms: Math.round(end) });
    this.holdStart = null;
    this.publishState(this.currentBite?.real ? "놓쳤을지도…" : "기다리는 중…", 0);
  }

  private async startCast(): Promise<void> {
    if (this.busy || !state.token) { if (!state.token) toast("먼저 계정을 골라주세요"); return; }
    if (performance.now() < this.cooldownUntil) { this.publishState("잠깐 쉬었다가…", 0); return; }
    this.busy = true;
    try {
      const cast = await api.fishStart();
      if (!this.scene.isActive()) return;
      this.cast = cast;
      this.t0 = performance.now();
      this.holds = [];
      this.holdStart = null;
      this.currentBite = null;
      this.publishState("찌를 보고 있어요…", 0);
      for (const b of cast.bites) {
        this.timers.push(window.setTimeout(() => this.showBite(b), b.at_ms));
        this.timers.push(window.setTimeout(() => this.hideBite(b), b.at_ms + b.window_ms));
      }
      const last = cast.bites[cast.bites.length - 1];
      this.timers.push(window.setTimeout(() => void this.finishCast(), last.at_ms + last.window_ms + cast.hold_ms + FINISH_GRACE_MS));
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "network";
      this.publishState(code === "fish_cooldown" ? "잠깐 쉬었다가…" : msgFor(code), 0);
      if (!(e instanceof ApiError)) toast(String(e));
    } finally {
      this.busy = false;
    }
  }

  private showBite(b: Bite): void {
    this.currentBite = b;
    if (this.marker) {
      this.marker.setVisible(true).setScale(b.real ? 1.4 : 0.8).setAlpha(b.real ? 1 : 0.6);
      this.tweens.killTweensOf(this.marker);
      this.tweens.add({ targets: this.marker, y: this.marker.y - (b.real ? 6 : 2), duration: 120, yoyo: true, repeat: b.real ? 3 : 1 });
    }
    if (b.real) navigator.vibrate?.(30);
    this.publishState(b.real ? "입질!! 지금 꾹!" : "…살짝 건드리네", 0, { real: b.real });
  }

  private hideBite(b: Bite): void {
    if (this.currentBite === b) this.currentBite = null;
    this.marker?.setVisible(false);
    if (this.cast) this.publishState(this.holdStart !== null ? "잡고 있어요…" : "찌를 보고 있어요…", 0);
  }

  private async finishCast(): Promise<void> {
    const cast = this.cast;
    if (!cast) return;
    if (this.holdStart !== null) this.release();
    this.cast = null;
    this.currentBite = null;
    this.marker?.setVisible(false);
    this.publishState("…", 0, { active: false });
    try {
      const r = await api.fishFinish(cast.session, this.holds);
      if (typeof r.balance === "number" && r.balance !== state.balance) { state.balance = r.balance; bus.emit("money", { balance: r.balance }); }
      bus.emit("fish:catch", { ok: r.ok, id: r.id, name: r.name, value: r.value, who: state.id ?? "" });
      this.publishState(r.ok ? `${r.name}을(를) 낚았어요! +${r.value}💰` : `놓쳤어요… ${r.name}이(가) 도망쳤어요`, 0);
    } catch (e) {
      this.publishState(e instanceof ApiError ? msgFor(e.code) : String(e), 0);
    }
    this.cooldownUntil = performance.now() + 3000;
    this.timers.push(window.setTimeout(() => { if (!this.cast) this.publishState("눌러서 낚싯대를 던져요", 0); }, 3200));
  }

  update(): void {
    if (this.cast && this.holdStart !== null) {
      const held = this.now() - this.holdStart;
      bus.emit("fish:meter", { meter: Math.min(1, held / this.cast.hold_ms), enough: held >= this.cast.hold_ms });
    }
  }

  private teardown(): void {
    for (const t of this.timers) clearTimeout(t);
    this.timers = [];
    for (const off of this.unsub) off();
    this.unsub = [];
    this.cast = null;
    this.holdStart = null;
    this.marker = null;
    bus.emit("fish:state", { status: "", meter: 0, holding: false, active: false, real: false });
  }
}
