/** 📋 게시판: the board on the inn wall (items tagged `board`, RoomScene tap → `board:open`).
 *
 * Three things, all read from state the 📜 panel already keeps (`state.progress`, `state.comfort`) and refreshed
 * from /api/activity when the board opens:
 *   - tonight's expected guests / pay across every open unit,
 *   - 📝 open reservations: what the guest wants, where, how long is left, whether the unit already has it
 *     (server `reservation.ready`) and a button that opens the shop scrolled to that item,
 *   - 📌 quests: every room's restoration stages (past ✓, current with need bars, upcoming dimmed) and rewards.
 */

import { api, ApiError, msgFor, type ComfortView, type NeedProgress, type RoomProgress } from "../api";
import { bus, toast } from "../bus";
import { placeName, unitName, type Stage } from "../catalog";
import { applyCat, applyComfort, applyProgress, CAT_MAX_AFFECTION, CAT_TAPS_PER_LEVEL, catalog, state } from "../state";
import { $, show, togglePanel } from "./hud";
import { itemThumb } from "./shop";

const NEED_LABEL: Record<NeedProgress["type"], string> = {
  ruined_zero: "부서진 물건 치우기", placed: "가구 놓기", deliver: "물고기 납품", pool: "공동 자금 모으기",
};
const DOG_COMFORT = 70; // mirrors data/guests.json dog.comfort_fallback (display only)

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function isOpen(): boolean {
  return !$("panel-board").classList.contains("hidden");
}

function itemName(id: string | null): string {
  return (id && catalog().byId.get(id)?.name) || id || "무언가";
}

/** "오늘 밤 손님 3명 · 숙박료 48💰 예상 · 객실 3곳" */
function renderSummary(): void {
  const views = Object.values(state.comfort);
  const box = $("board-summary");
  if (!views.length) { box.textContent = "아직 손님을 받을 수 있는 방이 없어요"; return; }
  const guests = views.reduce((n, v) => n + v.guests, 0);
  const pay = views.reduce((n, v) => n + v.pay, 0);
  const beds = views.reduce((n, v) => n + v.beds, 0);
  const parts = [guests ? `오늘 밤 손님 ${guests}명 · 숙박료 ${pay}💰 예상` : beds ? "오늘 밤은 손님이 없어요" : "침대가 없어서 손님을 못 받아요"];
  parts.push(`객실 ${views.length}곳`);
  parts.push(catLine());
  box.textContent = parts.join(" · ");
}

/** "🐱 호감도 1/3 · 쓰다듬기 137/300" — the cat loves the inn a little more every 100 taps, for good. */
function catLine(): string {
  const c = state.cat;
  const goal = CAT_MAX_AFFECTION * CAT_TAPS_PER_LEVEL;
  return c.affection >= CAT_MAX_AFFECTION
    ? `🐱 호감도 ${c.affection}/${CAT_MAX_AFFECTION} (최고예요)`
    : `🐱 호감도 ${c.affection}/${CAT_MAX_AFFECTION} · 쓰다듬기 ${Math.min(c.taps, goal)}/${goal}`;
}

function reservationCard(key: string, c: ComfortView): HTMLElement {
  const r = c.reservation!;
  const cat = catalog();
  const card = el("div", "rsv");
  const body = el("div", "body");
  const when = r.days_left <= 0 ? "오늘 밤" : `${r.days_left}일 뒤`;
  body.appendChild(el("div", "where", unitName(cat, key)));
  if (r.kind === "dog") {
    card.appendChild(el("div", "emoji", "🐶"));
    body.appendChild(el("div", "what", `개를 좋아하는 손님이 ${when} 와요 — 개 장식이 있거나 안락도 ${DOG_COMFORT} 이상이면 3배를 내요`));
    body.appendChild(el("div", `status ${r.ready ? "ok" : "miss"}`,
      r.ready ? "✓ 준비됐어요" : c.beds === 0 ? "침대가 없어요" : `아직이에요 (안락도 ${c.score}/${DOG_COMFORT})`));
  } else {
    const item = r.item_id ? cat.byId.get(r.item_id) : undefined;
    const slot = el("div", "emoji", "📦");
    card.appendChild(slot);
    if (item) void itemThumb(item).then((canvas) => slot.replaceWith(canvas));
    body.appendChild(el("div", "what", `${when}까지 ${itemName(r.item_id)} 준비 — 있으면 2배, 없으면 다음날 손님이 안 와요`));
    body.appendChild(el("div", `status ${r.ready ? "ok" : "miss"}`,
      r.ready ? "✓ 준비됐어요" : c.beds === 0 ? "침대도 없어요" : "아직 없어요"));
    if (!r.ready && item) {
      const btn = el("button", "", "상점에서 찾기");
      btn.addEventListener("click", () => bus.emit("shop:open", { itemId: item.id }));
      card.appendChild(body);
      card.appendChild(btn);
      return card;
    }
  }
  card.appendChild(body);
  return card;
}

