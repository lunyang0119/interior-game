import Phaser from "phaser";
import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { Z_HUNG, Z_HUNG_PAPER, Z_SCALE, canHang, collisionLayer, heightOf, isFloorPaper, onWall, paperCells, priceOf, stretchCols, stretchRows, widthOf, type Catalog, type Room, type RoomItem } from "../catalog";
import { state } from "../state";
import { depthOf, sortRowFor } from "./depth";
import { anchorUnderPointer, CELL } from "./grid";
import { makeItemSprite, tintSprite, type ItemLayer, type ItemSprite, type Pasted } from "./ItemLayer";
import { checkPlace } from "./rules";

const TINT_OK = 0x7cff7c;
const TINT_BAD = 0xff6b6b;
const FOOTPRINT_DEPTH = -90; // above rugs (-100), below furniture and avatars
const FOOTPRINT_ALPHA = 0.28;

/** Ghost-preview placement / move mode. Pointer input is fed in by RoomScene. */
export class PlacementController {
  private ghost: ItemSprite | null = null;
  /** What the ghost sprite was built for (wallpaper: span, and where it is pasted); a change rebuilds it. */
  private ghostShape = "";
  private footprint: Phaser.GameObjects.Graphics | null = null;
  private itemId = "";
  private moveUid: number | null = null;
  private cell = { cx: 0, cy: 0 };
  /** wallpaper / floor patterns: how many columns the ghost covers; null for everything else */
  private span: number | null = null;
  /** floor patterns: how many rows; null for everything else */
  private spanH: number | null = null;
  private lastSpan = new Map<string, number>(); // remembered per item so "+1" and re-opening keep the width
  private lastSpanH = new Map<string, number>();
  private ok = false;
  private busy = false;
  private lastState = "";
  /** Called when a fresh ghost is created after "+1" so the scene can re-enable hover-follow. */
  onRestart: (() => void) | null = null;

  constructor(private scene: Phaser.Scene, private cat: Catalog, private room: Room, private items: ItemLayer) {}

  get active(): boolean {
    return this.ghost !== null;
  }

  /** Start placing a new item; the ghost appears at `at` (the avatar's cell) or the room spawn. */
  begin(itemId: string, at?: { cx: number; cy: number }): void {
    this.cancel();
    this.itemId = itemId;
    this.moveUid = null;
    const it = this.cat.byId.get(itemId)!;
    this.span = stretchCols(it) ? Math.min(this.lastSpan.get(itemId) ?? it.w, this.room.cols) : null;
    this.spanH = stretchRows(it) ? Math.min(this.lastSpanH.get(itemId) ?? it.h, this.room.rows) : null;
    this.makeGhost();
    const s = at ? { x: at.cx, y: at.cy } : this.room.spawn;
    this.setCell(s.x, s.y);
    this.publish();
  }

  beginMove(row: RoomItem): void {
    this.cancel();
    this.itemId = row.item_id;
    this.moveUid = row.uid;
    const it = this.cat.byId.get(row.item_id)!;
    this.span = stretchCols(it) ? widthOf(it, row.span) : null;
    this.spanH = stretchRows(it) ? heightOf(it, row.span_h) : null;
    this.items.setHidden(row.uid, true);
    this.makeGhost();
    this.setCell(row.x, row.y);
    this.publish();
  }

  /** Width ("w": wallpaper, floor patterns) or height ("h": floor patterns) −/+ from the placement bar. */
  setSpan(delta: number, axis: "w" | "h" = "w"): void {
    if (!this.ghost) return;
    if (axis === "h") {
      if (this.spanH === null) return;
      const next = Phaser.Math.Clamp(this.spanH + delta, 1, this.room.rows);
      if (next === this.spanH) return;
      this.spanH = next;
      this.lastSpanH.set(this.itemId, next);
    } else {
      if (this.span === null) return;
      const next = Phaser.Math.Clamp(this.span + delta, 1, this.room.cols);
      if (next === this.span) return;
      this.span = next;
      this.lastSpan.set(this.itemId, next);
    }
    this.setCell(this.cell.cx, this.cell.cy);
    this.publish();
  }

  private makeGhost(): void {
    const it = this.cat.byId.get(this.itemId)!;
    this.ghost = makeItemSprite(this.scene, it, this.span, null, this.spanH).setAlpha(0.75);
    this.ghostShape = `${this.span ?? ""}x${this.spanH ?? ""}`;
    // the cells a w×h item will occupy: makes "why is it red" obvious for big furniture
    this.footprint = this.scene.add.graphics().setDepth(FOOTPRINT_DEPTH);
  }

  private width(): number {
    return widthOf(this.cat.byId.get(this.itemId)!, this.span);
  }

  private height(): number {
    return heightOf(this.cat.byId.get(this.itemId)!, this.spanH);
  }

  pointer(wx: number, wy: number): void {
    if (!this.ghost) return;
    const a = anchorUnderPointer(wx, wy, this.width(), this.height());
    if (a.cx === this.cell.cx && a.cy === this.cell.cy) return; // pointer still in the same cell
    this.setCell(a.cx, a.cy);
    this.publish();
  }

