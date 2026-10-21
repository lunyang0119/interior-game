/** Top HUD: round, remaining time, trace gauge, escape countdown, who has not submitted, my order, status.
 *  Renders from tstate on state:changed. */

import { tbus } from "../bus";
import { fmtRemain, markerAge, roundsLeft, tierOf, traceStage } from "../report";
import { isAdmin, isFugitive, isHunter, isOver, label, tstate } from "../state";
import { ORDER_KO } from "../strings";
import { setTitleBadge } from "../cues";
import { $, openPanel, setRich, show } from "./dom";

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
    // the intruder's grace: kept while grace_until is set (also after a resume moved the deadline onto it)
    const grace = p.grace_until != null;
    const end = grace ? Math.min(p.grace_until!, p.deadline_ts) : p.deadline_ts;
    const me = isFugitive() && !p.fugitive_ai;
    el.textContent = (grace ? (me ? "내 제출 대기 " : "침입자 대기 ") : "") + fmtRemain(end - now);
  }
  const clock = $("hud-clock");
  clock.title = p?.status === "ROUND_OPEN" && p.grace_until != null
    ? (isFugitive() && !p.fugitive_ai ? "승무원이 모두 제출했어요. 유예가 끝나기 전에 내 행동을 확정해요" : "승무원이 모두 제출했어요. 침입자가 확정하거나 유예가 끝나면 결과가 나와요")
    : p?.fugitive_ai ? "제출 마감까지 남은 시간. 모두 확정하면 바로 결과가 나와요"
      : "제출 마감까지 남은 시간. 승무원이 모두 확정하면 침입자 유예 뒤 결과가 나와요";
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

/** The trace gauge: a bar filled to the trace %, the stage word and what the ◎ marker means right now. */
function renderTrace(): void {
  const p = tstate.payload;
  const v = p?.view;
  const trace = p?.fugitive ? p.fugitive.trace : (p?.report?.trace ?? v?.trace ?? 0);
  const frozen = p?.fugitive ? p.fugitive.frozen : !!p?.frozen;
  const tier = p?.fugitive ? p.fugitive.tier : (p?.report?.tier ?? tierOf(trace, p?.config));
  const on = !!p && !!v;
  $("hud-trace-fill").style.width = on ? `${Math.max(0, Math.min(100, trace))}%` : "0%";
  $("hud-trace").classList.toggle("hot", on && tier >= 3);
  $("hud-trace-val").textContent = on ? `${trace}% · ${markerAge(tier, frozen)}` : "–";
  $("hud-trace").title = on
    ? `추적률 ${trace}% (${traceStage(tier, frozen)}). 라운드마다 오르고 침입자가 퀵핵을 쓰면 더 올라요. 높을수록 ◎ 표식이 더 최신 위치를 가리켜요. 100%가 되면 위치가 실시간으로 보이고 탈출 카운트다운이 시작돼요`
    : "추적률";
}

/** Rounds: "R3 / 14" normally; once the trace hit 100 %, the escape countdown ("탈출까지 2라운드"). */
function renderRounds(round: string): void {
  const p = tstate.payload;
  const chip = $("hud-round");
  const left = p && p.view && p.status !== "LOBBY" && p.status !== "IDLE" ? roundsLeft(p) : null;
  if (!p || !left) { show("hud-round", false); return; }
  show("hud-round", true);
  const over = isOver(p.status);
  const done = Math.max(0, (p.round_no ?? 1) - 1);
  const max = Number(p.config?.max_rounds ?? 0);
  const warn = left.traced && !over;
  chip.classList.toggle("warn", warn);
  if (over) setRich(chip, `{clock} ${done}라운드 진행`);
  else if (warn) setRich(chip, `{alert} 탈출까지 ${left.left}라운드${left.left <= 1 ? " · 마지막" : ""}`);
  else setRich(chip, `{clock} ${round}${max ? ` / ${max}` : ""}`);
  chip.title = warn
    ? `추적률이 100%가 돼서 침입자 신호가 곧 끊겨요. ${left.left}라운드 안에 못 잡으면 침입자가 탈출해요`
    : `${max ? `${max}라운드` : "정해진 라운드"} 안에 못 잡으면 침입자가 탈출해요 (지금 ${left.left}라운드 남음)`;
}

function render(): void {
  const p = tstate.payload;
  const v = p?.view;
  // while a round plays back, the chip names that round (the payload already moved on to the next one)
  const round = p && v && p.status !== "LOBBY" && p.status !== "IDLE" ? `R${tstate.playing?.round ?? p.round_no ?? v.round_no}` : "";
  renderTrace();
  renderRounds(round);
  // submission status by name
  const pending = pendingHunters();
  const total = v?.hunters.length ?? 0;
  const sub = $("hud-sub-val");
  const fug = p?.status === "ROUND_OPEN" ? (p.fugitive_submitted ? " · 침입자 {save}" : tstate.thinking.has("fugitive") ? " · 침입자 판단 중" : " · 침입자 미제출") : "";
  if (!total) sub.textContent = "–";
  else if (!pending.length) setRich(sub, `승무원 전원 제출${fug}`);
  else setRich(sub, `미제출 ${pending.length}: ${pending.map((n) => label(n) + (tstate.thinking.has(n) ? "(판단 중)" : "")).join(", ")}${fug}`);
  const st = p?.status ?? "IDLE";
  const spectator = p?.role === "spectator" && st !== "IDLE" && st !== "LOBBY";
  const [icon, lbl] = st === "LOBBY" ? ["exit", "모집 중"] : st === "PAUSED" ? ["pause", `${round} 일시정지`] : st === "CAPTURED" ? ["trophy", `${round} 체포`] : st === "ESCAPED" ? ["exit", `${round} 탈출`]
    : st === "IDLE" ? ["power", "대기"] : tstate.phase === "playback" ? ["play", `${round} 재생`] : spectator ? ["camera", `${round} 관전 중`] : ["signal", `${round} 진행 중`];
  $("hud-status").innerHTML = `<i class="ic ic-${icon}"></i><span>${lbl}</span>`;
  $("hud-status").title = spectator ? "이 추적의 참가자가 아니라 지켜보는 중이에요. 다음 판에 로비에서 탑승하세요" : "추적 상태";
  // my submitted order stays on the HUD
  const o = p?.you?.order;
  const mine = isHunter() && st === "ROUND_OPEN" && !!o;
  show("hud-order", mine);
  if (mine && o) $("hud-order-val").textContent = o.type === "move" ? `이동 → ${o.target}` : `${ORDER_KO[o.type]}${o.type === "search" ? ` (${p?.you?.room})` : ""}`;
  show("btn-admin", isAdmin());
  show("btn-lobby", st === "LOBBY" || st === "IDLE" || isOver(st));
  // spectators have no avatar to centre on
  show("btn-home-cam", !!p && p.role !== "spectator");
  show("hud-game", st !== "IDLE" && st !== "LOBBY");
  tick();
}
