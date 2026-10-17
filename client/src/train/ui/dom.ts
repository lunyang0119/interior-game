/** The train page's DOM helpers: the shared `$` / `el` / `show` (ui/dom.ts) plus panels, buttons and folds. */

import { $, el, show } from "../../ui/dom";
import { richEl as roomRichEl, setRich as roomSetRich } from "../../ui/icons";

export { $, el, show };

/** A cyber icon from media/train/icons.png (`preprocess.py train-ui`) sized for a line of text. */
export function ic(name: string): HTMLElement {
  const i = document.createElement("i");
  i.className = `ic ic-${name} ic-in`;
  i.setAttribute("aria-hidden", "true");
  return i;
}

/** `target.textContent = text` with `{name}` tokens as cyber icons (ui/icons.ts rich text, train flavour). */
export function setRich(target: HTMLElement, text: string): void {
  roomSetRich(target, text, ic);
}

/** `el(tag, cls, text)` with `{name}` tokens as cyber icons. */
export function richEl<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text: string): HTMLElementTagNameMap[K] {
  return roomRichEl(tag, cls, text, ic);
}

export function button(label: string, onClick: () => void, cls = ""): HTMLButtonElement {
  const b = el("button", cls, label);
  b.onclick = onClick;
  return b;
}

/** Open one panel (closing the other `.panel`s). */
export function openPanel(id: string): void {
  for (const p of document.querySelectorAll<HTMLElement>(".panel")) p.classList.toggle("hidden", p.id !== id);
}

export function closePanels(): void {
  for (const p of document.querySelectorAll<HTMLElement>(".panel")) p.classList.add("hidden");
}

/** Fold/unfold the bottom bars (▾ buttons with data-fold); the choice is remembered per bar. */
export function initFolds(): void {
  for (const b of document.querySelectorAll<HTMLButtonElement>("button.fold[data-fold]")) {
    const id = b.dataset.fold!;
    const key = `train_fold:${id}`;
    const apply = (folded: boolean) => {
      $(id).classList.toggle("folded", folded);
      b.innerHTML = `<i class="ic ic-${folded ? "tri_up" : "tri_down"}"></i><span>${folded ? "펴기" : "접기"}</span>`;
      try { localStorage.setItem(key, folded ? "1" : "0"); } catch { /* ignore */ }
    };
    let folded = false;
    try { folded = localStorage.getItem(key) === "1"; } catch { /* ignore */ }
    apply(folded);
    b.onclick = () => apply(!$(id).classList.contains("folded"));
  }
}
