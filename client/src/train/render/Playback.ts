/** Round playback: pre-effects → hunters walk (door bumps) → results → glimpses/markers → capture. Built only from
 *  the report the server sent to this client, so a hunter client never animates anything about the fugitive
 *  except glimpses and the capture room. */

import Phaser from "phaser";
import type { Report } from "../api";
import { resultBubble } from "../report";
import { DEVICE_KO } from "../strings";
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
  toast: (s: string) => void;
}

function wait(scene: Phaser.Scene, ms: number): Promise<void> {
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
  if (rep.signature && rep.signature !== "ping") ctx.toast(`⚠ ${DEVICE_KO[rep.signature] ?? rep.signature} 계열 장치에서 비정상 접근 감지`);
  if (rep.blackout) await fx.blackout();
  else await wait(scene, 300);

  const path = rep.playback.fugitive_path;
  const fugitiveWalk = ctx.fugitiveView && path && path.length ? fugitive.walkRooms(path) : Promise.resolve();

  // 2. hunters move (all at once; a locked door = walk up, bump, come back)
  await Promise.all(pb.map(async (h) => {
    if (h.action !== "move") return;
    if (h.blocked_edge) {
      const door = layout.doorByEdge.get(h.blocked_edge);
      if (door) await hunters.bump(h.id, h.from, door);
      const p = hunters.position(h.id);
      if (p) fx.bubble(p.x, p.y, "🚪 잠겨 있다");
      return;
    }
    await hunters.walk(h.id, h.to);
  }));
  await fugitiveWalk;
  await wait(scene, 250);

  // 3. results
  const scanDevice = new Map<string, string>();
  for (const ev of rep.events) if (ev.type === "scan" && ev.device) scanDevice.set(ev.uid, ev.device);
  for (const h of pb) {
    const text = resultBubble(h.result, h.action, scanDevice.get(h.id));
    const p = hunters.position(h.id);
    if (text && p) fx.bubble(p.x, p.y, text, 2200);
  }

  // 4. what the tracker shows after the round
  const glimpses = [...new Set(rep.events.filter((e) => e.type === "glimpse").map((e) => e.room!))];
  for (const r of glimpses) await fugitive.glimpse(r);
  if (!rep.blackout) fx.setMarkers(rep.markers);
  for (const ev of rep.events) if (ev.type === "contact_miss" && ev.room) fx.roomBubble(ev.room, "💥 접촉!");
  if (rep.frozen) ctx.toast("‼ 침입자 신호가 한 지점에 고정되었다");
  else if (rep.traced) ctx.toast("‼ 추적률 100% — 실시간 추적 중");

  // 5. capture: the silhouette appears where it was caught, the tint lifts, then everything freezes
  if (rep.captured_by) {
    const room = rep.hunters[rep.captured_by]?.room;
    const capRoom = ctx.fugitiveView && path?.length ? path[path.length - 1] : room;
    if (capRoom) {
      await fugitive.show(capRoom);
      await wait(scene, 600);
      await fugitive.reveal();
      const p = hunters.position(rep.captured_by);
      if (p) fx.bubble(p.x, p.y, "체포!", 3000);
      await wait(scene, 1200);
    }
  }
  await wait(scene, 400);
}
