import Phaser from "phaser";
import { ATLAS } from "../room/ItemLayer";

export class BootScene extends Phaser.Scene {
  constructor() {
    super("Boot");
  }

  preload(): void {
    this.load.atlas(ATLAS, "/gen/interiors.png", "/gen/interiors.json");
  }

  create(data: object): void {
    this.scene.start("Room", data);
  }
}
