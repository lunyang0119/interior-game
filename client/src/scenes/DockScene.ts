import Phaser from "phaser";
import { bus } from "../bus";
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
interface DockLayout { w: number; h: number; layers: DockLayer[] }

const MAP_ATLAS = "map";

/** The dock: a layered backdrop with no avatar. Buttons (나가기 / 낚시) live in the DOM (#dockbar). */
export class DockScene extends Phaser.Scene {
  private layout: DockLayout | null = null;

  constructor() {
    super("Dock");
  }

  preload(): void {
    this.load.json("dock-layout", `/gen/dock.json?t=${Date.now()}`);
  }

  create(): void {
    // presence: leave the room we came from (nobody is drawn here, but the room's head count should drop)
    if (state.token) {
      if (socket.connected) socket.sendEnter("dock");
      this.events.once(Phaser.Scenes.Events.SHUTDOWN, socket.on("hello", () => socket.sendEnter("dock")));
    }
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
      if (l.kind === "slice" && l.atlas === "map" && !this.textures.exists(MAP_ATLAS)) this.load.atlas(MAP_ATLAS, "/gen/map.png", "/gen/map.json");
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
    bus.emit("dock:ready");
  }
}
