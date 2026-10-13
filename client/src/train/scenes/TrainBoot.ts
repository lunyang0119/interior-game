import Phaser from "phaser";
import { assetUrl } from "../../assets";
import { ATLAS } from "../render/tiles";

/** Loads the interiors atlas (train tiles live in it) and hands over to the train scene. */
export class TrainBoot extends Phaser.Scene {
  constructor() {
    super("TrainBoot");
  }

  preload(): void {
    this.load.atlas(ATLAS, assetUrl("/gen/interiors.png"), assetUrl("/gen/interiors.json"));
  }

  create(data: object): void {
    this.scene.start("Train", data);
  }
}
