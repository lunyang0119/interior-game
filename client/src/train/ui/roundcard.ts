/** Round result card: after each round's playback, one row per crew member (action → result) plus the round's
 *  public headline and the candidate rooms, over the map. Tap to dismiss, hides itself after a while, re-opened from
 *  the HUD 결과 chip. Built only from the report this client received (the intruder's own notes ride on its own copy). */

import type { Report } from "../api";
import { tbus } from "../bus";
import { CAPTURE_HOW_KO, actionText, candidateLine, hackNotice, headline, resultText } from "../report";
import { isFugitive, label, me, tstate } from "../state";
import { $, el, richEl, show } from "./dom";

const AUTO_HIDE_MS = 12_000;
let hideTimer: number | null = null;
let showTimer: number | null = null;

export function initRoundCard(): void {
  $("roundcard").onclick = () => hideRoundCard();
  $("btn-roundcard").onclick = () => {
    const h = tstate.history;
    if ($("roundcard").classList.contains("hidden") && h.length) showRoundCard(h[h.length - 1], 0, false);
    else hideRoundCard();
  };
  tbus.on("state:changed", renderButton);
  tbus.on("history:changed", renderButton);
  renderButton();
}

function renderButton(): void {
  const p = tstate.payload;
  show("btn-roundcard", !!p?.view && p.status !== "LOBBY" && p.status !== "IDLE" && tstate.history.length > 0 && tstate.phase !== "playback");
}

function clearTimers(): void {
  if (hideTimer !== null) { window.clearTimeout(hideTimer); hideTimer = null; }
  if (showTimer !== null) { window.clearTimeout(showTimer); showTimer = null; }
}

export function hideRoundCard(): void {
  clearTimers();
  show("roundcard", false);
}

/** Show `rep`'s card after `delayMs` (an end banner first); `autoHide` false when the player asked for it. */
export function showRoundCard(rep: Report, delayMs = 0, autoHide = true): void {
  clearTimers();
  const open = () => {
    showTimer = null;
    if (tstate.phase === "playback") return;   // the next round already started playing
    render(rep);
    show("roundcard");
    if (autoHide) hideTimer = window.setTimeout(() => { hideTimer = null; show("roundcard", false); }, AUTO_HIDE_MS);
  };
  if (delayMs > 0) showTimer = window.setTimeout(open, delayMs); else open();
}

function render(rep: Report): void {
  const p = tstate.payload;
  const rows = p?.view?.map_rows ?? [];
  const body = $("roundcard-body");
  body.innerHTML = "";
  body.appendChild(richEl("div", "rc-head", `{chart} R${rep.round} 결과`));
  const hl = el("div", "rc-headline");
  for (const s of headline(rep)) hl.appendChild(richEl("span", "", s));
  body.appendChild(hl);
  const notes: string[] = [];
  const notice = hackNotice(rep, isFugitive());
  if (notice) notes.push(notice);
  if (rep.timed_out) notes.push("{clock} 제출 시간 종료 · 미제출자는 대기 처리");
  if (rep.frozen) notes.push("{alert} 침입자 신호가 한 지점에 고정됐어요");
  else if (rep.traced) notes.push("{alert} 추적률 100% · 침입자 위치가 실시간으로 보여요 · 탈출 카운트다운 시작");
  if (rep.captured_by) notes.push(`{trophy} ${label(rep.captured_by)} 체포 (${CAPTURE_HOW_KO[rep.capture_how ?? ""] ?? rep.capture_how})`);
  if (tstate.escape?.round === rep.round) notes.push(`{exit} ${tstate.escape.line}`);
  for (const n of notes) body.appendChild(richEl("div", "rc-note", n));

  // crew rows in the HUD's (tag) order, not the engine's shuffled resolution order
  const tags = (p?.view?.hunters ?? []).map((h) => h.name);
  const colors = new Map((p?.view?.hunters ?? []).map((h) => [h.name, h.color]));
  const rank = (id: string) => { const i = tags.indexOf(id); return i < 0 ? tags.length : i; };
  const sorted = [...rep.playback.hunters].sort((a, b) => rank(a.id) - rank(b.id) || a.id.localeCompare(b.id));
  for (const h of sorted) {
    const row = el("div", "rc-row" + (h.id === me() ? " me" : ""));
    const c = colors.get(h.id);
    if (c) row.style.borderLeft = `4px solid ${c}`;
    row.append(el("span", "rc-name", label(h.id)), el("span", "rc-act", actionText(h)), richEl("span", "rc-res", resultText(h, rep, rows)));
    body.appendChild(row);
  }
  // where the intruder can be now, from this round's public clues (the map shades the same rooms)
  if (!rep.captured_by) {
    const cand = candidateLine(rep, rows, p?.config);
    if (cand) body.appendChild(richEl("div", "rc-cand", cand));
  }
  body.appendChild(el("div", "rc-foot", "눌러서 닫기 · 위의 결과 버튼으로 다시 볼 수 있어요"));
}
