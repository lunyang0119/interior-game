/** Round playback: pre-effects → hunters walk (door bumps) → results → glimpses/markers → capture. Built only from
 *  the report the server sent to this client, so a hunter client never animates anything about the fugitive
 *  except glimpses and the capture room. */

import Phaser from "phaser";
import type { Report } from "../api";
import { HACK_NOTICE_MS, hackNotice, resultBubble } from "../report";
import type { Fx } from "./Fx";
import type { Hunters } from "./Hunters";
import type { Layout } from "./layout";

type Fugitive = import("./Fugitive").FugitiveSprite;

export interface PlaybackCtx {
  scene: Phaser.Scene;
  layout: Layout;
  hunters: Hunters;
  fugitive: Fugitive;
  fx: Fx;
  /** this client is the fugitive: also walk the silhouette along fugitive_path */
  fugitiveView: boolean;
  toast: (s: string, ms?: number) => void;
  /** 건너뛰기 pressed: skip the waits and walks, just land everything where the round ends */
  skipped: () => boolean;
  /** where the fugitive was caught as the server told everyone (ws captured.room / view.capture_room) */
  captureRoom?: () => string | null;
}

/** how long a result bubble stays over a hunter */
const BUBBLE_MS = 4000;

function wait(scene: Phaser.Scene, ms: number, ctx?: PlaybackCtx): Promise<void> {
  if (ctx?.skipped()) return Promise.resolve();
  return new Promise((resolve) => scene.time.delayedCall(ms, () => resolve()));
}

export async function playRound(ctx: PlaybackCtx, rep: Report): Promise<void> {
  const { scene, layout, hunters, fugitive, fx } = ctx;
  const pb = rep.playback.hunters;
  const fromRooms: Record<string, string> = {};
  for (const h of pb) fromRooms[h.id] = h.from;
  hunters.placeAll(fromRooms);
  fx.setMarkers([]);

  // 1. the fugitive's pre-effects (what the hunters can perceive of them)
  fx.setLocks(rep.locks);
  fx.setSteam(rep.steam);
  // quickhack notice: hunters learn what is public (locked doors, steam, blackout, the device signature) and where;
  // the fugitive sees whether their own hack fired. Stays up long enough to read while the crew walks.
  const notice = hackNotice(rep, ctx.fugitiveView);
  if (notice) ctx.toast(notice, HACK_NOTICE_MS);
  if (rep.blackout && !ctx.skipped()) await fx.blackout();
  else await wait(scene, 300, ctx);

  const path = rep.playback.fugitive_path;
  const fugitiveWalk = ctx.fugitiveView && path && path.length && !ctx.skipped() ? fugitive.walkRooms(path) : Promise.resolve();

  // 2. hunters move (all at once; a locked door = walk up, bump, come back)
  await Promise.all(pb.map(async (h) => {
    if (h.action !== "move") return;
    if (ctx.skipped()) { hunters.placeAll({ [h.id]: h.blocked_edge ? h.from : h.to }); return; }
    if (h.blocked_edge) {
      const door = layout.doorByEdge.get(h.blocked_edge);
      if (door) await hunters.bump(h.id, h.from, door);
      const p = hunters.position(h.id);
      if (p) fx.bubble(p.x, p.y, "잠겨 있다", BUBBLE_MS);
      return;
    }
    await hunters.walk(h.id, h.to);
  }));
  await fugitiveWalk;
  if (ctx.skipped()) {   // a skip pressed mid-walk: land everyone where the round ends
    const to: Record<string, string> = {};
    for (const h of pb) to[h.id] = h.blocked_edge ? h.from : h.to;
    hunters.placeAll(to);
    if (ctx.fugitiveView && path?.length) await fugitive.show(path[path.length - 1]);
  }
  await wait(scene, 250, ctx);

  // 3. results
  const scanDevice = new Map<string, string>();
  for (const ev of rep.events) if (ev.type === "scan" && ev.device) scanDevice.set(ev.uid, ev.device);
  for (const h of pb) {
    const text = resultBubble(h.result, h.action, scanDevice.get(h.id));
    const p = hunters.position(h.id);
    if (text && p) fx.bubble(p.x, p.y, text, BUBBLE_MS);
  }

  // 4. what the tracker shows after the round
  const glimpses = [...new Set(rep.events.filter((e) => e.type === "glimpse").map((e) => e.room!))];
  for (const r of glimpses) if (!ctx.skipped()) await fugitive.glimpse(r);
  if (!rep.blackout) fx.setMarkers(rep.markers);
  for (const ev of rep.events) if (ev.type === "contact_miss" && ev.room) fx.roomBubble(ev.room, "접촉!");
  if (rep.frozen) ctx.toast("{alert} 침입자 신호가 한 지점에 고정되었다");
  else if (rep.traced) ctx.toast("{alert} 추적률 100% — 실시간 추적 중");

  // 5. capture: the silhouette appears where it was caught, the tint lifts, then everything freezes
  if (rep.captured_by) {
    // a door-encounter (swap) capture happens between two rooms: the capturer's room is not where the fugitive
    // stands, so hunters use the room the server announced
    const room = ctx.captureRoom?.() ?? rep.hunters[rep.captured_by]?.room;
    const capRoom = ctx.fugitiveView && path?.length ? path[path.length - 1] : room;
    if (capRoom) {
      await fugitive.show(capRoom);
      await wait(scene, 600, ctx);
      await fugitive.reveal();
      const p = hunters.position(rep.captured_by);
      if (p) fx.bubble(p.x, p.y, "체포!", 3000);
      await wait(scene, 1200, ctx);
    }
  }
  await wait(scene, 400, ctx);
}
