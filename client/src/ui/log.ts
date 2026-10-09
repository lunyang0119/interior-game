/** 📜 기록 panel: the last few things that happened, today's totals, and every room's restoration checklist.
 *
 * The server only ever serves the newest five rows (small talk, not a ledger); new rows arrive live over the
 * socket (`event`), stage completions as `progress`. The HUD room chip opens the same panel at the checklist.
 */

import { api, ApiError, msgFor, type ActivityEvent, type NeedProgress, type RoomProgress } from "../api";
import { bus, toast } from "../bus";
import { placeName, SEED_PLAYER } from "../catalog";
import { applyProgress, catalog, state } from "../state";
import { socket } from "../ws";
import { $, show, togglePanel } from "./hud";

const MAX_ROWS = 5;

let rows: ActivityEvent[] = [];
let loot = new Map<string, string>(); // loot id → name, from /api/fish
let today = { earned: 0, spent: 0, fish: 0 };
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
  $("log-today").textContent = `오늘 · 벌이 +${today.earned}💰 · 지출 −${today.spent}💰 · 낚시 ${today.fish}마리`;
}

function needLine(n: NeedProgress): string {
  const label = n.label || NEED_LABEL[n.type];
  if (n.type === "ruined_zero") return n.done ? `${label} ✓` : `${label} (${n.have}개 남음)`;
  return `${label} ${n.have}/${n.want}${n.done ? " ✓" : ""}`;
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
    renderRows();
    renderSummary();
    renderProgress();
  } catch (e) {
    toast(e instanceof ApiError ? msgFor(e.code) : String(e));
  }
}

function open(section?: "progress"): void {
  togglePanel("panel-log");
  if ($("panel-log").classList.contains("hidden")) return;
  renderProgress();
  if (loaded) { renderRows(); renderSummary(); }
  void load();
  if (section === "progress") $("log-progress").scrollIntoView({ block: "start", behavior: "smooth" });
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
    if (m.event.kind === "earn") today.earned += m.event.amount ?? 0;
    if (m.event.kind === "fish") today.fish += 1;
    if (m.event.kind === "place") today.spent += -(m.event.amount ?? 0);
    if (!$("panel-log").classList.contains("hidden")) { renderRows(); renderSummary(); }
  });
  socket.on("progress", (m: { rooms: Record<string, RoomProgress>; locked: string[] }) => applyProgress(m.rooms, m.locked));
  // the room chip stays in step with the restoration picture
  bus.on("progress:changed", () => renderChip());
  bus.on("room:changed", () => renderChip());
  show("panel-log", false);
}

/** `🏠 여관 · 🧹 3 · 1/2단계` — the HUD chip; tapping it opens the checklist. */
function renderChip(): void {
  const p = state.progress[state.roomId];
  $("hud-room-stage").textContent = p ? ` · ${p.done ? "복구 완료" : `${p.stage}/${p.total}단계`}` : "";
}
