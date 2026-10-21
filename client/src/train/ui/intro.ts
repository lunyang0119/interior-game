/** First-round intro card: three lines over the map when round 1 opens, by role, so a newcomer knows it is a
 *  hide-and-seek before touching anything (the ⓘ panel keeps the full rules). Shown once per game per browser. */

import { tbus } from "../bus";
import { isFugitive, isHunter, tstate } from "../state";
import { roundsLeft } from "../report";
import { $, el, richEl, show } from "./dom";

const KEY = "train_intro";
/** the game-start banner (ws `started`, 3.5 s) plays first; the card follows it */
const AFTER_BANNER_MS = 3600;
let timer: number | null = null;

export function initIntro(): void {
  $("introcard").onclick = () => hideIntro();
  tbus.on("state:changed", maybeShow);
}

function seen(gameId: number): boolean {
  try { return localStorage.getItem(KEY) === String(gameId); } catch { return false; }
}

function markSeen(gameId: number): void {
  try { localStorage.setItem(KEY, String(gameId)); } catch { /* ignore */ }
}

export function hideIntro(): void {
  if (timer !== null) { window.clearTimeout(timer); timer = null; }
  show("introcard", false);
}

function maybeShow(): void {
  const p = tstate.payload;
  if (!p?.game_id || p.status !== "ROUND_OPEN" || (p.round_no ?? 0) !== 1 || tstate.phase === "playback") return;
  if (p.role === "spectator" || seen(p.game_id) || timer !== null) return;
  const id = p.game_id;
  markSeen(id);
  timer = window.setTimeout(() => {
    timer = null;
    if (tstate.payload?.game_id !== id || tstate.phase === "playback") return;
    render();
    show("introcard");
  }, AFTER_BANNER_MS);
}

function lines(): string[] {
  const p = tstate.payload!;
  const left = roundsLeft(p)?.left;
  const limit = left ? `${left}라운드` : "정해진 라운드";
  if (isFugitive() && !p.fugitive_ai) {
    return [
      "{target} 내가 침입자예요. 승무원에게 들키지 않고 열차 안에 숨어요",
      "매 라운드 옆 구역으로 옮기거나 제자리에 있고, RAM으로 퀵핵을 써서 승무원을 방해할 수 있어요",
      "승무원이 내 구역을 수색하거나 나와 같은 문을 같은 라운드에 지나면 체포예요",
      `${limit} 안에 안 잡히면 탈출이에요. 퀵핵을 쓸수록 추적률이 빨리 차고, 100%가 되면 내 위치가 실시간으로 보여요`,
    ];
  }
  const you = isHunter() ? "" : " (지금은 지켜보는 중이에요)";
  return [
    `{search} 침입자 한 명이 열차 어딘가에 숨어 있어요${you}`,
    "매 라운드 옆 구역으로 가거나, 지금 구역을 뒤지거나, 신호를 탐색해요",
    "침입자가 있는 구역을 뒤지면 체포예요. 침입자와 같은 문을 같은 라운드에 지나도 체포예요",
    `${limit} 안에 못 잡으면 침입자가 탈출해요. ◎ 표식과 후보 구역을 보고 좁혀 가요`,
  ];
}

function render(): void {
  const body = $("introcard-body");
  body.innerHTML = "";
  body.appendChild(richEl("div", "rc-head", isFugitive() && !tstate.payload?.fugitive_ai ? "{target} 추적 시작 · 침입자" : "{search} 추적 시작 · 승무원"));
  for (const s of lines()) body.appendChild(richEl("div", "intro-line", s));
  body.appendChild(el("div", "rc-foot", "눌러서 닫기 · 자세한 규칙은 도움말 버튼"));
}
