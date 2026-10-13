/** Typed event bus of the train page (own instance; the room game's bus.ts is untouched). */

export interface TrainEvents {
  "scene:ready": { rooms: number };
  "room:tap": { room: string | null };
  "preview:grid": { on: boolean };
}

type Handler<K extends keyof TrainEvents> = (payload: TrainEvents[K]) => void;

class Bus {
  private handlers = new Map<string, Set<(p: unknown) => void>>();

  on<K extends keyof TrainEvents>(type: K, fn: Handler<K>): () => void {
    let set = this.handlers.get(type);
    if (!set) this.handlers.set(type, (set = new Set()));
    set.add(fn as (p: unknown) => void);
    return () => set!.delete(fn as (p: unknown) => void);
  }

  emit<K extends keyof TrainEvents>(type: K, payload: TrainEvents[K]): void {
    this.handlers.get(type)?.forEach((fn) => fn(payload));
  }
}

export const tbus = new Bus();
