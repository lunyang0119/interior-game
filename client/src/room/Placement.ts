import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { Z_SCALE, priceOf, widthOf, type Catalog, type RoomItem } from "../catalog";
import { state } from "../state";
import { depthOf, isWallLayer, sortRowFor } from "./depth";
import { anchorUnderPointer, CELL } from "./grid";
import { makeItemSprite, type ItemLayer } from "./ItemLayer";
import { checkPlace } from "./rules";

const TINT_OK = 0x7cff7c;
const TINT_BAD = 0xff6b6b;
const FOOTPRINT_DEPTH = -90; // above rugs (-100), below furniture and avatars
const FOOTPRINT_ALPHA = 0.28;

/** Ghost-preview placement / move mode. Pointer input is fed in by RoomScene. */
export class PlacementController {
  private ghost: Phaser.GameObjects.Image | Phaser.GameObjects.TileSprite | null = null;
  private footprint: Phaser.GameObjects.Graphics | null = null;
  private itemId = "";
  private moveUid: number | null = null;
  private cell = { cx: 0, cy: 0 };
  /** wallpaper only: how many columns the ghost covers; null for everything else */
  private span: number | null = null;
  private lastSpan = new Map<string, number>(); // remembered per wallpaper so "+1" and re-opening keep the width
  private ok = false;
  private busy = false;
  private lastState = "";
  /** Called when a fresh ghost is created after "+1" so the scene can re-enable hover-follow. */
  onRestart: (() => void) | null = null;

  constructor(private scene: Phaser.Scene, private cat: Catalog, private items: ItemLayer) {}

  get active(): boolean {
    return this.ghost !== null;
  }

  begin(itemId: string): void {
    this.cancel();
    this.itemId = itemId;
    this.moveUid = null;
    const it = this.cat.byId.get(itemId)!;
    this.span = it.layer === "wallpaper" ? Math.min(this.lastSpan.get(itemId) ?? it.w, this.cat.room.cols) : null;
    this.makeGhost();
    const s = this.cat.room.spawn;
    this.setCell(s.x, s.y);
    this.publish();
  }

  beginMove(row: RoomItem): void {
    this.cancel();
    this.itemId = row.item_id;
    this.moveUid = row.uid;
    const it = this.cat.byId.get(row.item_id)!;
    this.span = it.layer === "wallpaper" ? widthOf(it, row.span) : null;
    this.items.setHidden(row.uid, true);
    this.makeGhost();
    this.setCell(row.x, row.y);
    this.publish();
  }

  /** Wallpaper width −/+ from the placement bar. */
  setSpan(delta: number): void {
    if (!this.ghost || this.span === null) return;
    const next = Phaser.Math.Clamp(this.span + delta, 1, this.cat.room.cols);
    if (next === this.span) return;
    this.span = next;
    this.lastSpan.set(this.itemId, next);
    if ("setSize" in this.ghost) this.ghost.setSize(next * CELL, this.ghost.height);
    this.setCell(this.cell.cx, this.cell.cy);
    this.publish();
  }

  private makeGhost(): void {
    const it = this.cat.byId.get(this.itemId)!;
    this.ghost = makeItemSprite(this.scene, it, this.span).setAlpha(0.75);
    // the cells a w×h item will occupy: makes "why is it red" obvious for big furniture
    this.footprint = this.scene.add.graphics().setDepth(FOOTPRINT_DEPTH);
  }

  private width(): number {
    return widthOf(this.cat.byId.get(this.itemId)!, this.span);
  }

  pointer(wx: number, wy: number): void {
    if (!this.ghost) return;
    const it = this.cat.byId.get(this.itemId)!;
    const a = anchorUnderPointer(wx, wy, this.width(), it.h);
    if (a.cx === this.cell.cx && a.cy === this.cell.cy) return; // pointer still in the same cell
    this.setCell(a.cx, a.cy);
    this.publish();
  }

