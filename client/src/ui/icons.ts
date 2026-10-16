import { el } from "./dom";

/** Pixel icons in place of emoji (docs/conventions/icons.md). The sprite and the `.icon-<name>` classes come from
 *  data/ui_icons.json via `preprocess.py ui` (media/theme.css). */

/** `<i class="icon icon-coin">`; drawn at the theme scale; `big` doubles it for big buttons. */
export function icon(name: string, big = false): HTMLElement {
  const i = document.createElement("i");
  i.className = `icon icon-${name}${big ? " x2" : ""}`;
  i.setAttribute("aria-hidden", "true");
  return i;
}

const TOKEN = /\{([a-z_]+)\}/g;

/** Text with `{name}` tokens turned into icons; everything else stays a text node (never parsed as HTML). */
export function rich(text: string): DocumentFragment {
  const out = document.createDocumentFragment();
  let at = 0;
  for (const m of text.matchAll(TOKEN)) {
    if (m.index! > at) out.append(text.slice(at, m.index));
    out.append(icon(m[1]));
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.append(text.slice(at));
  return out;
}

/** `el.textContent = text`, but with `{name}` tokens as icons. */
export function setRich(target: HTMLElement, text: string): void {
  target.replaceChildren(rich(text));
}

/** `el(tag, cls, text)` (ui/dom.ts) with `{name}` tokens as icons. */
export function richEl<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text: string): HTMLElementTagNameMap[K] {
  const e = el(tag, cls);
  e.append(rich(text));
  return e;
}