  private setCell(cx: number, cy: number): void {
    if (!this.ghost) return;
    const it = this.cat.byId.get(this.itemId)!;
    this.cell = { cx, cy };
    const others = this.items.rows.filter((r) => r.uid !== this.moveUid);
    const check = checkPlace(this.cat, this.room, others, this.itemId, cx, cy, this.span, this.spanH);
    this.ok = check.ok;
    // wallpaper on the floor rows: strips over the painted 벽지 칸 (a plain red strip where nothing is painted)
    const cells = isFloorPaper(it, this.room, cy) ? paperCells(this.room, cx, cy, this.width(), it.h) : null;
    const pasted: Pasted | null = cells ? { x: cx, y: cy, cells } : null;
    const shape = pasted ? `${this.span ?? ""}@${cx},${cy}` : `${this.span ?? ""}x${this.spanH ?? ""}`;
    if (shape !== this.ghostShape) {
      this.ghost.destroy();
      this.ghost = makeItemSprite(this.scene, it, this.span, pasted, this.spanH).setAlpha(0.75);
      this.ghostShape = shape;
    }
    const h = this.height();
    let y = (onWall(it) ? cy * CELL : (cy + h) * CELL) + (it.offset_y ?? 0);
    let sortRow = sortRowFor(collisionLayer(it), cy + h - 1);
    let z = Z_SCALE[collisionLayer(it)];
    if (check.ok && check.parentUid != null) {
      const parent = this.items.get(check.parentUid);
      const pit = parent && this.cat.byId.get(parent.item_id);
      if (parent && pit) {
        sortRow = parent.y + pit.h - 1;
        if (canHang(it)) z = Z_HUNG; // hung on a partition
        else y -= pit.surface_offset_y; // on a table
      }
    }
    if (cells) {
      sortRow = Math.max(...cells.map((c) => c[1]));
      z = Z_HUNG_PAPER;
    }
    this.ghost.setPosition(cx * CELL, y).setDepth(depthOf(sortRow, z) + 5);
    tintSprite(this.ghost, check.ok ? TINT_OK : TINT_BAD);
    if (this.footprint) {
      const color = check.ok ? TINT_OK : TINT_BAD;
      this.footprint.clear().fillStyle(color, FOOTPRINT_ALPHA).lineStyle(1, color, 0.9);
      if (cells) {
        for (const [x, yy] of cells) this.footprint.fillRect(x * CELL, yy * CELL, CELL, CELL);
      } else {
        const w = this.width();
        this.footprint.fillRect(cx * CELL, cy * CELL, w * CELL, h * CELL)
          .strokeRect(cx * CELL + 0.5, cy * CELL + 0.5, w * CELL - 1, h * CELL - 1);
      }
    }
  }

  private publish(): void {
    const it = this.cat.byId.get(this.itemId);
    const price = it ? priceOf(it, this.span, this.spanH) : 0;
    const size = this.spanH !== null ? ` · ${this.span}×${this.spanH}칸` : this.span !== null ? ` · 폭 ${this.span}칸` : "";
    const label = this.moveUid !== null ? `${it?.name} 이동${size}` : `${it?.name} · ${price}{coin}${size}`;
    const mode = this.moveUid !== null ? "move" : "place";
    const key = `${this.active}|${label}|${this.ok}|${mode}|${this.busy}|${this.span}|${this.spanH}`;
    if (key === this.lastState) return; // nothing changed → no DOM work
    this.lastState = key;
    bus.emit("place:state", { active: this.active, label, ok: this.ok, mode, busy: this.busy, span: this.span, spanMax: this.room.cols, spanH: this.spanH, spanHMax: this.room.rows });
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
      const spanH = this.spanH;
      const wasMove = this.moveUid !== null;
      if (this.moveUid !== null) {
        const r = await api.move(this.moveUid, cx, cy, span, spanH);
        if (typeof r.balance === "number") { state.balance = r.balance; bus.emit("money", { balance: r.balance }); } // older servers omit it
      } else {
        const r = await api.place(this.room.id, itemId, cx, cy, span, spanH);
        state.balance = r.balance;
        bus.emit("money", { balance: r.balance });
        // show the placed item immediately so the "+1" ghost sees it as occupied before the snapshot lands
        this.items.sync([...this.items.rows, { uid: r.uid, item_id: itemId, x: cx, y: cy, z: 0, parent_uid: null, placed_by: state.id ?? "", ts: 0, span, span_h: spanH, room_id: this.room.id }]);
      }
      this.cancel();
      bus.emit("room:refresh"); // when the snapshot lands, RoomScene calls revalidate() so the new ghost sees the placed item
      if (again && !wasMove) {
        const it = this.cat.byId.get(itemId);
        if (it && priceOf(it, span, spanH) > state.balance) { toast("돈이 부족해서 여기까지예요"); return; }
        if (span !== null) this.lastSpan.set(itemId, span);
        if (spanH !== null) this.lastSpanH.set(itemId, spanH);
        this.begin(itemId);
        this.onRestart?.();
        // start next to what was just placed (right, then below); fall back to the same cell, shown red
        const w = this.width();
        const h = this.height();
        const next = [[cx + w, cy], [cx, cy + h], [cx - w, cy]].find(([x, y]) => checkPlace(this.cat, this.room, this.items.rows, itemId, x, y, span, spanH).ok);
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
    this.spanH = null;
    this.lastState = "";
    bus.emit("place:state", { active: false, label: "", ok: false, mode: null });
  }
}