  private setCell(cx: number, cy: number): void {
    if (!this.ghost) return;
    const it = this.cat.byId.get(this.itemId)!;
    this.cell = { cx, cy };
    const others = this.items.rows.filter((r) => r.uid !== this.moveUid);
    const check = checkPlace(this.cat, others, this.itemId, cx, cy, this.span);
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
      const w = this.width();
      this.footprint.clear()
        .fillStyle(color, FOOTPRINT_ALPHA).fillRect(cx * CELL, cy * CELL, w * CELL, it.h * CELL)
        .lineStyle(1, color, 0.9).strokeRect(cx * CELL + 0.5, cy * CELL + 0.5, w * CELL - 1, it.h * CELL - 1);
    }
  }

  private publish(): void {
    const it = this.cat.byId.get(this.itemId);
    const price = it ? priceOf(it, this.span) : 0;
    const width = this.span !== null ? ` · 폭 ${this.span}칸` : "";
    const label = this.moveUid !== null ? `${it?.name} 이동${width}` : `${it?.name} · ${price}💰${width}`;
    const mode = this.moveUid !== null ? "move" : "place";
    const key = `${this.active}|${label}|${this.ok}|${mode}|${this.busy}|${this.span}`;
    if (key === this.lastState) return; // nothing changed → no DOM work
    this.lastState = key;
    bus.emit("place:state", { active: this.active, label, ok: this.ok, mode, busy: this.busy, span: this.span, spanMax: this.cat.room.cols });
  }

  /** `again`: after a successful placement keep a fresh ghost of the same item (rugs, wallpaper, chairs…). */
  async confirm(again = false): Promise<void> {
    if (!this.ghost || this.busy) return;
    if (!this.ok) { toast("여기엔 못 놓아요"); return; }
    this.busy = true;
    this.publish();
    try {
      const itemId = this.itemId;
      const { cx, cy } = this.cell;
      const span = this.span;
      const wasMove = this.moveUid !== null;
      if (this.moveUid !== null) {
        const r = await api.move(this.moveUid, cx, cy, span);
        if (typeof r.balance === "number") { state.balance = r.balance; bus.emit("money", { balance: r.balance }); } // older servers omit it
      } else {
        const r = await api.place(itemId, cx, cy, span);
        state.balance = r.balance;
        bus.emit("money", { balance: r.balance });
        // show the placed item immediately so the "+1" ghost sees it as occupied before the snapshot lands
        this.items.sync([...this.items.rows, { uid: r.uid, item_id: itemId, x: cx, y: cy, z: 0, parent_uid: null, placed_by: state.id ?? "", ts: 0, span }]);
      }
      this.cancel();
      bus.emit("room:refresh"); // when the snapshot lands, RoomScene calls revalidate() so the new ghost sees the placed item
      if (again && !wasMove) {
        const it = this.cat.byId.get(itemId);
        if (it && priceOf(it, span) > state.balance) { toast("돈이 부족해서 여기까지예요"); return; }
        if (span !== null) this.lastSpan.set(itemId, span);
        this.begin(itemId);
        this.onRestart?.();
        // start next to what was just placed (right, then below); fall back to the same cell, shown red
        const w = this.width();
        const h = it?.h ?? 1;
        const next = [[cx + w, cy], [cx, cy + h], [cx - w, cy]].find(([x, y]) => checkPlace(this.cat, this.items.rows, itemId, x, y, span).ok);
        this.setCell(next?.[0] ?? cx, next?.[1] ?? cy);
        this.publish();
      }
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
      if (e instanceof ApiError && (e.code === "not_found" || e.code === "unauthorized")) this.cancel();
      bus.emit("room:refresh");
    } finally {
      this.busy = false;
      this.publish();
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
    this.span = null;
    this.lastState = "";
    bus.emit("place:state", { active: false, label: "", ok: false, mode: null });
  }
}
