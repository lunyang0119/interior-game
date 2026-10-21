/** 채팅 panel: everyone online talks in one channel; the last few lines come from /api/chat, new ones over the
 *  socket (`chat`). The scene draws the same line as a speech bubble over the avatar when it was said in the room
 *  you are in (Avatar.say). The 채팅 button carries an unread count while the panel is closed.
 *
 *  Phones: the panel is the usual bottom sheet, but the input row must stay above the software keyboard. Android
 *  shrinks the layout viewport (fixed bottom follows by itself); iOS only shrinks the *visual* viewport, so while
 *  the panel is open we follow `visualViewport` and lift the sheet by the keyboard's height (fitKeyboard).
 *  The train page (/train/) has no chat.
 */

import { api, ApiError, msgFor, type ChatMessage } from "../api";
import { bus, toast } from "../bus";
import { placeName } from "../catalog";
import { catalog, state } from "../state";
import { socket } from "../ws";
import { $, el, show } from "./dom";
import { isDesktop, togglePanel } from "./hud";

export const CHAT_MAX_LEN = 200;
const MAX_ROWS = 50;

let rows: ChatMessage[] = [];
let loaded = false;
let unread = 0;

function isOpen(): boolean {
  return !$("panel-chat").classList.contains("hidden");
}

function fmtWhen(ts: number): string {
  const d = new Date(ts * 1000);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const today = new Date();
  const sameDay = d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
  return sameDay ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}

/** "여관", "광산 3층", "바깥": where the line was said (presence room → place name). */
function whereName(room: string): string {
  const [base, floor] = room.split("#");
  const name = placeName(catalog(), base);
  return floor ? `${name} ${floor}층` : name;
}

function rowEl(m: ChatMessage): HTMLElement {
  const card = el("div", "msg" + (m.player === state.id ? " mine" : ""));
  const head = el("div", "msg-head");
  head.append(el("span", "who", `${m.player} · ${whereName(m.room)}`), el("span", "when", fmtWhen(m.ts)));
  card.append(head, el("div", "text", m.text));
  return card;
}

function scrollToEnd(): void {
  const list = $("chat-list");
  list.scrollTop = list.scrollHeight;
}

function render(): void {
  const list = $("chat-list");
  list.replaceChildren();
  if (!rows.length) { list.append(el("div", "empty", loaded ? "아직 아무 말도 없었어요" : "불러오는 중…")); return; }
  for (const m of rows) list.append(rowEl(m));
  scrollToEnd();
}

function setUnread(n: number): void {
  unread = n;
  const b = $("chat-unread");
  b.textContent = n > 99 ? "99+" : String(n);
  show("chat-unread", n > 0);
}

function push(m: ChatMessage): void {
  if (rows.some((r) => r.id === m.id)) return;
  rows = [...rows, m].slice(-MAX_ROWS);
  if (isOpen()) {
    const list = $("chat-list");
    list.querySelector(".empty")?.remove();
    list.append(rowEl(m));
    scrollToEnd();
  } else if (m.player !== state.id) {
    setUnread(unread + 1);
  }
}

async function load(): Promise<void> {
  if (!state.token) return;
  try {
    const r = await api.chat();
    const seen = new Set(r.messages.map((m) => m.id));
    rows = [...r.messages, ...rows.filter((m) => !seen.has(m.id))].slice(-MAX_ROWS);
    loaded = true;
    if (isOpen()) render();
  } catch (e) {
    if (isOpen()) toast(e instanceof ApiError ? msgFor(e.code) : String(e));
  }
}

function open(): void {
  if (!state.id) { toast("먼저 계정을 골라주세요"); return; }
  togglePanel("panel-chat");
  if (!isOpen()) { unfitKeyboard(); return; }
  setUnread(0);
  render();
  if (!loaded) void load();
  fitKeyboard();
  // desktop only: phones would pop the keyboard over the panel
  if (isDesktop()) $("chat-input").focus();
}

function send(): void {
  const input = $<HTMLInputElement>("chat-input");
  const text = input.value.trim();
  if (!text) return;
  if (!socket.connected) { toast("연결이 끊겨 있어요. 잠시 뒤에 다시 보내요"); return; }
  socket.sendChat(text.slice(0, CHAT_MAX_LEN));
  input.value = "";
}

// ---------------------------------------------------------------- phone keyboard

let vvHandler: (() => void) | null = null;

/** Lift the sheet above the software keyboard (iOS keeps the layout viewport; only visualViewport shrinks). */
function fitKeyboard(): void {
  const vv = window.visualViewport;
  if (!vv || isDesktop() || vvHandler) return;
  const panel = $("panel-chat");
  const apply = () => {
    if (!isOpen()) return;
    const kb = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    if (kb > 0) {
      panel.style.bottom = `${kb + 8}px`;
      panel.style.maxHeight = `${Math.max(160, Math.round(vv.height * 0.6))}px`;
    } else {
      panel.style.bottom = "";
      panel.style.maxHeight = "";
    }
    scrollToEnd();
  };
  vvHandler = apply;
  vv.addEventListener("resize", apply);
  vv.addEventListener("scroll", apply);
  apply();
}

function unfitKeyboard(): void {
  const vv = window.visualViewport;
  if (vv && vvHandler) { vv.removeEventListener("resize", vvHandler); vv.removeEventListener("scroll", vvHandler); }
  vvHandler = null;
  const panel = $("panel-chat");
  panel.style.bottom = "";
  panel.style.maxHeight = "";
}

export function initChat(): void {
  const input = $<HTMLInputElement>("chat-input");
  input.maxLength = CHAT_MAX_LEN;
  $("btn-chat").addEventListener("click", open);
  bus.on("chat:open", open);
  // the send button must not steal focus from the input: on a phone that would drop the keyboard after every line
  const sendBtn = $("chat-send");
  sendBtn.addEventListener("pointerdown", (e) => e.preventDefault());
  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return; // Korean IME: Enter first commits the syllable
    if (e.key === "Enter") { e.preventDefault(); send(); }
    else if (e.key === "Escape") { input.blur(); show("panel-chat", false); unfitKeyboard(); }
  });
  socket.on("chat", (m: ChatMessage) => push(m));
  socket.on("error", (m: { code: string }) => { if (m.code === "rate_limited" && isOpen()) toast(msgFor(m.code)); });
  // the panel closes on any scene change (hud.ts closeAllPanels) and from other panels opening: stop following the keyboard
  document.querySelectorAll<HTMLElement>("[data-close='panel-chat']").forEach((b) => b.addEventListener("click", unfitKeyboard));
  bus.on("scene:changed", unfitKeyboard);
  bus.on("account:switch", () => { rows = []; loaded = false; setUnread(0); unfitKeyboard(); if (isOpen()) render(); });
  // a reconnect may have missed lines
  socket.on("open", () => { if (loaded) void load(); });
}
