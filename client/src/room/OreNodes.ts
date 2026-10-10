/** Ore nodes in the mine (room kind "mine"): today's rocks from `GET /api/mine/nodes`, drawn as `gen/mine/<kind>.png`.
 *
 * The server owns them (mine.py): a fresh set appears at KST midnight, everyone shares it, every `POST /api/mine/hit`
 * takes one hit off a node and the hit that breaks it pays the pool. Here: draw them, block walking through them,
 * pick one as the 채광 target when the avatar stands next to it (`reach` cells, Chebyshev), send presses, and
 * mirror other people's hits from the ws `mine` message. The HUD (#minebar) shows the target and today's count.
 */

import Phaser from "phaser";
import { api, ApiError, msgFor, type MineHitResponse, type MineNode } from "../api";
import { assetUrl } from "../assets";
import { play, SFX, SFX_VOL } from "../audio/sfx";
import { bus, toast } from "../bus";
import { state } from "../state";
import type { WsMsg } from "../ws";
import { depthOf } from "./depth";
import { CELL } from "./grid";
import { cellKey, type Cell } from "./walk";

type MineMsg = Extract<WsMsg, { type: "mine" }>;
const Z_ORE = 1; // like furniture on its row (avatars on the same row draw over it)
const RING_COLOR = 0xffd35c;

export class OreNodes {
  private nodes = new Map<number, MineNode>();
  private sprites = new Map<number, Phaser.GameObjects.Image>();
  private ores = new Map<string, { name: string; hits: number }>();
  private ring: Phaser.GameObjects.Graphics;
  private target: number | null = null;
  private busy = false;
  private alive = true;
  private reach = 1;
  private lastPerDay = 0; // the day's picture (per_day / resets_at) comes with load(); a hit only moves `left`
  private lastReset = 0;
  /** cellKey of every standing node: the walk grid treats them as rock. */
  readonly blocked = new Set<number>();

  constructor(private scene: Phaser.Scene, private myCell: () => Cell | null,
              private onBalance: (balance: number) => void) {
    this.ring = scene.add.graphics().setVisible(false);
  }

  /** Fetch the ore table + today's nodes and draw them (also after a `mine_reset`). */
  async load(): Promise<void> {
    try {
      const [info, today] = await Promise.all([api.mineInfo(), api.mineNodes()]);
      if (!this.alive) return;
      this.reach = info.reach;
      this.ores = new Map(info.ores.map((o) => [o.id, { name: o.name, hits: o.hits }]));
      await this.ensureTextures(today.nodes.map((n) => n.kind));
      if (!this.alive) return;
      this.sync(today.nodes);
      this.lastPerDay = today.per_day;
      this.lastReset = today.resets_at;
      this.emitLeft(today.left);
    } catch (e) {
      if (e instanceof ApiError && e.code === "no_mine") return; // the server has no mine yet
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  }

  private ensureTextures(kinds: string[]): Promise<void> {
    const missing = [...new Set(kinds)].filter((k) => !this.scene.textures.exists(`ore_${k}`));
    if (!missing.length) return Promise.resolve();
    return new Promise((resolve) => {
      for (const k of missing) this.scene.load.image(`ore_${k}`, assetUrl(`/gen/mine/${k}.png`));
      this.scene.load.once(Phaser.Loader.Events.COMPLETE, () => resolve());
      this.scene.load.start();
    });
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
    const key = `ore_${n.kind}`;
    const img = this.scene.textures.exists(key)
      ? this.scene.add.image((n.x + 0.5) * CELL, (n.y + 1) * CELL, key).setOrigin(0.5, 1)
      : this.scene.add.image((n.x + 0.5) * CELL, (n.y + 1) * CELL, "__MISSING").setOrigin(0.5, 1);
    img.setDepth(depthOf(n.y, Z_ORE));
    this.sprites.set(n.seq, img);
  }

  private rebuildBlocked(): void {
    this.blocked.clear();
    for (const n of this.nodes.values()) this.blocked.add(cellKey(n.x, n.y));
  }

  nodeAt(cx: number, cy: number): MineNode | null {
    for (const n of this.nodes.values()) if (n.x === cx && n.y === cy) return n;
    return null;
  }

  private inReach(n: MineNode): boolean {
    const me = this.myCell();
    return !!me && Math.max(Math.abs(me.cx - n.x), Math.abs(me.cy - n.y)) <= this.reach;
  }

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
      bus.emit("loot:got", { ok: true, kind: "mine", id: r.id, name: r.name ?? r.id, value: r.value ?? 0, who: state.id ?? "",
        seq: r.ledger_seq ?? null, deliverable: r.deliverable ?? [] });
    }
    this.emitLeft(r.left);
  }

  /** Somebody (maybe me — my own answer already applied it) hit a node in this room. */
  onMessage(m: MineMsg): void {
    if (m.by === state.id) return;
    const n = this.nodes.get(m.seq);
    if (!n) return;
    this.applyProgress(m.seq, m.hits_left, m.done);
    if (m.done && m.loot) toast(`${m.by}가 ${m.loot.name}을(를) 캤어요${m.loot.value > 0 ? ` (+${m.loot.value}💰)` : ""}`);
    this.emitLeft(m.left);
  }

  private emitLeft(left: number): void {
    bus.emit("mine:left", { left, per_day: this.lastPerDay, resets_at: this.lastReset });
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
    this.blocked.clear();
    this.ring.destroy();
    this.target = null;
    bus.emit("mine:target", null);
  }
}
