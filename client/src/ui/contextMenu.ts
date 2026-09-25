import { bus } from "../bus";
import type { RoomItem } from "../catalog";
import { catalog } from "../state";
import { $, show } from "./hud";

let current: RoomItem | null = null;

export function initContextMenu(): void {
  const ctx = $("ctx");
  bus.on("item:menu", ({ item, screenX, screenY }) => {
    current = item;
    const it = catalog().byId.get(item.item_id);
    $("ctx-title").textContent = `${it?.name ?? item.item_id} · ${item.placed_by}가 놓음`;
    show("ctx", true);
    const w = ctx.offsetWidth, h = ctx.offsetHeight;
    ctx.style.left = `${Math.min(screenX, innerWidth - w - 8)}px`;
    ctx.style.top = `${Math.min(screenY, innerHeight - h - 8)}px`;
  });
  $("ctx-move").addEventListener("click", () => { if (current) bus.emit("place:move", { uid: current.uid }); close(); });
  $("ctx-remove").addEventListener("click", () => {
    if (!current) return;
    const it = catalog().byId.get(current.item_id);
    if (confirm(`${it?.name ?? current.item_id} 치울까요? ${it?.price ?? 0}💰 환불되어요.`)) bus.emit("item:remove", { uid: current.uid });
    close();
  });
  $("ctx-cancel").addEventListener("click", close);
  document.addEventListener("pointerdown", (e) => { if (!ctx.contains(e.target as Node)) close(); }, { capture: true });
}

function close(): void {
  current = null;
  show("ctx", false);
}
