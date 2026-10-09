/** 📜 기록 panel: the last few things that happened, today's totals, and every room's restoration checklist.
 *
 * The server only ever serves the newest five rows (small talk, not a ledger); new rows arrive live over the
 * socket (`event`), stage completions as `progress`. The HUD room chip opens the same panel at the checklist.
 */

import { api, ApiError, msgFor, type ActivityEvent, type ComfortView, type NeedProgress, type RoomProgress, type TodayTotals } from "../api";
import { bus, toast } from "../bus";
import { placeName, SEED_PLAYER } from "../catalog";
import { applyComfort, applyProgress, catalog, state } from "../state";
import { socket } from "../ws";
import { $, show, togglePanel } from "./hud";

const MAX_ROWS = 5;

let rows: ActivityEvent[] = [];
let loot = new Map<string, string>(); // loot id → name, from /api/fish
let today: TodayTotals = { earned: 0, fish: 0, fish_count: 0, furniture: 0, sold: 0, deliver: 0, guests: 0 };
let comfortTimer: number | undefined; // debounce for refreshing the comfort picture after room changes
let loaded = false;

const NEED_LABEL: Record<NeedProgress["type"], string> = {
  ruined_zero: "부서진 물건 치우기", placed: "가구 놓기", deliver: "물고기 납품", pool: "공동 자금 모으기",
};

function who(id: string | null): string {
  return !id || id === SEED_PLAYER ? "???" : id;
}

function itemName(id: string | null): string {
  if (!id) return "무언가";
  return catalog().byId.get(id)?.name ?? id;
}

function fishName(id: string | null): string {
  return (id && loot.get(id)) || id || "물고기";
}

function money(n: number | null): string {
  if (!n) return "";
  return n > 0 ? ` (+${n}💰)` : ` (−${-n}💰)`;
}

function ago(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return "방금";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "어제" : `${d}일 전`;
}

/** One log row as a sentence (해요체). */
export function describe(e: ActivityEvent): string {
  const cat = catalog();
  const room = e.room_id ? placeName(cat, e.room_id) : "";
  switch (e.kind) {
    case "place": return `${who(e.player_id)}가 ${room ? room + "에 " : ""}${itemName(e.item_id)}을(를) 놓았어요${money(e.amount)}`;
    case "remove": return `${who(e.player_id)}가 ${room ? room + "의 " : ""}${itemName(e.item_id)}을(를) 치웠어요${money(e.amount)}`;
    case "sell": return `${who(e.player_id)}가 ${room ? room + "의 " : ""}부서진 ${itemName(e.item_id)}을(를) 팔았어요${money(e.amount)}`;
    case "fish": return `${who(e.player_id)}가 ${fishName(e.item_id)}을(를) 낚았어요${money(e.amount)}`;
    case "deliver": return `${who(e.player_id)}가 ${fishName(e.item_id)}을(를) ${room || "어딘가"}에 납품했어요`;
    case "earn": return `${who(e.player_id)}가 ${e.amount ?? 0}💰를 벌어왔어요`;
    case "guest": {
      if (e.data?.skipped) return `${room}에는 손님이 아무도 안 왔어요`;
      const extra = e.data?.dog ? " 🐶 개를 좋아하는 손님도 묵었어요!" : e.data?.reserved ? " 예약 손님이 두 배를 냈어요!" : "";
      return `${room}에 손님 ${e.data?.guests ?? 0}명이 묵고 ${e.amount ?? 0}💰를 냈어요${extra}`;
    }
    case "reserve":
      return e.data?.dog
        ? `🐶 개를 좋아하는 손님이 ${e.data?.days ?? "?"}일 뒤 ${room}에 묵겠대요 — 개 장식이 있거나 안락도가 높으면 와요`
        : `${room}에 예약이 들어왔어요 — ${e.data?.days ?? "?"}일 안에 ${itemName(e.item_id)}을(를) 놓아 주세요`;
    case "missed": return `${room}의 예약 손님이 ${itemName(e.item_id)}이(가) 없어서 돌아갔어요. 내일은 손님이 안 와요`;
    case "stage": {
      const opened = (e.data?.unlocks ?? []).map((r) => placeName(cat, r));
      return `🎉 ${room} '${e.data?.name ?? e.data?.stage ?? ""}' 완료!${opened.length ? ` ${opened.join(", ")}이(가) 열렸어요` : ""}`;
    }
    default: return `${who(e.player_id)}: ${e.kind}`;
  }
}