function renderReservations(): void {
  const box = $("board-reserve");
  box.replaceChildren();
  const keys = Object.keys(state.comfort).filter((k) => state.comfort[k].reservation);
  if (!keys.length) { box.appendChild(el("div", "empty", "지금은 예약이 없어요")); return; }
  keys.sort((a, b) => state.comfort[a].reservation!.days_left - state.comfort[b].reservation!.days_left);
  for (const key of keys) box.appendChild(reservationCard(key, state.comfort[key]));
}

function needRow(n: NeedProgress): HTMLElement[] {
  const label = n.label || NEED_LABEL[n.type];
  const row = el("div", `need${n.done ? " done" : ""}`);
  if (n.type === "ruined_zero") {
    row.textContent = n.done ? label : `${label} (${n.have}개 남음)`;
    return [row];
  }
  row.textContent = `${label} ${n.have}/${n.want}`;
  if (n.done) return [row];
  const bar = el("div", "bar");
  const fill = document.createElement("i");
  fill.style.width = `${Math.min(100, Math.round((100 * n.have) / Math.max(1, n.want)))}%`;
  bar.appendChild(fill);
  return [row, bar];
}

function questCard(roomId: string, stages: Stage[], p: RoomProgress | undefined): HTMLElement {
  const cat = catalog();
  const card = el("div", `quest${roomId === state.roomId ? " here" : ""}`);
  const head = el("div", "quest-head");
  const done = p?.stage ?? 0;
  head.append(document.createTextNode(placeName(cat, roomId)),
    el("span", "", p?.done ? "복구 완료" : `${done}/${stages.length}단계`));
  card.appendChild(head);
  stages.forEach((s, i) => {
    if (i < done) { card.appendChild(el("div", "stage past", `✓ ${s.name}`)); return; }
    if (i > done) { card.appendChild(el("div", "stage next", `· ${s.name} (다음)`)); return; }
    const cur = el("div", "stage");
    cur.appendChild(el("span", "stage-name", `▶ ${s.name}`));
    card.appendChild(cur);
    for (const n of p?.current?.needs ?? []) card.append(...needRow(n));
    const unlocks = (p?.current?.unlocks ?? s.reward.map((r) => r.room)).map((u) => placeName(cat, u));
    if (unlocks.length) card.appendChild(el("div", "reward", `완료하면 ${unlocks.join(", ")}이(가) 열려요`));
  });
  return card;
}

function renderQuests(): void {
  const box = $("board-quests");
  box.replaceChildren();
  const cat = catalog();
  const ids = [...cat.rooms.keys()].filter((id) => (cat.rooms.get(id)?.restore?.length ?? 0) > 0);
  if (!ids.length) { box.appendChild(el("div", "empty", "의뢰가 없어요")); return; }
  // the room we stand in first, then rooms still being restored, finished ones last
  const rank = (id: string) => (id === state.roomId ? -1 : state.progress[id]?.done ? 1 : 0);
  ids.sort((a, b) => rank(a) - rank(b));
  for (const id of ids) box.appendChild(questCard(id, cat.rooms.get(id)!.restore!, state.progress[id]));
}

function render(): void {
  renderSummary();
  renderReservations();
  renderQuests();
}

async function load(): Promise<void> {
  try {
    const r = await api.activity();
    applyProgress(r.progress, r.locked);
    applyComfort(r.comfort);
    applyCat(r.cat);
    if (isOpen()) render();
  } catch (e) {
    toast(e instanceof ApiError ? msgFor(e.code) : String(e));
  }
}

function open(): void {
  togglePanel("panel-board");
  if (!isOpen()) return;
  render();
  void load();
}

export function initBoard(): void {
  bus.on("board:open", open);
  bus.on("progress:changed", () => { if (isOpen()) renderQuests(); });
  bus.on("comfort:changed", () => { if (isOpen()) { renderSummary(); renderReservations(); } });
  bus.on("cat:changed", () => { if (isOpen()) renderSummary(); });
  show("panel-board", false);
}
