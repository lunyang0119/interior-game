/** Top HUD: round, remaining time, trace, who has not submitted, my order, status. Renders from tstate on state:changed. */

import { tbus } from "../bus";
import { fmtRemain } from "../report";
import { isAdmin, isFugitive, isHunter, label, tstate } from "../state";
import { ORDER_KO } from "../strings";
import { setTitleBadge } from "../cues";
import { $, openPanel, show } from "./dom";

let timer: number | null = null;

export function initHud(): void {
  $("btn-report").onclick = () => openPanel("panel-report");
  $("btn-vote").onclick = () => openPanel("panel-vote");
  $("hud-sub").onclick = () => openPanel("panel-vote");
  $("btn-admin").onclick = () => openPanel("panel-admin");
  $("btn-home-cam").onclick = () => tbus.emit("camera:home", {});
  $("btn-lobby").onclick = () => openPanel("panel-lobby");
  $("btn-order-change").onclick = () => { $("orderbar").classList.remove("folded"); tbus.emit("orderbar:unfold", {}); };
  tbus.on("state:changed", render);
  if (timer === null) timer = window.setInterval(tick, 1000);
  render();
}

/** Who still has to submit (names, not counts); dazed hunters count as done. */
export function pendingHunters(): string[] {
  const p = tstate.payload;
  return (p?.view?.hunters ?? []).filter((h) => !h.submitted && !h.dazed).map((h) => h.name);
}

function tick(): void {
  const p = tstate.payload;
  const el = $("hud-clock-val");
  const now = Date.now() / 1000;
  if (!p || p.status !== "ROUND_OPEN" || !p.deadline_ts) {
    el.textContent = p?.status === "PAUSED" ? (p.paused_remaining != null ? `일시정지 · ${fmtRemain(p.paused_remaining)}` : "일시정지") : "–";
  } else {
    const grace = p.grace_until != null && p.grace_until < p.deadline_ts;
    el.textContent = (grace ? "도주자 대기 " : "") + fmtRemain((grace ? p.grace_until! : p.deadline_ts) - now);
  }
  // the vote chip: once the window opens; before that it counts down to it
  const pending = pendingHunters().filter((n) => n !== p?.you?.id);
  const open = p?.vote_after_ts != null && now >= p.vote_after_ts;
  show("btn-vote", isHunter() && pending.length > 0 && p?.status === "ROUND_OPEN");
  $("btn-vote-val").textContent = open || p?.vote_after_ts == null ? "건너뛰기" : `투표 ${fmtRemain(p.vote_after_ts - now).replace(" 남음", " 뒤")}`;
  $("btn-vote").title = open ? "미제출자 건너뛰기 투표" : "이 시간이 지나면 미제출자 건너뛰기 투표를 열 수 있어요";
  // tab title: my turn, or a result I have not watched yet
  const myTurn = p?.status === "ROUND_OPEN" && tstate.phase !== "playback" && (
    (isHunter() && !!p.you && !p.you.order && !p.you.dazed) || (isFugitive() && !p.fugitive_ai && !!p.fugitive && !p.fugitive.order));
  setTitleBadge(myTurn || tstate.unseenResult, myTurn ? "내 차례" : tstate.unseenResult ? "새 결과" : "");
}

function render(): void {
  const p = tstate.payload;
  const v = p?.view;
  const round = p && v && p.status !== "LOBBY" && p.status !== "IDLE" ? `R${p.round_no ?? v.round_no}` : "";
  const trace = p?.fugitive ? p.fugitive.trace : (p?.report?.trace ?? v?.trace ?? 0);
  const tier = p?.fugitive ? p.fugitive.tier : (p?.report?.tier ?? 0);
  $("hud-trace-val").textContent = p && v ? `${trace}% · 경계도 ${tier}` : "–";
  // submission status by name
  const pending = pendingHunters();
  const total = v?.hunters.length ?? 0;
  const sub = $("hud-sub-val");
  const fug = p?.status === "ROUND_OPEN" ? (p.fugitive_submitted ? " · 도주자 ✓" : tstate.thinking.has("fugitive") ? " · 도주자 판단 중" : " · 도주자 미제출") : "";
  if (!total) sub.textContent = "–";
  else if (!pending.length) sub.textContent = `승무원 전원 제출${fug}`;
  else sub.textContent = `미제출 ${pending.length}: ${pending.map((n) => label(n) + (tstate.thinking.has(n) ? "(판단 중)" : "")).join(", ")}${fug}`;
  const st = p?.status ?? "IDLE";
  const spectator = p?.role === "spectator" && st !== "IDLE" && st !== "LOBBY";
  const [icon, lbl] = st === "LOBBY" ? ["exit", "모집 중"] : st === "PAUSED" ? ["pause", `${round} 일시정지`] : st === "CAPTURED" ? ["trophy", `${round} 체포`]
    : st === "IDLE" ? ["power", "대기"] : tstate.phase === "playback" ? ["play", `${round} 재생`] : spectator ? ["camera", `${round} 관전 중`] : ["signal", `${round} 진행 중`];
  $("hud-status").innerHTML = `<i class="ic ic-${icon}"></i><span>${lbl}</span>`;
  $("hud-status").title = spectator ? "이 추적의 참가자가 아니라 지켜보는 중이에요. 다음 판에 로비에서 탑승하세요" : "추적 상태";
  // my submitted order stays on the HUD
  const o = p?.you?.order;
  const mine = isHunter() && st === "ROUND_OPEN" && !!o;
  show("hud-order", mine);
  if (mine && o) $("hud-order-val").textContent = o.type === "move" ? `이동 → ${o.target}` : `${ORDER_KO[o.type]}${o.type === "search" ? ` (${p?.you?.room})` : ""}`;
  show("btn-admin", isAdmin());
  show("btn-lobby", st === "LOBBY" || st === "IDLE");
  show("hud-game", st !== "IDLE" && st !== "LOBBY");
  tick();
}