function renderRows(): void {
  const list = $("log-list");
  list.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "ev empty";
    empty.textContent = "아직 아무 일도 없었어요";
    list.appendChild(empty);
    return;
  }
  for (const e of rows) {
    const div = document.createElement("div");
    div.className = `ev ${e.kind}`;
    const text = document.createElement("span");
    text.textContent = describe(e);
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = ago(e.ts);
    div.append(text, when);
    list.appendChild(div);
  }
}

function renderSummary(): void {
  const signed = (n: number) => (n < 0 ? `−${-n}` : `+${n}`) + "💰";
  const parts = [`벌이 ${signed(today.earned)}`, `낚시 ${signed(today.fish)} (${today.fish_count}마리)`, `가구 ${signed(today.furniture)}`];
  if (today.sold) parts.push(`판매 ${signed(today.sold)}`);
  if (today.deliver) parts.push(`납품 ${signed(today.deliver)}`);
  if (today.guests) parts.push(`숙박료 ${signed(today.guests)}`);
  $("log-today").textContent = "오늘 · " + parts.join(" · ");
}

function needLine(n: NeedProgress): string {
  const label = n.label || NEED_LABEL[n.type];
  if (n.type === "ruined_zero") return n.done ? `${label} ✓` : `${label} (${n.have}개 남음)`;
  return `${label} ${n.have}/${n.want}${n.done ? " ✓" : ""}`;
}

function div(cls: string, text?: string): HTMLDivElement {
  const d = document.createElement("div");
  d.className = cls;
  if (text !== undefined) d.textContent = text;
  return d;
}

/** Every open room: comfort bar, what makes it up, tonight's guests and the open reservation. */
function renderGuests(): void {
  const box = $("log-guests");
  box.replaceChildren();
  const cat = catalog();
  const ids = [...cat.rooms.keys()].filter((id) => state.comfort[id]);
  if (!ids.length) { box.textContent = "손님을 받을 수 있는 방이 아직 없어요"; return; }
  ids.sort((a, b) => (a === state.roomId ? -1 : b === state.roomId ? 1 : 0));
  for (const id of ids) {
    const c: ComfortView = state.comfort[id];
    const card = div(`guest${id === state.roomId ? " here" : ""}`);
    const head = div("guest-head");
    head.append(document.createTextNode(placeName(cat, id)), Object.assign(document.createElement("span"), { textContent: `☕ ${c.score}` }));
    card.appendChild(head);
    const bar = div("bar");
    const fill = document.createElement("i");
    fill.style.width = `${c.score}%`;
    bar.appendChild(fill);
    card.appendChild(bar);
    const parts = [`가구 ${c.base}`];
    if (c.mult > 1) parts.push(`세트 ×${c.mult}`);
    if (c.ruined) parts.push(`부서진 물건 −${c.ruined * 5}`);
    if (c.affection) parts.push(`고양이 +${c.affection * 3}`);
    parts.push(`침대 ${c.beds}개`);
    card.appendChild(div("guest-sub", parts.join(" · ")));
    let night: string;
    if (c.beds === 0) night = "침대가 없어서 손님을 못 받아요";
    else if (c.skipped) night = "오늘 밤은 손님이 안 와요 (예약을 못 지켰어요)";
    else if (c.guests === 0) night = "너무 허름해서 손님이 안 와요";
    else night = `오늘 밤 손님 ${c.guests}명 · 숙박료 ${c.pay}💰 (1명당 ${c.per_guest}💰)`;
    card.appendChild(div(`guest-night${c.beds === 0 || c.skipped || c.guests === 0 ? " guest-warn" : ""}`, night));
    if (c.reservation) {
      const r = c.reservation;
      const when = r.days_left <= 0 ? "오늘 밤" : `${r.days_left}일 뒤`;
      card.appendChild(div("reserve", r.kind === "dog"
        ? `🐶 개를 좋아하는 손님이 ${when} 와요 — 개 장식이 있거나 안락도 70 이상이면 3배를 내요`
        : `📝 예약: ${when}까지 ${itemName(r.item_id)} 준비 (있으면 2배, 없으면 다음날 손님이 안 와요)`));
    }
    box.appendChild(card);
  }
}

