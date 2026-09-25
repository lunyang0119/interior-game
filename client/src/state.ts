import { DEFAULT_LOOK, type AvatarLook, type Catalog } from "./catalog";

export interface Contribution { id: string; earned: number }

/** Mutable app-wide state. Change through the owning module, read anywhere. */
export const state = {
  catalog: null as Catalog | null,
  id: null as string | null,
  token: null as string | null,
  balance: 0,
  contributions: [] as Contribution[],
  avatar: { ...DEFAULT_LOOK } as AvatarLook,
  online: 0,
  roomVersion: -1,
};

export function catalog(): Catalog {
  if (!state.catalog) throw new Error("catalog not loaded");
  return state.catalog;
}
