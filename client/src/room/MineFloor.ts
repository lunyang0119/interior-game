/** One floor of the mine (room kind "mine"): today's rocks, ore nodes and ladder from `GET /api/mine/floor/{n}`.
 *
 * The server owns the layout (mine.py): every KST day each floor gets fresh rock clusters (partition sprites
 * that block walking), `nodes_per_floor` ore nodes and one dud that hides the ladder down; everyone on the floor
 * shares it. Here: draw it all from the interior atlas (`ore.sprite`, rock keys, `ladder`), block walking
 * through rocks and floor nodes, pick a node as the 채광 target when the avatar stands next to it (`reach`
 * cells, Chebyshev; wall ores are mined from the floor cell below), send presses, mirror other people's hits
 * from the ws `mine` message, and tell the scene when the avatar stands on the open ladder. The HUD (#minebar)
 * shows the target and the floor's count.
 */

import Phaser from "phaser";
import { api, ApiError, msgFor, type MineHitResponse, type MineNode, type MineOre } from "../api";
import { play, SFX, SFX_VOL } from "../audio/sfx";
import { bus, toast } from "../bus";
import { Z_SCALE } from "../catalog";
import { state } from "../state";
import type { WsMsg } from "../ws";
import { depthOf, TILE_DEPTH } from "./depth";
import { CELL } from "./grid";
import { ATLAS } from "./ItemLayer";
import { cellKey, type Cell } from "./walk";

type MineMsg = Extract<WsMsg, { type: "mine" }>;
const Z_ORE = Z_SCALE.furniture; // like furniture on its row (avatars on the row below draw over it)
const RING_COLOR = 0xffd35c;
const HOLE_COLOR = 0x120c0a;

export class MineFloor {
  private nodes = new Map<number, MineNode>();
  private sprites = new Map<number, Phaser.GameObjects.Image>();
  private rocks: Phaser.GameObjects.Image[] = [];
  private ladderSprite: Phaser.GameObjects.GameObject | null = null;
  private ladder: { x: number; y: number } | null = null;
  private ores = new Map<string, MineOre>();
  private ladderKey: string | null = null;
  private ring: Phaser.GameObjects.Graphics;
  private target: number | null = null;
  private busy = false;
  private alive = true;
  private reach = 1;
  private perFloor = 0; // the floor's picture (per_floor / resets_at) comes with load(); a hit only moves `left`
  private lastReset = 0;
  /** cellKey of every rock and standing floor node: the walk grid treats them as solid. */
  readonly blocked = new Set<number>();
  /** Called when the ladder opens (my hit or somebody's): the scene checks whether I already stand on it. */
  onLadder: (() => void) | null = null;

  constructor(private scene: Phaser.Scene, readonly floor: number, private myCell: () => Cell | null,
              private onBalance: (balance: number) => void) {
    this.ring = scene.add.graphics().setVisible(false);
  }

