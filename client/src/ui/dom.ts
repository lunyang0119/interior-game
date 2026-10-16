/** Tiny DOM helpers shared by the room game's UI (`ui/*.ts`) and the train page (`train/ui/*.ts`). */

export function $<T extends HTMLElement = HTMLElement>(id: string): T {
  const e = document.getElementById(id);
  if (!e) throw new Error(`#${id} missing`);
  return e as T;
}

export function show(id: string, on = true): void {
  $(id).classList.toggle("hidden", !on);
}

/** `el("div", "row", "text")`; text goes in as textContent, never HTML. */
export function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
