import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { Z_SCALE, type Catalog, type RoomItem } from "../catalog";
import { state } from "../state";
import { depthOf, isWallLayer, sortRowFor } from "./depth";
import { anchorUnderPointer, CELL } from "./grid";
import { ATLAS, type ItemLayer } from "./ItemLayer";
import { checkPlace } from "./rules";

const TINT_OK = 0x7cff7c;
const TINT_BAD = 0xff6b6b;
const FOOTPRINT_DEPTH = -90; // above rugs (-100), below furniture and avatars
const FOOTPRINT_ALPHA = 0.28;

/** Ghost-preview placement / move mode. Pointer input is fed in by RoomScene. */
export class PlacementController {
  private ghost: Phaser.GameObjects.Image | null = null;
  private footprint: Phaser.GameObjects.Graphics | null = null;
  private itemId = "";
  private moveUid: number | null = null;
  private cell = { cx: 0, cy: 0 };
  private ok = false;
  private busy = false;
  private lastState = "";

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
    this.ghost = this.scene.add.image(0, 0, ATLAS, it.sprite).setOrigin(0, isWallLayer(it.layer) ? 0 : 1).setAlpha(0.75);
    // the cells a w×h item will occupy: makes "why is it red" obvious for big furniture
    this.footprint = this.scene.add.graphics().setDepth(FOOTPRINT_DEPTH);
  }

  pointer(wx: number, wy: number): void {
    if (!this.ghost) return;
    const it = this.cat.byId.get(this.itemId)!;
    const a = anchorUnderPointer(wx, wy, it.w, it.h);
    if (a.cx === this.cell.cx && a.cy === this.cell.cy) return; // pointer still in the same cell
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
    let y = isWallLayer(it.layer) ? cy * CELL : (cy + it.h) * CELL;
    let sortRow = sortRowFor(it.layer, cy + it.h - 1);
    if (check.ok && check.parentUid != null) {
      const parent = this.items.get(check.parentUid);
      const pit = parent && this.cat.byId.get(parent.item_id);
      if (parent && pit) { y -= pit.surface_offset_y; sortRow = parent.y + pit.h - 1; }
    }
    this.ghost.setPosition(cx * CELL, y).setDepth(depthOf(sortRow, Z_SCALE[it.layer]) + 5).setTint(check.ok ? TINT_OK : TINT_BAD);
    if (this.footprint) {
      const color = check.ok ? TINT_OK : TINT_BAD;
      this.footprint.clear()
        .fillStyle(color, FOOTPRINT_ALPHA).fillRect(cx * CELL, cy * CELL, it.w * CELL, it.h * CELL)
        .lineStyle(1, color, 0.9).strokeRect(cx * CELL + 0.5, cy * CELL + 0.5, it.w * CELL - 1, it.h * CELL - 1);
    }
  }

  private publish(): void {
    const it = this.cat.byId.get(this.itemId);
    const label = this.moveUid !== null ? `${it?.name} 이동` : `${it?.name} · ${it?.price}💰`;
    const mode = this.moveUid !== null ? "move" : "place";
    const key = `${this.active}|${label}|${this.ok}|${mode}`;
    if (key === this.lastState) return; // nothing changed → no DOM work
    this.lastState = key;
    bus.emit("place:state", { active: this.active, label, ok: this.ok, mode });
  }

  /** `again`: after a successful placement keep a fresh ghost of the same item (rugs, wallpaper, chairs…). */
  async confirm(again = false): Promise<void> {
    if (!this.ghost || this.busy) return;
    if (!this.ok) { toast("여기엔 못 놓아요"); return; }
    this.busy = true;
    try {
      if (this.moveUid !== null) {
        await api.move(this.moveUid, this.cell.cx, this.cell.cy);
      } else {
        const r = await api.place(this.itemId, this.cell.cx, this.cell.cy);
        state.balance = r.balance;
        bus.emit("money", { balance: r.balance });
      }
      const itemId = this.itemId;
      const { cx, cy } = this.cell;
      const wasMove = this.moveUid !== null;
      this.cancel();
      bus.emit("room:refresh"); // when the snapshot lands, RoomScene calls revalidate() so the new ghost sees the placed item
      if (again && !wasMove) {
        const it = this.cat.byId.get(itemId);
        if (it && it.price > state.balance) { toast("돈이 부족해서 여기까지예요"); return; }
        this.begin(itemId);
        this.setCell(cx, cy);
        this.publish();
      }
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
      if (e instanceof ApiError && (e.code === "not_found" || e.code === "unauthorized")) this.cancel();
      bus.emit("room:refresh");
    } finally {
      this.busy = false;
    }
  }

  /** Room snapshot changed while placing: re-run the rule check for the current cell. */
  revalidate(): void {
    if (!this.ghost) return;
    this.setCell(this.cell.cx, this.cell.cy);
    this.publish();
  }

  cancel(): void {
    if (this.moveUid !== null) this.items.setHidden(this.moveUid, false);
    this.moveUid = null;
    this.ghost?.destroy();
    this.ghost = null;
    this.footprint?.destroy();
    this.footprint = null;
    this.lastState = "";
    bus.emit("place:state", { active: false, label: "", ok: false, mode: null });
  }
}
