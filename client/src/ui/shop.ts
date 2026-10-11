import { bus, toast } from "../bus";
import { forSale, priceOf, type Item, type Layer } from "../catalog";
import { catalog, state } from "../state";
import { $, closeAllPanels, show, togglePanel } from "./hud";
import { assetUrl } from "../assets";

const TABS: { key: Layer | "all"; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "furniture", label: "가구" },
  { key: "surface_item", label: "소품" },
  { key: "floor", label: "바닥·러그" },
  { key: "wallpaper", label: "벽지" },
  { key: "wall", label: "벽 장식" },
];

let tab: Layer | "all" = "all";
/** Normalized search text (see `norm`); "" = no filter. */
let query = "";
let atlasImg: HTMLImageElement | null = null;
let atlasFrames: Record<string, { frame: { x: number; y: number; w: number; h: number } }> = {};
/** Built once per item; afterwards only class/visibility toggles (no canvas redraws on balance changes).
 *  `key` is the normalized name + id the search box matches against. */
const cards = new Map<string, { item: Item; el: HTMLElement; key: string }>();
const tabButtons = new Map<string, HTMLButtonElement>();

/** Case- and whitespace-insensitive comparison key (Korean is kept as is). */
function norm(s: string): string {
  return s.toLowerCase().replace(/\s+/g, "");
}

function searchBox(): HTMLInputElement {
  return $("shop-search") as HTMLInputElement;
}

function clearSearch(): void {
  query = "";
  searchBox().value = "";
}

async function loadAtlas(): Promise<void> {
  if (atlasImg) return;
  const [json, img] = await Promise.all([
    fetch(assetUrl("/gen/interiors.json")).then((r) => r.json()),
    new Promise<HTMLImageElement>((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = assetUrl("/gen/interiors.png"); }),
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

function build(): void {
  if (cards.size) return;
  const grid = $("shop-grid");
  grid.innerHTML = "";
  for (const item of catalog().items) {
    if (!forSale(item)) continue; // junk and room fixtures are not in the shop
    const el = document.createElement("div");
    el.className = "shop-item";
    el.appendChild(thumb(item));
    const size = item.layer === "wallpaper" ? `${item.price}💰/칸 · 폭 조절` : `${item.price}💰 · ${item.w}×${item.h}`;
    el.insertAdjacentHTML("beforeend", `<div class="n">${item.name}</div><div class="p">${size}</div>`);
    el.addEventListener("click", () => {
      if (priceOf(item, 1) > state.balance) { toast("돈이 부족해요"); return; }
      bus.emit("place:begin", { itemId: item.id });
    });
    grid.appendChild(el);
    cards.set(item.id, { item, el, key: norm(`${item.name} ${item.id}`) });
  }
  const tabs = $("shop-tabs");
  tabs.innerHTML = "";
  for (const t of TABS) {
    const b = document.createElement("button");
    b.textContent = t.label;
    b.addEventListener("click", () => { tab = t.key; applyFilter(); });
    tabs.appendChild(b);
    tabButtons.set(t.key, b);
  }
  const box = searchBox();
  // `input` also fires mid-IME-composition with the partial syllable, so Korean filters live
  box.addEventListener("input", () => { query = norm(box.value); applyFilter(); });
  box.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Escape") { e.preventDefault(); clearSearch(); applyFilter(); box.blur(); }
    else if (e.key === "Enter") box.blur();
  });
}

/** Shows the cards matching both the layer tab and the search text; toggles the "no results" note. */
function applyFilter(): void {
  for (const [key, b] of tabButtons) b.classList.toggle("on", key === tab);
  let shown = 0;
  for (const { item, el, key } of cards.values()) {
    const hide = (tab !== "all" && item.layer !== tab) || (query !== "" && !key.includes(query));
    el.classList.toggle("hidden", hide);
    if (!hide) shown++;
  }
  $("shop-empty").classList.toggle("hidden", shown > 0);
}

function applyBalance(): void {
  for (const { item, el } of cards.values()) el.classList.toggle("disabled", priceOf(item, 1) > state.balance);
}

/** A 64×64 thumbnail of an item drawn from the atlas (the board uses it for reservation cards). */
export async function itemThumb(item: Item): Promise<HTMLCanvasElement> {
  await loadAtlas();
  return thumb(item);
}

/** Opens the shop; with `itemId` (a reservation's request) it switches to 전체, scrolls to that card and flashes it. */
export function openShop(itemId?: string): void {
  if (!state.id) { toast("먼저 계정을 골라주세요"); return; }
  void loadAtlas().then(() => {
    build();
    if (itemId) {
      const card = cards.get(itemId);
      if (!card) { toast("상점에 없는 물건이에요"); return; }
      tab = "all";
      clearSearch();
      applyFilter();
      applyBalance();
      closeAllPanels();
      show("panel-shop", true);
      card.el.scrollIntoView({ block: "center" });
      card.el.classList.add("hl");
      window.setTimeout(() => card.el.classList.remove("hl"), 2500);
      return;
    }
    applyFilter();
    applyBalance();
    togglePanel("panel-shop");
    // desktop only: phones would pop the keyboard over the panel
    if (!$("panel-shop").classList.contains("hidden") && window.matchMedia("(pointer: fine)").matches) searchBox().focus();
  });
}

export function initShop(): void {
  $("btn-shop").addEventListener("click", () => openShop());
  bus.on("shop:open", ({ itemId }) => openShop(itemId));
  bus.on("money", () => { if (cards.size) applyBalance(); });
}
