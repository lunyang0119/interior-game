import { bus } from "../bus";
import { GUEST_PLAYER, hasTag, priceOf, SEED_PLAYER, TAG_NOTE, TAG_RUINED, type RoomItem } from "../catalog";
import { catalog } from "../state";
import { $, show } from "./dom";
import { setRich } from "./icons";

let current: RoomItem | null = null;

export function initContextMenu(): void {
  const ctx = $("ctx");
  bus.on("item:menu", ({ item, screenX, screenY }) => {
    current = item;
    const it = catalog().byId.get(item.item_id);
    const ruined = hasTag(it, TAG_RUINED);
    const guest = item.placed_by === GUEST_PLAYER;
    const who = item.placed_by === SEED_PLAYER ? "처음부터 있던 물건" : guest ? "손님이 두고 갔어요" : `${item.placed_by}가 놓음`;
    $("ctx-title").textContent = `${it?.name ?? item.item_id} · ${who}`;
    setRich($("ctx-remove"), ruined ? `팔기 (+${it ? priceOf(it, item.span, item.span_h) : 0}{coin})` : guest ? "치우기" : "팔기 (전액 환불)");
    const note = hasTag(it, TAG_NOTE);
    show("ctx-note", note);
    setRich($("ctx-note"), note && item.note ? "{letter} 쪽지 읽기" : "{letter} 쪽지 쓰기");
    show("ctx", true);
    const w = ctx.offsetWidth, h = ctx.offsetHeight;
    ctx.style.left = `${Math.min(screenX, innerWidth - w - 8)}px`;
    ctx.style.top = `${Math.min(screenY, innerHeight - h - 8)}px`;
  });
  $("ctx-walk").addEventListener("click", () => { if (current) bus.emit("item:walk", { uid: current.uid }); close(); });
  $("ctx-note").addEventListener("click", () => { if (current) bus.emit("item:note", { item: current }); close(); });
  $("ctx-move").addEventListener("click", () => { if (current) bus.emit("place:move", { uid: current.uid }); close(); });
  $("ctx-remove").addEventListener("click", () => {
    if (!current) return;
    const it = catalog().byId.get(current.item_id);
    const price = it ? priceOf(it, current.span, current.span_h) : 0;
    const q = hasTag(it, TAG_RUINED) ? `${it?.name ?? current.item_id} 팔까요? (+${price})` : `${it?.name ?? current.item_id} 치울까요? (${price} 환불)`;
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
