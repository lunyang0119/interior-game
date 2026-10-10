import Phaser from "phaser";
import { bus } from "../bus";
import { ATLAS } from "../room/ItemLayer";
import { state } from "../state";
import { MAP_ATLAS } from "./MapScene";
import { assetUrl } from "../assets";

export class BootScene extends Phaser.Scene {
  constructor() {
    super("Boot");
  }

  preload(): void {
    this.load.atlas(ATLAS, assetUrl("/gen/interiors.png"), assetUrl("/gen/interiors.json"));
    // the overworld atlas (houses, tiles, markers) only exists once the map has been built
    if (state.catalog?.map) this.load.atlas(MAP_ATLAS, assetUrl("/gen/map.png"), assetUrl("/gen/map.json"));
  }

  create(data: object): void {
    // #dock deep link: go straight to the dock instead of starting the room first (both would run at once)
    if (location.hash === "#dock") { this.scene.start("Dock"); bus.emit("scene:changed", { scene: "dock" }); return; }
    this.scene.start("Room", data);
    bus.emit("scene:changed", { scene: "room" }); // the DOM bars and the BGM playlist follow the scene from the first frame
  }
}
