/** Lobby / idle / game-over panel: who is aboard, join/leave, (admin) start, and anyone's "새 추적 열기" when no
 *  chase runs or the last one ended (the server lets anyone open a game then). */

import { api, msgFor, type MapSummary, type TrainState } from "../api";
import { tbus, toast } from "../bus";
import { CAPTURE_HOW_KO } from "../report";
import { isAdmin, isBot, isOver, label, me, tstate } from "../state";
import { $, button, el, openPanel, richEl, show } from "./dom";

let maps: MapSummary[] = [];
let countdown: number | null = null;
/** the 출발 button lives across re-renders so a state push mid-countdown keeps its label and its handler */
let goBtn: HTMLButtonElement | null = null;
const GO_LABEL = "출발 (라운드 1 시작)";
let lastStatus: string | null = null;
/** the panel should open at the next chance (a status transition happened, maybe during a playback) */
let wantOpen = false;
/** status the "새 추적 열기" form was built for */
let formFor: string | null = null;

export function initLobby(): void {
  tbus.on("state:changed", render);
  render();
}

async function loadMaps(): Promise<void> {
  if (maps.length) return;
  try { maps = (await api.maps()).maps; } catch { /* keep "auto" only */ }
}

function stopCountdown(): void {
  if (countdown !== null) { window.clearInterval(countdown); countdown = null; }
  if (goBtn) goBtn.textContent = GO_LABEL;
}

function startButton(): HTMLButtonElement {
  if (goBtn) return goBtn;
  const go = goBtn = button(GO_LABEL, () => {
    // 3-second countdown so a crew member still reading can shout; tapping again cancels
    if (countdown !== null) { stopCountdown(); toast("출발을 취소했어요"); return; }
    let n = 3;
    go.textContent = `출발 ${n}… (취소)`;
    countdown = window.setInterval(async () => {
      n--;
      if (n > 0) { go.textContent = `출발 ${n}… (취소)`; return; }
      stopCountdown();
      try { await api.start(); } catch (e) { toast(msgFor(e)); }
    }, 1000);
  }, "primary");
  return go;
}

/** "새 추적 열기" row: seats, map, AI fugitive. Shown while IDLE and after a chase ended. */
function createForm(actions: HTMLElement): void {
  void loadMaps().then(() => {
    const st = tstate.payload?.status ?? "IDLE";
    if (st !== "IDLE" && !isOver(st)) return;   // a game opened while the maps were loading
    actions.innerHTML = "";
    const row = el("div", "row");
    const n = el("select");
    for (let i = 2; i <= 6; i++) { const o = el("option", "", `${i}명`); o.value = String(i); if (i === 4) o.selected = true; n.appendChild(o); }
    const m = el("select");
    const auto = el("option", "", "맵: 인원에 맞게"); auto.value = ""; m.appendChild(auto);
    for (const x of maps) { const o = el("option", "", `${x.id} (${x.rooms}칸)`); o.value = x.id; m.appendChild(o); }
    const ai = el("label", "small");
    const aiBox = el("input"); aiBox.type = "checkbox";
    ai.append(aiBox, " 도주자도 AI");
    ai.title = "도주자를 Gemini가 맡아요. 연 사람은 관제를 유지하면서 승무원으로 탑승할 수 있어요";
    row.append(n, m, button("새 추적 열기", async () => {
      try { await api.create(Number(n.value), m.value || undefined, aiBox.checked); } catch (e) { toast(msgFor(e)); }
    }, "primary"));
    if (tstate.payload?.ai_available) row.appendChild(ai);
    actions.appendChild(row);
  });
}

/** What happened in the chase that just ended (everyone sees the same public facts). */
function summaryLines(p: TrainState): string[] {
  const h = tstate.history;
  const rep = p.report ?? (h.length ? h[h.length - 1] : null);
  const out: string[] = [];
  if (p.status === "CAPTURED") {
    const by = rep?.captured_by;
    out.push(by
      ? `{trophy} R${rep!.round} 체포 · ${label(by)} (${CAPTURE_HOW_KO[rep!.capture_how ?? ""] ?? rep!.capture_how})`
      : "{trophy} 도주자가 잡혔어요");
  } else {
    out.push(`{exit} 도주자가 ${tstate.escape?.round ?? rep?.round ?? "?"}라운드에 빠져나갔어요`);
    if (tstate.escape?.line) out.push(tstate.escape.line);
  }
  if (rep) out.push(`최종 추적률 ${rep.trace}% · ${rep.round}라운드 진행`);
  if (p.route?.length) out.push("{pin} 도주자의 라운드별 경로가 맵에 그려져 있어요");
  if (p.ai_log?.length) out.push("{chat} AI의 판단은 보고 패널에서 볼 수 있어요");
  out.push("새 추적을 열면 이 판은 닫히고, 연 사람이 관제가 돼요");
  return out;
}

