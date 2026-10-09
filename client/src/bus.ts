/** Tiny typed event bus between the Phaser scene and the DOM UI. */

import type { Deliverable } from "./api";
import type { AvatarLook, RoomItem } from "./catalog";

export interface Events {
  "money": { balance: number };
  "online": { count: number };
  "toast": { text: string; ms?: number };
  "account:switch": { id: string };
  "avatar:saved": AvatarLook;
  "place:begin": { itemId: string };
  "place:move": { uid: number };
  "place:confirm": void;
  "place:confirm-again": void;
  "place:cancel": void;
  "place:span": { delta: number };
  "place:state": { active: boolean; label: string; ok: boolean; mode: "place" | "move" | null; busy?: boolean; span?: number | null; spanMax?: number };
  "room:refresh": void;
  "room:changed": { id: string; name: string; ruined: number }; // the Room scene shows another room / junk count moved
  "room:exit": { from: string; to: string; spawn: { x: number; y: number } }; // avatar stepped on an exit
  "scene:changed": { scene: "room" | "map" | "dock" };
  "scene:ready": void; // the new scene has its data and is drawn → hide the loading overlay
  "net:state": { online: boolean; reason?: "replaced" | "rotated" }; // WebSocket up/down for the HUD chip
  "map:enter-ask": { name: string }; // standing on a door: show "<name>에 들어가시겠어요?" (empty name closes it)
  "map:enter-answer": { yes: boolean };
  "map:enter": { room: string }; // answered yes
  "dock:enter": void;
  "dock:exit": void;
  "dock:ready": void;
  "fish:press": void; // the one fishing button: cast when idle, start a hold when a bite is up
  "fish:release": void;
  "fish:state": { status: string; mode: "idle" | "wait" | "bite" | "hold" };
  "fish:meter": { meter: number }; // 0..1 of the current bite's hold
  // seq + deliverable only for my own catch: the overlay then offers "납품하기" (ui/hud.ts)
  "fish:catch": { ok: boolean; id: string; name: string; value: number; who: string; seq?: number | null; deliverable?: Deliverable[] };
  "item:menu": { item: RoomItem; screenX: number; screenY: number };
  "item:remove": { uid: number };
  "item:walk": { uid: number }; // context menu "여기로 가기": walk the avatar up to that item
  "item:note": { item: RoomItem }; // context menu "쪽지 읽기/쓰기": open the note panel
  "progress:changed": { completed: { room: string; from: number; to: number }[] }; // state.progress / state.locked replaced
  "comfort:changed": void; // state.comfort replaced
  "log:open": { section?: "progress" | "guests" }; // open the 📜 panel (optionally scrolled to the restoration checklist)
}

type Handler<K extends keyof Events> = (payload: Events[K]) => void;

const handlers = new Map<keyof Events, Set<Handler<any>>>();

export const bus = {
  on<K extends keyof Events>(type: K, fn: Handler<K>): () => void {
    let set = handlers.get(type);
    if (!set) handlers.set(type, (set = new Set()));
    set.add(fn);
    return () => set!.delete(fn);
  },
  emit<K extends keyof Events>(type: K, ...args: Events[K] extends void ? [] : [Events[K]]): void {
    handlers.get(type)?.forEach((fn) => fn(args[0]));
  },
};

/** Default duration grows with the text so long notices (token expired, registration) can actually be read. */
export function toast(text: string, ms?: number): void {
  bus.emit("toast", { text, ms: ms ?? Math.min(6000, 1500 + text.length * 60) });
}
