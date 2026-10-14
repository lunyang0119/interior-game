/** Top HUD: round, countdown, trace, submitted count, status, panel buttons. Renders from tstate on state:changed. */

import { tbus } from "../bus";
import { fmtCountdown } from "../report";
import { isFugitive, isHunter, tstate } from "../state";
import { $, openPanel, show } from "./dom";

let timer: number | null = null;

export function initHud(): void {
  $("btn-report").onclick = () => openPanel("panel-report");
  $("btn-vote").onclick = () => openPanel("panel-vote");
  $("btn-admin").onclick = () => openPanel("panel-admin");
  $("btn-home-cam").onclick = () => tbus.emit("camera:home", {});
  $("btn-lobby").onclick = () => openPanel("panel-lobby");
  tbus.on("state:changed", render);
  if (timer === null) timer = window.setInterval(tick, 1000);
  render();
}

function tick(): void {
  const p = tstate.payload;
  const el = $("hud-clock-val");
  if (!p || p.status !== "ROUND_OPEN" || !p.deadline_ts) { el.textContent = p?.status === "PAUSED" ? "일시정지" : "–"; return; }
  const now = Date.now() / 1000;
  const due = p.grace_until != null && p.grace_until < p.deadline_ts ? p.grace_until : p.deadline_ts;
  el.textContent = (p.grace_until != null && p.grace_until < p.deadline_ts ? "유예 " : "") + fmtCountdown(due - now);
  // the vote button appears once the skip window opened and somebody has not submitted yet
  // the vote button shows whenever someone else has not submitted; before the window opens it counts down to it
  const pending = (p.view?.hunters ?? []).some((h) => !h.submitted && !h.dazed && h.name !== p.you?.id);
  const open = p.vote_after_ts != null && now >= p.vote_after_ts;
  show("btn-vote", isHunter() && pending);
  $("btn-vote").textContent = open || p.vote_after_ts == null ? "🗳 건너뛰기" : `🗳 ${fmtCountdown(p.vote_after_ts - now)}`;
  $("btn-vote").title = open ? "미제출자 건너뛰기 투표" : "이 시간이 지나면 미제출자 건너뛰기 투표를 열 수 있어요";
}

function render(): void {
  const p = tstate.payload;
  const v = p?.view;
  $("hud-round-val").textContent = p && v && p.status !== "LOBBY" && p.status !== "IDLE" ? `R${p.round_no ?? v.round_no}` : "–";
  const trace = p?.fugitive ? p.fugitive.trace : (p?.report?.trace ?? v?.trace ?? 0);
  $("hud-trace-val").textContent = p && v ? `${trace}%` : "–";
  $("hud-trace").title = p?.report ? `신호 ${p.report.signal}` : "";
  const total = v?.hunters.length ?? 0;
  const done = v?.hunters.filter((h) => h.submitted || h.dazed).length ?? 0;
  $("hud-sub-val").textContent = total ? `${done}/${total}` : "–";
  const st = p?.status ?? "IDLE";
  $("hud-status").textContent = st === "LOBBY" ? "🚃 모집 중" : st === "PAUSED" ? "⏸ 일시정지" : st === "CAPTURED" ? "★ 체포" : st === "IDLE" ? "대기" : tstate.phase === "playback" ? "▶ 재생" : "📡 라운드 진행";
  show("btn-admin", isFugitive());
  show("btn-lobby", st === "LOBBY" || st === "IDLE");
  show("hud-game", st !== "IDLE" && st !== "LOBBY");
  tick();
}
