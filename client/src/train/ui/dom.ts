/** Tiny DOM helpers shared by the train page's UI modules. */

export const $ = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T;

export function show(id: string, on = true): void {
  $(id).classList.toggle("hidden", !on);
}

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text = ""): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
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
      b.textContent = folded ? "▴" : "▾";
      try { localStorage.setItem(key, folded ? "1" : "0"); } catch { /* ignore */ }
    };
    let folded = false;
    try { folded = localStorage.getItem(key) === "1"; } catch { /* ignore */ }
    apply(folded);
    b.onclick = () => apply(!$(id).classList.contains("folded"));
  }
}
