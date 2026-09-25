import type { AvatarLook, Catalog } from "./catalog";

export interface Contribution { id: string; earned: number }

/** Mutable app-wide state. Change through the owning module, read anywhere. */
export const state = {
  catalog: null as Catalog | null,
  id: null as string | null,
  token: null as string | null,
  balance: 0,
  contributions: [] as Contribution[],
  avatar: { skin: 0, hair: 0, hair_color: 0, outfit: 0, acc: 0 } as AvatarLook,
  online: 0,
  roomVersion: -1,
};

export function catalog(): Catalog {
  if (!state.catalog) throw new Error("catalog not loaded");
  return state.catalog;
}
