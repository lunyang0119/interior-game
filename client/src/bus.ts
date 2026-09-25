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
  "place:cancel": void;
  "place:state": { active: boolean; label: string; ok: boolean };
  "room:refresh": void;
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

export function toast(text: string, ms = 2200): void {
  bus.emit("toast", { text, ms });
}
