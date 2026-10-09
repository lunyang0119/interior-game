/** 쪽지 panel: items tagged `note` carry a short text that anyone can read and rewrite.
 *
 * Opened from the context menu ("쪽지 읽기/쓰기"). The text box is a plain card for now; a paper texture goes
 * behind `.note-paper` later (style.css). Saving bumps the room version on the server, so every client refreshes.
 */

import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { SEED_PLAYER, type RoomItem } from "../catalog";
import { catalog } from "../state";
import { $, show } from "./hud";

export const NOTE_MAX = 200;

let current: RoomItem | null = null;

function fmtWhen(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function render(item: RoomItem): void {
  const it = catalog().byId.get(item.item_id);
  $("note-title").textContent = it?.name ?? "쪽지";
  const edit = $("note-edit") as HTMLTextAreaElement;
  edit.value = item.note ?? "";
  edit.maxLength = NOTE_MAX;
  const by = item.note_by && item.note_by !== SEED_PLAYER ? item.note_by : null;
  $("note-by").textContent = item.note
    ? `— ${by ?? "???"}${item.note_ts ? ` · ${fmtWhen(item.note_ts)}` : ""}`
    : "아직 아무것도 안 적혀 있어요";
  updateCount();
}

function updateCount(): void {
  const edit = $("note-edit") as HTMLTextAreaElement;
  $("note-count").textContent = `${edit.value.length}/${NOTE_MAX}`;
}

export function initNote(): void {
  bus.on("item:note", ({ item }) => {
    current = item;
    render(item);
    show("panel-note", true);
    if (window.matchMedia("(pointer: fine)").matches) ($("note-edit") as HTMLTextAreaElement).focus();
  });
  $("note-edit").addEventListener("input", updateCount);
  const save = $("note-save") as HTMLButtonElement;
  save.addEventListener("click", async () => {
    if (!current || save.disabled) return;
    const text = ($("note-edit") as HTMLTextAreaElement).value.trim();
    save.disabled = true;
    try {
      const r = await api.note(current.uid, text);
      current = { ...current, note: r.note, note_by: r.note_by, note_ts: r.note_ts };
      render(current);
      toast(text ? "쪽지를 남겼어요" : "쪽지를 지웠어요");
      show("panel-note", false);
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    } finally {
      save.disabled = false;
    }
  });
  // leaving the room: drop a stale editor
  bus.on("scene:changed", () => { current = null; show("panel-note", false); });
}
