/** Scene effects: signal markers (◎), locked doors (⛔), steam, blackout, speech bubbles, room/door highlights. */

import Phaser from "phaser";
import { CELL } from "../../room/grid";
import { TILE_DEPTH } from "../../room/depth";
import { ROOM_H, ROOM_W, type Layout } from "./layout";

const FX_DEPTH = 900_000;       // above furniture and avatars
const OVERLAY_DEPTH = 950_000;  // full-screen effects
const BUBBLE_DEPTH = 990_000;

export class Fx {
  private markers = new Map<string, Phaser.GameObjects.Text>();
  private locks = new Map<string, Phaser.GameObjects.Text>();
  private steam = new Map<string, Phaser.GameObjects.GameObject[]>();
  private highlight: Phaser.GameObjects.Graphics;
  private dark: Phaser.GameObjects.Rectangle;
  private objects: Phaser.GameObjects.GameObject[] = [];

  constructor(private scene: Phaser.Scene, private layout: Layout, private doorAt: (edge: string) => { x: number; y: number } | null) {
    this.highlight = scene.add.graphics().setDepth(TILE_DEPTH + 4);
    this.dark = scene.add.rectangle(0, 0, 10, 10, 0x000000, 0).setOrigin(0).setScrollFactor(0).setDepth(OVERLAY_DEPTH);
    this.resizeDark();
    scene.scale.on(Phaser.Scale.Events.RESIZE, this.resizeDark, this);
  }

  private resizeDark = (): void => {
    const cam = this.scene.cameras.main;
    this.dark.setSize(this.scene.scale.width / cam.zoom + 4, this.scene.scale.height / cam.zoom + 4);
  };

  roomCenter(room: string): { x: number; y: number } | null {
    const b = this.layout.rooms.get(room);
    return b ? { x: (b.x0 + ROOM_W / 2) * CELL, y: (b.y0 + ROOM_H / 2) * CELL } : null;
  }

  private text(x: number, y: number, s: string, size = 12, color = "#ffd54a"): Phaser.GameObjects.Text {
    const t = this.scene.add.text(x, y, s, { fontFamily: '"Label", sans-serif', fontSize: `${size}px`, color, stroke: "#000", strokeThickness: 3, resolution: 3 })
      .setOrigin(0.5, 1).setDepth(FX_DEPTH);
    this.objects.push(t);
    return t;
  }

  /** ◎ 신호 감지 on rooms (replaces the previous set). */
  setMarkers(rooms: string[]): void {
    for (const [r, t] of this.markers) if (!rooms.includes(r)) { t.destroy(); this.markers.delete(r); }
    for (const r of rooms) {
      if (this.markers.has(r)) continue;
      const c = this.roomCenter(r);
      if (!c) continue;
      const t = this.text(c.x, c.y - CELL, "◎", 20);
      this.scene.tweens.add({ targets: t, alpha: { from: 1, to: 0.35 }, duration: 700, yoyo: true, repeat: -1 });
      this.markers.set(r, t);
    }
  }

  /** ⛔ on locked doors (replaces the previous set). */
  setLocks(edges: string[]): void {
    for (const [e, t] of this.locks) if (!edges.includes(e)) { t.destroy(); this.locks.delete(e); }
    for (const e of edges) {
      if (this.locks.has(e)) continue;
      const p = this.doorAt(e);
      if (!p) continue;
      this.locks.set(e, this.text(p.x, p.y, "⛔", 14, "#ff6b6b"));
    }
  }

  /** ☕ steam filling rooms (replaces the previous set). */
  setSteam(rooms: string[]): void {
    for (const [r, objs] of this.steam) if (!rooms.includes(r)) { objs.forEach((o) => o.destroy()); this.steam.delete(r); }
    for (const r of rooms) {
      if (this.steam.has(r)) continue;
      const b = this.layout.rooms.get(r);
      if (!b) continue;
      const rect = this.scene.add.rectangle(b.x0 * CELL, b.y0 * CELL, ROOM_W * CELL, ROOM_H * CELL, 0xffffff, 0.35).setOrigin(0).setDepth(FX_DEPTH - 1);
      this.scene.tweens.add({ targets: rect, alpha: { from: 0.25, to: 0.5 }, duration: 900, yoyo: true, repeat: -1 });
      const c = this.roomCenter(r)!;
      const t = this.text(c.x, c.y + CELL, "☕", 16, "#ffffff");
      this.objects.push(rect);
      this.steam.set(r, [rect, t]);
    }
  }

  /** 광학 재부팅: the view goes dark and flickers for `ms`. */
  blackout(ms = 1800): Promise<void> {
    return new Promise((resolve) => {
      this.dark.setAlpha(0.92);
      this.scene.tweens.add({
        targets: this.dark, alpha: { from: 0.92, to: 0.6 }, duration: 90, yoyo: true, repeat: Math.floor(ms / 180),
        onComplete: () => { this.dark.setAlpha(0); resolve(); },
      });
    });
  }

  /** A short speech bubble above a world point. */
  bubble(x: number, y: number, s: string, ms = 1600): void {
    const t = this.scene.add.text(x, y - 36, s, { fontFamily: '"Label", sans-serif', fontSize: "9px", color: "#111", backgroundColor: "#f7f7fb", padding: { x: 4, y: 2 }, resolution: 3 })
      .setOrigin(0.5, 1).setDepth(BUBBLE_DEPTH);
    this.scene.tweens.add({ targets: t, y: y - 44, alpha: { from: 1, to: 0 }, delay: ms - 400, duration: 400, onComplete: () => t.destroy() });
  }

  /** A floating line in a room (e.g. the decoy's "soft noise"). */
  roomBubble(room: string, s: string, ms = 1600): void {
    const c = this.roomCenter(room);
    if (c) this.bubble(c.x, c.y, s, ms);
  }

  /** Outline rooms (selectable targets) and doors; `[]` clears. */
  highlightRooms(rooms: string[], color = 0x4f8cff, doors: { x: number; y: number }[] = [], selected: string | null = null): void {
    const g = this.highlight;
    g.clear();
    for (const r of rooms) {
      const b = this.layout.rooms.get(r);
      if (!b) continue;
      g.lineStyle(2, r === selected ? 0xffd54a : color, r === selected ? 1 : 0.8);
      g.strokeRect(b.x0 * CELL + 1, b.y0 * CELL + 1, ROOM_W * CELL - 2, ROOM_H * CELL - 2);
      if (r !== selected) { g.fillStyle(color, 0.12); g.fillRect(b.x0 * CELL, b.y0 * CELL, ROOM_W * CELL, ROOM_H * CELL); }
    }
    for (const d of doors) {
      g.lineStyle(2, 0xff6b6b, 0.9);
      g.strokeCircle(d.x, d.y - CELL / 2, CELL * 0.8);
    }
  }

  destroy(): void {
    this.scene.scale.off(Phaser.Scale.Events.RESIZE, this.resizeDark, this);
    for (const o of this.objects) o.destroy();
    this.highlight.destroy();
    this.dark.destroy();
    this.markers.clear(); this.locks.clear(); this.steam.clear();
  }
}
