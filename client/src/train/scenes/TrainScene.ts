import Phaser from "phaser";
import { Gestures } from "../../input/Gestures";
import { CameraController } from "../../scenes/CameraController";
import type { MapDetail } from "../api";
import { tbus } from "../bus";
import { CarMap } from "../render/CarMap";
import { buildLayout, roomAt } from "../render/layout";
import { CELL } from "../../room/grid";

export interface TrainSceneData {
  map: MapDetail;
  preview?: boolean;
}

/** The train car. In preview mode it only shows the data-driven layout of one map (admin check of the art). */
export class TrainScene extends Phaser.Scene {
  private carMap!: CarMap;
  private camCtl!: CameraController;
  private gestures!: Gestures;
  private data_!: TrainSceneData;

  constructor() {
    super("Train");
  }

  init(data: TrainSceneData): void {
    this.data_ = data;
  }

  create(): void {
    const layout = buildLayout(this.data_.map.rooms);
    this.carMap = new CarMap(this, layout);
    this.cameras.main.setBackgroundColor("#14141c");
    this.camCtl = new CameraController(this, { worldW: this.carMap.widthPx, worldH: this.carMap.heightPx, minZoom: 1, maxZoom: 4, targetRows: layout.rows });
    this.gestures = new Gestures(this, {
      tap: (p) => {
        const w = this.camCtl.screenToWorld(p.x, p.y);
        const b = roomAt(layout, Math.floor(w.x / CELL), Math.floor(w.y / CELL));
        tbus.emit("room:tap", { room: b?.id ?? null });
      },
      pan: (dx, dy) => this.camCtl.panBy(dx, dy),
      pinch: (ratio, mid) => this.camCtl.pinch(ratio, mid),
      pinchEnd: () => this.camCtl.pinchEnd(),
      wheel: (dy, p) => this.camCtl.wheel(dy, { x: p.x, y: p.y }),
    });
    const offGrid = tbus.on("preview:grid", ({ on }) => this.carMap.showGrid(on));
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      offGrid();
      this.gestures.destroy();
      this.camCtl.destroy();
      this.carMap.destroy();
    });
    tbus.emit("scene:ready", { rooms: layout.rooms.size });
  }

  update(): void {
    this.camCtl.update();
  }
}
