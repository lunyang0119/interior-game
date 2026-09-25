import { bus, toast } from "../bus";
import type { Item, Layer } from "../catalog";
import { catalog, state } from "../state";
import { $, togglePanel } from "./hud";

const TABS: { key: Layer | "all"; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "furniture", label: "가구" },
  { key: "surface_item", label: "소품" },
  { key: "floor", label: "러그" },
  { key: "wall", label: "벽" },
];

let tab: Layer | "all" = "all";
let atlasImg: HTMLImageElement | null = null;
let atlasFrames: Record<string, { frame: { x: number; y: number; w: number; h: number } }> = {};

async function loadAtlas(): Promise<void> {
  if (atlasImg) return;
  const [json, img] = await Promise.all([
    fetch("/gen/interiors.json").then((r) => r.json()),
    new Promise<HTMLImageElement>((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = "/gen/interiors.png"; }),
  ]);
  atlasFrames = json.frames;
  atlasImg = img;
}

function thumb(item: Item): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 64;
  c.height = 64;
  const f = atlasFrames[item.sprite]?.frame;
  if (f && atlasImg) {
    const ctx = c.getContext("2d")!;
    ctx.imageSmoothingEnabled = false;
    const s = Math.min(60 / f.w, 60 / f.h, 3);
    const w = f.w * s, h = f.h * s;
    ctx.drawImage(atlasImg, f.x, f.y, f.w, f.h, (64 - w) / 2, (64 - h) / 2, w, h);
  }
  return c;
}

function render(): void {
  const grid = $("shop-grid");
  grid.innerHTML = "";
  const items = catalog().items.filter((i) => tab === "all" || i.layer === tab);
  for (const item of items) {
    const el = document.createElement("div");
    el.className = "shop-item" + (item.price > state.balance ? " disabled" : "");
    el.appendChild(thumb(item));
    el.insertAdjacentHTML("beforeend", `<div class="n">${item.name}</div><div class="p">${item.price}💰 · ${item.w}×${item.h}</div>`);
    el.addEventListener("click", () => {
      if (item.price > state.balance) { toast("돈이 부족해"); return; }
      bus.emit("place:begin", { itemId: item.id });
    });
    grid.appendChild(el);
  }
  const tabs = $("shop-tabs");
  tabs.innerHTML = "";
  for (const t of TABS) {
    const b = document.createElement("button");
    b.textContent = t.label;
    b.className = t.key === tab ? "on" : "";
    b.addEventListener("click", () => { tab = t.key; render(); });
    tabs.appendChild(b);
  }
}

export function initShop(): void {
  $("btn-shop").addEventListener("click", async () => {
    if (!state.id) { toast("먼저 계정을 골라"); return; }
    await loadAtlas();
    render();
    togglePanel("panel-shop");
  });
  bus.on("money", () => { if (!$("panel-shop").classList.contains("hidden")) render(); });
}
