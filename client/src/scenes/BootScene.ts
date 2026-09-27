import Phaser from "phaser";
import { bus } from "../bus";
import { ATLAS } from "../room/ItemLayer";
import { state } from "../state";
import { MAP_ATLAS } from "./MapScene";

export class BootScene extends Phaser.Scene {
  constructor() {
    super("Boot");
  }

  preload(): void {
    this.load.atlas(ATLAS, "/gen/interiors.png", "/gen/interiors.json");
    // the overworld atlas (houses, tiles, markers) only exists once the map has been built
    if (state.catalog?.map) this.load.atlas(MAP_ATLAS, "/gen/map.png", "/gen/map.json");
  }

  create(data: object): void {
    // #dock deep link: go straight to the dock instead of starting the room first (both would run at once)
    if (location.hash === "#dock") { this.scene.start("Dock"); bus.emit("scene:changed", { scene: "dock" }); return; }
    this.scene.start("Room", data);
  }
}
