import { bus } from "../bus";
import { hasTag, priceOf, SEED_PLAYER, TAG_RUINED, type RoomItem } from "../catalog";
import { catalog } from "../state";
import { $, show } from "./hud";

let current: RoomItem | null = null;

export function initContextMenu(): void {
  const ctx = $("ctx");
  bus.on("item:menu", ({ item, screenX, screenY }) => {
    current = item;
    const it = catalog().byId.get(item.item_id);
    const ruined = hasTag(it, TAG_RUINED);
    const who = item.placed_by === SEED_PLAYER ? "처음부터 있던 물건" : `${item.placed_by}가 놓음`;
    $("ctx-title").textContent = `${it?.name ?? item.item_id} · ${who}`;
    $("ctx-remove").textContent = ruined ? `팔기 (+${it ? priceOf(it, item.span) : 0}💰)` : "팔기 (전액 환불)";
    show("ctx", true);
    const w = ctx.offsetWidth, h = ctx.offsetHeight;
    ctx.style.left = `${Math.min(screenX, innerWidth - w - 8)}px`;
    ctx.style.top = `${Math.min(screenY, innerHeight - h - 8)}px`;
  });
  $("ctx-move").addEventListener("click", () => { if (current) bus.emit("place:move", { uid: current.uid }); close(); });
  $("ctx-remove").addEventListener("click", () => {
    if (!current) return;
    const it = catalog().byId.get(current.item_id);
    const price = it ? priceOf(it, current.span) : 0;
    const q = hasTag(it, TAG_RUINED) ? `${it?.name ?? current.item_id} 팔까요? ${price}💰 들어와요.` : `${it?.name ?? current.item_id} 치울까요? ${price}💰 환불되어요.`;
    if (confirm(q)) bus.emit("item:remove", { uid: current.uid });
    close();
  });
  $("ctx-cancel").addEventListener("click", close);
  document.addEventListener("pointerdown", (e) => { if (!ctx.contains(e.target as Node)) close(); }, { capture: true });
}

function close(): void {
  current = null;
  show("ctx", false);
}
