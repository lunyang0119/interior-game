import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { Z_SCALE, type Catalog, type RoomItem } from "../catalog";
import { state } from "../state";
import { depthOf } from "./depth";
import { anchorUnderPointer, CELL } from "./grid";
import { ATLAS, type ItemLayer } from "./ItemLayer";
import { checkPlace } from "./rules";

const TINT_OK = 0x7cff7c;
const TINT_BAD = 0xff6b6b;

/** Ghost-preview placement / move mode. Pointer input is fed in by RoomScene. */
export class PlacementController {
  private ghost: Phaser.GameObjects.Image | null = null;
  private itemId = "";
  private moveUid: number | null = null;
  private cell = { cx: 0, cy: 0 };
  private ok = false;
  private busy = false;

  constructor(private scene: Phaser.Scene, private cat: Catalog, private items: ItemLayer) {}

  get active(): boolean {
    return this.ghost !== null;
  }

  begin(itemId: string): void {
    this.cancel();
    this.itemId = itemId;
    this.moveUid = null;
    this.makeGhost();
    const s = this.cat.room.spawn;
    this.setCell(s.x, s.y);
    this.publish();
  }

  beginMove(row: RoomItem): void {
    this.cancel();
    this.itemId = row.item_id;
    this.moveUid = row.uid;
    this.items.setHidden(row.uid, true);
    this.makeGhost();
    this.setCell(row.x, row.y);
    this.publish();
  }

  private makeGhost(): void {
    const it = this.cat.byId.get(this.itemId)!;
    this.ghost = this.scene.add.image(0, 0, ATLAS, it.sprite).setOrigin(0, 1).setAlpha(0.75);
  }

  pointer(wx: number, wy: number): void {
    if (!this.ghost) return;
    const it = this.cat.byId.get(this.itemId)!;
    const a = anchorUnderPointer(wx, wy, it.w, it.h);
    this.setCell(a.cx, a.cy);
    this.publish();
  }

  private setCell(cx: number, cy: number): void {
    if (!this.ghost) return;
    const it = this.cat.byId.get(this.itemId)!;
    this.cell = { cx, cy };
    const others = this.items.rows.filter((r) => r.uid !== this.moveUid);
    const check = checkPlace(this.cat, others, this.itemId, cx, cy);
    this.ok = check.ok;
    let y = (cy + it.h) * CELL;
    let sortRow = cy + it.h - 1;
    if (check.ok && check.parentUid != null) {
      const parent = this.items.get(check.parentUid);
      const pit = parent && this.cat.byId.get(parent.item_id);
      if (parent && pit) { y -= pit.surface_offset_y; sortRow = parent.y + pit.h - 1; }
    }
    this.ghost.setPosition(cx * CELL, y).setDepth(depthOf(sortRow, Z_SCALE[it.layer]) + 5).setTint(check.ok ? TINT_OK : TINT_BAD);
  }

  private publish(): void {
    const it = this.cat.byId.get(this.itemId);
    const label = this.moveUid !== null ? `${it?.name} 이동` : `${it?.name} · ${it?.price}💰`;
    bus.emit("place:state", { active: this.active, label, ok: this.ok });
  }

  async confirm(): Promise<void> {
    if (!this.ghost || this.busy) return;
    if (!this.ok) { toast("여기엔 못 놓아"); return; }
    this.busy = true;
    try {
      if (this.moveUid !== null) {
        await api.move(this.moveUid, this.cell.cx, this.cell.cy);
      } else {
        const r = await api.place(this.itemId, this.cell.cx, this.cell.cy);
        state.balance = r.balance;
        bus.emit("money", { balance: r.balance });
      }
      this.cancel();
      bus.emit("room:refresh");
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
      if (e instanceof ApiError && (e.code === "not_found" || e.code === "unauthorized")) this.cancel();
      bus.emit("room:refresh");
    } finally {
      this.busy = false;
    }
  }

  cancel(): void {
    if (this.moveUid !== null) this.items.setHidden(this.moveUid, false);
    this.moveUid = null;
    this.ghost?.destroy();
    this.ghost = null;
    bus.emit("place:state", { active: false, label: "", ok: false });
  }
}
