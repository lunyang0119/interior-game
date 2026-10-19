import Phaser from "phaser";
import { assetUrl } from "../../assets";
import { ATLAS } from "../render/tiles";
import { IC, IC_MAP } from "../render/Fx";
import { FUGITIVE_TEX } from "../render/Fugitive";

/** Loads the interiors atlas (train tiles live in it) and the cyber icons (map markers), then hands over to the train scene. */
export class TrainBoot extends Phaser.Scene {
  constructor() {
    super("TrainBoot");
  }

  preload(): void {
    this.load.atlas(ATLAS, assetUrl("/gen/interiors.png"), assetUrl("/gen/interiors.json"));
    // media/train/icons.png packs 28 px cells; icons.json = name → [x, y] (preprocess.py train-ui)
    this.load.spritesheet(IC, assetUrl("/media/train/icons.png"), { frameWidth: 28, frameHeight: 28 });
    this.load.json(IC_MAP, assetUrl("/media/train/icons.json"));
    // the fugitive's own character sheet (preprocess.py train-ui, config.TRAIN_FUGITIVE_SHEET); missing → layered silhouette
    this.load.spritesheet(FUGITIVE_TEX, assetUrl("/media/train/fugitive.png"), { frameWidth: 16, frameHeight: 32 });
  }

  create(data: object): void {
    this.scene.start("Train", data);
  }
}