function render(): void {
  const p = tstate.payload;
  const st = p?.status ?? "IDLE";
  const over = isOver(st);
  const lobbyish = st === "LOBBY" || st === "IDLE" || over;
  if (st !== lastStatus) {
    lastStatus = st;
    wantOpen = lobbyish;
    if (st !== "LOBBY") stopCountdown();
  }
  const list = $("lobby-list");
  const actions = $("lobby-actions");
  const info = $("lobby-info");
  const summary = $("lobby-summary");
  if (!lobbyish) { wantOpen = false; show("panel-lobby", false); return; }
  // open only on a status change, after any playback, and without closing a panel the player has open
  if (wantOpen && tstate.phase !== "playback") {
    wantOpen = false;
    const other = [...document.querySelectorAll<HTMLElement>(".panel")].some((x) => x.id !== "panel-lobby" && !x.classList.contains("hidden"));
    if (!other) openPanel("panel-lobby");
  }
  list.innerHTML = "";
  summary.innerHTML = "";
  show("lobby-summary", over);

  if (st === "IDLE" || over) {
    if (over && p) for (const line of summaryLines(p)) summary.appendChild(richEl("div", "small", line));
    info.textContent = over ? "" : "진행 중인 추적이 없어요. 새 추적을 열면 이 계정이 관제(도주자)가 돼요.";
    show("lobby-info", !over);
    // keep the form (and the player's picks in it) across state pushes
    if (formFor !== st || !actions.children.length) { formFor = st; actions.innerHTML = ""; createForm(actions); }
    return;
  }
  formFor = null;
  show("lobby-info", true);

  actions.innerHTML = "";
  const lobby = p?.lobby ?? [];
  info.textContent = `맵 ${p?.map_id} · 승무원 ${lobby.length}/${p?.hunter_count}명 · 도주자: ${p?.fugitive_ai ? "AI" : "관제"}`;
  for (const id of lobby) {
    const row = richEl("div", "lobby-row", `${isBot(id) ? "{chat}" : "{gamepad}"} ${label(id)}${id === me() ? " (나)" : ""}`);
    list.appendChild(row);
  }
  if (!lobby.length) list.appendChild(el("div", "small muted", "아직 아무도 탑승하지 않았어요"));
  list.appendChild(el("div", "small muted", `출발 인원 기준으로 맵과 밸런스가 정해져요 (현재 ${lobby.length}명)`));
  const bots = lobby.filter(isBot).length;
  if (isAdmin() && p?.ai_available && lobby.length < (p.hunter_count ?? 0)) {
    actions.appendChild(button(`AI 승무원으로 채우기 (${(p.hunter_count ?? 0) - lobby.length}명)`, async () => {
      try { await api.addBots(p.hunter_count ?? 2); } catch (e) { toast(msgFor(e)); }
    }));
  }
  if (isAdmin() && bots) {
    actions.appendChild(button(`AI 승무원 내리기 (${bots}명)`, async () => {
      try { await api.removeBots(); } catch (e) { toast(msgFor(e)); }
    }));
  }
  if (isAdmin() && p?.ai_available) {
    actions.appendChild(button(p.fugitive_ai ? "도주자: AI → 내가 맡기" : "도주자: 내가 → AI에게 맡기기", async () => {
      try { await api.setFugitiveAi(!p.fugitive_ai); } catch (e) { toast(msgFor(e)); }
    }));
  }
  if (isAdmin()) {
    actions.appendChild(startButton());
    actions.appendChild(button("추적 취소", async () => {
      if (!confirm("이 추적을 닫을까요?")) return;
      try { await api.endGame(); } catch (e) { toast(msgFor(e)); }
    }, "danger"));
  }
  if (isAdmin() && !p?.fugitive_ai) {
    // the admin is the fugitive: no riding
  } else if (me() && lobby.includes(me()!)) {
    actions.appendChild(button("하차", async () => { try { await api.leave(); } catch (e) { toast(msgFor(e)); } }));
  } else if (me()) {
    actions.appendChild(button("탑승", async () => { try { await api.join(); } catch (e) { toast(msgFor(e)); } }, "primary"));
  }
}