  /** Fetch the ore table + this floor's layout and draw it (also after a `mine_reset`). */
  async load(): Promise<void> {
    try {
      const [info, today] = await Promise.all([api.mineInfo(), api.mineFloor(this.floor)]);
      if (!this.alive) return;
      this.reach = info.reach;
      this.ladderKey = info.ladder;
      this.ores = new Map(info.ores.map((o) => [o.id, o]));
      this.drawRocks(today.rocks);
      this.sync(today.nodes);
      this.setLadder(today.ladder);
      this.perFloor = today.per_floor;
      this.lastReset = today.resets_at;
      this.emitLeft(today.left);
    } catch (e) {
      if (e instanceof ApiError && e.code === "no_mine") return; // the server has no mine yet
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  }

  // ---------------------------------------------------------------- drawing

  private drawRocks(list: [number, number, string][]): void {
    for (const r of this.rocks) r.destroy();
    this.rocks = [];
    const atlas = this.scene.textures.get(ATLAS);
    for (const [x, y, key] of list) {
      const img = atlas.has(key)
        ? this.scene.add.image((x + 0.5) * CELL, (y + 1) * CELL, ATLAS, key).setOrigin(0.5, 1)
        : this.scene.add.image((x + 0.5) * CELL, (y + 1) * CELL, "__MISSING").setOrigin(0.5, 1); // slice not in this atlas build
      img.setDepth(depthOf(y, Z_ORE));
      this.rocks.push(img);
    }
    this.rebuildBlocked(list);
  }

  /** Replace the picture with the server's: new nodes appear, broken ones go, hit counts update. */
  private sync(list: MineNode[]): void {
    const seen = new Set<number>();
    for (const n of list) {
      seen.add(n.seq);
      const prev = this.nodes.get(n.seq);
      this.nodes.set(n.seq, n);
      if (!prev) this.draw(n);
    }
    for (const seq of [...this.nodes.keys()]) if (!seen.has(seq)) this.remove(seq, false);
    this.rebuildBlocked();
    this.refreshTarget();
  }

  private draw(n: MineNode): void {
    const key = this.ores.get(n.kind)?.sprite ?? `ore_${n.kind}`;
    const atlas = this.scene.textures.get(ATLAS);
    const img = atlas.has(key)
      ? this.scene.add.image((n.x + 0.5) * CELL, (n.y + 1) * CELL, ATLAS, key).setOrigin(0.5, 1)
      : this.scene.add.image((n.x + 0.5) * CELL, (n.y + 1) * CELL, "__MISSING").setOrigin(0.5, 1);
    img.setDepth(depthOf(n.y, Z_ORE));
    this.sprites.set(n.seq, img);
  }

  private rockCells: [number, number, string][] = [];

  private rebuildBlocked(rocks?: [number, number, string][]): void {
    if (rocks) this.rockCells = rocks;
    this.blocked.clear();
    for (const [x, y] of this.rockCells) this.blocked.add(cellKey(x, y));
    for (const n of this.nodes.values()) if (!n.wall) this.blocked.add(cellKey(n.x, n.y));
  }

  private setLadder(l: { x: number; y: number } | null): void {
    if (this.ladder && l && this.ladder.x === l.x && this.ladder.y === l.y) return;
    this.ladderSprite?.destroy();
    this.ladderSprite = null;
    this.ladder = l;
    if (!l) return;
    const atlas = this.scene.textures.get(ATLAS);
    if (this.ladderKey && atlas.has(this.ladderKey)) {
      this.ladderSprite = this.scene.add.image((l.x + 0.5) * CELL, (l.y + 1) * CELL, ATLAS, this.ladderKey)
        .setOrigin(0.5, 1).setDepth(TILE_DEPTH + 1);
    } else {
      // no ladder slice in this build of the atlas: a dark hole with a "▼"
      const g = this.scene.add.graphics().setDepth(TILE_DEPTH + 1);
      g.fillStyle(HOLE_COLOR, 1).fillRoundedRect(l.x * CELL + 2, l.y * CELL + 3, CELL - 4, CELL - 5, 3);
      g.fillStyle(0xffd35c, 0.9).fillTriangle(l.x * CELL + 5, l.y * CELL + 6, l.x * CELL + CELL - 5, l.y * CELL + 6, l.x * CELL + CELL / 2, l.y * CELL + CELL - 4);
      this.ladderSprite = g;
    }
  }

  // ---------------------------------------------------------------- queries

  nodeAt(cx: number, cy: number): MineNode | null {
    for (const n of this.nodes.values()) if (n.x === cx && n.y === cy) return n;
    return null;
  }

  /** The floor cell to walk to for mining a node (a wall ore is mined from the cell below it). */
  standCell(n: MineNode): Cell {
    return { cx: n.x, cy: n.wall ? n.y + 1 : n.y };
  }

  ladderAt(cx: number, cy: number): boolean {
    return !!this.ladder && this.ladder.x === cx && this.ladder.y === cy;
  }

  ladderCell(): Cell | null {
    return this.ladder ? { cx: this.ladder.x, cy: this.ladder.y } : null;
  }

  private inReach(n: MineNode): boolean {
    const me = this.myCell();
    return !!me && Math.max(Math.abs(me.cx - n.x), Math.abs(me.cy - n.y)) <= this.reach;
  }

  // ---------------------------------------------------------------- target

  /** Make `seq` the 채광 target when the avatar stands next to it. Returns false (and says so unless `quiet`)
   *  when it is out of reach or gone. */
  select(seq: number, quiet = false): boolean {
    const n = this.nodes.get(seq);
    if (!n) { if (!quiet) toast("이미 캐낸 광석이에요"); return false; }
    if (!this.inReach(n)) { if (!quiet) toast("광석 옆으로 가야 해요"); return false; }
    this.target = seq;
    this.publishTarget();
    return true;
  }

  /** The avatar moved: a target it walked away from is dropped. */
  refreshTarget(): void {
    if (this.target === null) return;
    const n = this.nodes.get(this.target);
    if (!n || !this.inReach(n)) { this.target = null; this.publishTarget(); }
    else this.publishTarget();
  }

  private publishTarget(): void {
    const n = this.target !== null ? this.nodes.get(this.target) : undefined;
    if (!n) {
      this.ring.setVisible(false);
      bus.emit("mine:target", null);
      return;
    }
    this.ring.clear().lineStyle(1, RING_COLOR, 0.9).strokeRoundedRect(n.x * CELL + 1, n.y * CELL + 1, CELL - 2, CELL - 2, 3)
      .setDepth(depthOf(n.y, Z_ORE) - 1).setVisible(true);
    const ore = this.ores.get(n.kind);
    bus.emit("mine:target", { seq: n.seq, name: ore?.name ?? n.kind, hits_left: n.hits_left, hits: ore?.hits ?? n.hits });
  }

  // ---------------------------------------------------------------- mining

  /** One press of 채광 on the target (one request at a time; presses during the cooldown are dropped server-side). */
  hitTarget(): void {
    if (this.busy || this.target === null || !state.token) return;
    const seq = this.target;
    const n = this.nodes.get(seq);
    if (!n || !this.inReach(n)) { this.refreshTarget(); return; }
    this.busy = true;
    play(SFX.pick, { volume: SFX_VOL.ui });
    api.mineHit(seq)
      .then((r) => { if (this.alive) this.applyHit(r); })
      .catch((e) => {
        if (!(e instanceof ApiError)) { toast(String(e)); return; }
        if (e.code === "mine_cooldown") return; // pressed too fast: the next press counts
        if (e.code === "node_gone") { this.remove(seq, true); this.rebuildBlocked(); this.refreshTarget(); void this.load(); return; }
        if (e.code === "not_here") { this.refreshTarget(); }
        toast(msgFor(e.code));
      })
      .finally(() => { this.busy = false; });
  }

  private applyHit(r: MineHitResponse): void {
    this.onBalance(r.balance);
    this.applyProgress(r.seq, r.hits_left, r.done);
    if (r.done && r.id) {
      if ((r.value ?? 0) > 0) {
        bus.emit("loot:got", { ok: true, kind: "mine", id: r.id, name: r.name ?? r.id, value: r.value ?? 0, who: state.id ?? "",
          seq: r.ledger_seq ?? null, deliverable: r.deliverable ?? [] });
      }
      if (r.ladder) this.uncover(r.ladder, true);
    }
    this.emitLeft(r.left);
  }

  /** Somebody (maybe me — my own answer already applied it) hit a node on this floor. */
  onMessage(m: MineMsg): void {
    if (m.floor !== this.floor) return;
    if (m.by === state.id) return;
    const n = this.nodes.get(m.seq);
    if (!n) return;
    this.applyProgress(m.seq, m.hits_left, m.done);
    if (m.done && m.loot && m.loot.value > 0) toast(`${m.by}가 ${m.loot.name}을(를) 캤어요 (+${m.loot.value}💰)`);
    if (m.ladder) this.uncover(m.ladder, false);
    this.emitLeft(m.left);
  }

  private uncover(l: { x: number; y: number }, mine: boolean): void {
    this.setLadder(l);
    toast(mine ? "아래로 내려가는 사다리가 나왔어요!" : "누군가 사다리를 찾았어요");
    this.onLadder?.();
  }

  private emitLeft(left: number): void {
    bus.emit("mine:left", { left, per_floor: this.perFloor, floor: this.floor, resets_at: this.lastReset });
  }

  private applyProgress(seq: number, hitsLeft: number, done: boolean): void {
    const n = this.nodes.get(seq);
    const img = this.sprites.get(seq);
    if (!n) return;
    n.hits_left = hitsLeft;
    if (done) {
      this.remove(seq, true);
      this.rebuildBlocked();
      if (this.target === seq) this.target = null;
      this.publishTarget();
      return;
    }
    if (img) {
      this.scene.tweens.killTweensOf(img);
      const x0 = (n.x + 0.5) * CELL;
      img.setX(x0);
      this.scene.tweens.add({ targets: img, x: x0 - 1.5, duration: 40, yoyo: true, repeat: 2, onComplete: () => img.setX(x0) });
    }
    if (this.target === seq) this.publishTarget();
  }

  /** Drop a node; `pop` plays the break animation. */
  private remove(seq: number, pop: boolean): void {
    this.nodes.delete(seq);
    const img = this.sprites.get(seq);
    this.sprites.delete(seq);
    if (!img) return;
    this.scene.tweens.killTweensOf(img);
    if (!pop) { img.destroy(); return; }
    this.scene.tweens.add({ targets: img, scaleX: 1.4, scaleY: 0.2, alpha: 0, y: img.y - 4, duration: 180, ease: "Quad.easeOut",
      onComplete: () => img.destroy() });
  }

  destroy(): void {
    this.alive = false;
    for (const img of this.sprites.values()) { this.scene.tweens.killTweensOf(img); img.destroy(); }
    this.sprites.clear();
    this.nodes.clear();
    for (const r of this.rocks) r.destroy();
    this.rocks = [];
    this.ladderSprite?.destroy();
    this.ladderSprite = null;
    this.blocked.clear();
    this.ring.destroy();
    this.target = null;
    bus.emit("mine:target", null);
  }
}
