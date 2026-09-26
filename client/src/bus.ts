/** Tiny typed event bus between the Phaser scene and the DOM UI. */

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
  "dock:enter": void;
  "dock:exit": void;
  "dock:ready": void;
  "dock:fish": void; // placeholder: fishing is not implemented yet
  "item:menu": { item: RoomItem; screenX: number; screenY: number };
  "item:remove": { uid: number };
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
