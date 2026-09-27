import Phaser from "phaser";
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
    this.scene.start("Room", data);
  }
}