/** Every room that has stages: name, how far along, and the current stage's checklist. */
function renderProgress(): void {
  const box = $("log-progress");
  box.replaceChildren();
  const cat = catalog();
  const ids = [...cat.rooms.keys()].filter((id) => state.progress[id]);
  if (!ids.length) { box.textContent = "복구할 곳이 없어요"; return; }
  // the room we are standing in first
  ids.sort((a, b) => (a === state.roomId ? -1 : b === state.roomId ? 1 : 0));
  for (const id of ids) {
    const p: RoomProgress = state.progress[id];
    const card = document.createElement("div");
    card.className = `restore${id === state.roomId ? " here" : ""}${p.done ? " done" : ""}`;
    const head = document.createElement("div");
    head.className = "restore-head";
    head.textContent = `${placeName(cat, id)} · ${p.stage}/${p.total}단계${p.done ? " · 복구 완료" : p.current ? ` · ${p.current.name}` : ""}`;
    card.appendChild(head);
    if (p.current) {
      for (const n of p.current.needs) {
        const li = document.createElement("div");
        li.className = `need${n.done ? " done" : ""}`;
        li.textContent = needLine(n);
        card.appendChild(li);
      }
      if (p.current.unlocks.length) {
        const r = document.createElement("div");
        r.className = "reward";
        r.textContent = `완료하면 ${p.current.unlocks.map((u) => placeName(cat, u)).join(", ")}이(가) 열려요`;
        card.appendChild(r);
      }
    }
    box.appendChild(card);
  }
}

async function load(): Promise<void> {
  try {
    if (!loot.size) {
      try { loot = new Map((await api.fishInfo()).loot.map((l) => [l.id, l.name])); } catch { /* names fall back to ids */ }
    }
    const r = await api.activity();
    rows = r.events.slice(0, MAX_ROWS);
    today = r.today;
    loaded = true;
    applyProgress(r.progress, r.locked);
    applyComfort(r.comfort);
    renderRows();
    renderSummary();
    renderProgress();
    renderGuests();
  } catch (e) {
    toast(e instanceof ApiError ? msgFor(e.code) : String(e));
  }
}

function open(section?: "progress" | "guests"): void {
  togglePanel("panel-log");
  if ($("panel-log").classList.contains("hidden")) return;
  renderProgress();
  renderGuests();
  if (loaded) { renderRows(); renderSummary(); }
  void load();
  if (section) $(`log-${section}`).scrollIntoView({ block: "start", behavior: "smooth" });
}

/** The comfort picture goes stale whenever any room's items change; refetch it a moment later (debounced). */
function refreshComfort(): void {
  window.clearTimeout(comfortTimer);
  comfortTimer = window.setTimeout(() => {
    void api.rooms().then((r) => applyComfort(Object.fromEntries(r.rooms.filter((x) => x.comfort).map((x) => [x.id, x.comfort!]))))
      .catch(() => { /* offline: keep what we have */ });
  }, 600);
}

export function initLog(): void {
  $("btn-log").addEventListener("click", () => open());
  bus.on("log:open", ({ section }) => open(section));
  bus.on("progress:changed", ({ completed }) => {
    if (!$("panel-log").classList.contains("hidden")) renderProgress();
    const cat = catalog();
    for (const c of completed) {
      const stage = cat.rooms.get(c.room)?.restore?.[c.to - 1];
      toast(`🎉 ${placeName(cat, c.room)} '${stage?.name ?? c.to + "단계"}' 완료!`, 4000);
    }
  });
  socket.on("event", (m: { event: ActivityEvent }) => {
    rows = [m.event, ...rows.filter((r) => r.seq !== m.event.seq)].slice(0, MAX_ROWS);
    const amt = m.event.amount ?? 0;
    switch (m.event.kind) {
      case "earn": today.earned += amt; break;
      case "fish": today.fish += amt; today.fish_count += 1; break;
      case "place": case "remove": today.furniture += amt; break;
      case "sell": today.sold += amt; break;
      case "deliver": today.deliver += amt; break;
      case "guest": today.guests += amt; break;
    }
    if (m.event.kind === "guest" || m.event.kind === "reserve" || m.event.kind === "missed") {
      toast(describe(m.event), 5000);
      refreshComfort();
    }
    if (!$("panel-log").classList.contains("hidden")) { renderRows(); renderSummary(); }
  });
  socket.on("progress", (m: { rooms: Record<string, RoomProgress>; locked: string[] }) => applyProgress(m.rooms, m.locked));
  // the room chip stays in step with the restoration picture
  bus.on("progress:changed", () => renderChip());
  bus.on("room:changed", () => renderChip());
  bus.on("comfort:changed", () => {
    renderChip();
    if (!$("panel-log").classList.contains("hidden")) renderGuests();
  });
  socket.on("room", () => refreshComfort()); // a room's version moved: somebody placed/removed something
  show("panel-log", false);
}

/** `🏠 여관 · 🧹 3 · 1/2단계 · ☕42` — the HUD chip; tapping it opens the checklist. */
function renderChip(): void {
  const p = state.progress[state.roomId];
  const c = state.comfort[state.roomId];
  $("hud-room-stage").textContent = (p ? ` · ${p.done ? "복구 완료" : `${p.stage}/${p.total}단계`}` : "") + (c ? ` · ☕${c.score}` : "");
}
