/** Korean text of a round report (the bot's strings.py REPORT_* lines, minus Discord markdown). */

import type { Hack, PlaybackHunter, Report, ReportEvent } from "./api";
import { DEVICE_KO, HACK_KO, ORDER_KO } from "./strings";

export const SIGNAL_KO: Record<string, string> = { strong: "강", medium: "중", weak: "약", none: "없음", noise: "판독 불가" };
export const CAPTURE_HOW_KO: Record<string, string> = { search: "수색", swap: "같은 문 통과", colocate: "같은 구역" };
/** device signature → the quickhack bound to it (strings.py HACK_DEVICE; the help panel shows the same table) */
const HACK_OF_DEVICE: Record<string, Hack> = { speaker: "distract", light: "blackout", curtain: "hide", coffeepot: "overload" };
/** how long the quickhack notice stays on screen while a round plays back */
export const HACK_NOTICE_MS = 6500;

/** The quickhack notice for a round: what the fugitive did and where, as far as this client may know.
 *  Hunters get public facts only (locked doors, steam rooms, the blackout, the device signature);
 *  the fugitive sees their own order and whether it actually fired (the engine voids a hack it can no longer pay for). */
export function hackNotice(rep: Report, fugitiveView: boolean): string | null {
  if (fugitiveView && rep.fugitive_order !== undefined) {
    const o = rep.fugitive_order;
    const hidden = rep.hidden_events ?? [];
    const voided = hidden.find((s) => /^퀵핵 .* 무효: /.test(s));
    const stopped = hidden.find((s) => /앞에서 정지/.test(s));
    const parts: string[] = [];
    if (o?.hack) {
      parts.push(voided
        ? `{alert} 퀵핵 무효 — ${voided.replace(/^퀵핵 \S+ 무효: /, "")}`
        : `{target} 퀵핵 실행 — ${HACK_KO[o.hack] ?? o.hack}${o.target ? ` (${o.target})` : ""}`);
    }
    if (stopped) parts.push(`{exit} ${stopped}`);
    return parts.length ? parts.join(" · ") : null;
  }
  const parts: string[] = [];
  if (rep.locks.length) parts.push(`{exit} 문 잠금: ${rep.locks.join(", ")}`);
  if (rep.steam.length) parts.push(`{power} 과부하: ${rep.steam.join(", ")}에 증기`);
  if (rep.blackout) parts.push("▒ 광학 재부팅: 이번 라운드 추적기 판독 불가");
  if (rep.signature === "ping") parts.push("{signal} 핑: 도주자가 승무원 명령을 들여다봤어요");
  else if (rep.signature) {
    const hk = HACK_OF_DEVICE[rep.signature];
    const dev = DEVICE_KO[rep.signature] ?? rep.signature;
    if (hk === "distract") parts.push(`{speaker} 교란: ${dev} 장치 비정상 접근 · 가짜 표식이 섞여 있어요 (진짜와 겹치면 하나로 보여요)`);
    else if (hk === "hide") parts.push(`{target} 은신: ${dev} 장치 비정상 접근 — 침입자가 몸을 숨겼어요`);
    else if (!(hk === "blackout" && rep.blackout) && !(hk === "overload" && rep.steam.length)) parts.push(`{alert} ${dev} 계열 장치에서 비정상 접근 감지`);
  }
  return parts.length ? `퀵핵 감지 — ${parts.join(" · ")}` : null;
}

export function eventLine(ev: ReportEvent, name: (uid: string) => string): string {
  const n = name(ev.uid);
  switch (ev.type) {
    case "door_locked": return `{exit} ${n}: 문이 잠겨 있다 (${ev.edge})`;
    case "dazed": return `{power} ${n}: 커피포트가 과부하로 터졌다. 증기에 휩싸여 다음 라운드 행동 불가`;
    case "search_steam": return `{power} ${n}: 증기 때문에 ${ev.room} 수색 실패`;
    case "search_empty": return `{search} ${n}: ${ev.room} 수색 — 이상 없음`;
    case "scan": return `{signal} ${n}: 추적 결과 · 침입자가 지금 있는 구역의 장치는 ${DEVICE_KO[ev.device ?? ""] ?? ev.device} 계열`;
    case "scan_noise": return `{signal} ${n}: 노이즈 — 판독 실패`;
    case "scan_busy": return `{signal} ${n}: 채널 혼선 — 이번 라운드 추적 채널이 이미 사용 중`;
    case "contact_miss": return `{alert} ${n}: ${ev.room} 에서 접촉! 그러나 신호가 손끝을 스쳐 빠져나갔다`;
    case "glimpse": return `{camera} ${n}: ${ev.room} 에서 침입자 신호의 주인을 목격! 수색하지 않아 놓쳤다`;
    default: return `${n}: ${ev.type}`;
  }
}

/** Short bubble over a hunter after the walk (playback). Plain text: Phaser draws it, `{icon}` tokens would show raw. */
export function resultBubble(result: string | null, _action: string, device?: string): string | null {
  switch (result) {
    case "captured": return "체포!";
    case "search_empty": return "이상 없음";
    case "search_steam": return "수색 실패";
    case "dazed": return "증기…";
    case "scan_ok": return `추적: ${DEVICE_KO[device ?? ""] ?? "?"}`;
    case "scan_noise": return "노이즈";
    case "scan_busy": return "혼선";
    default: return null;
  }
}

/** "이동 → B2" / "수색 (A1)" / "추적" / "대기": what a crew member did this round (round card, crew list). */
export function actionText(h: PlaybackHunter): string {
  if (h.action === "move") return `이동 → ${h.to}`;
  if (h.action === "search") return `수색 (${h.from})`;
  return ORDER_KO[h.action] ?? h.action;
}

/** What came of it, in words (DOM text, may carry `{icon}` tokens). */
export function resultText(h: PlaybackHunter, rep: Report): string {
  const glimpse = rep.events.find((e) => e.type === "glimpse" && e.uid === h.id);
  const extra = glimpse ? ` · {camera} ${glimpse.room}에서 침입자 목격` : "";
  if (h.result === "captured") return "{trophy} 체포!";
  if (h.blocked_edge) return `{close} 문이 잠겨 있었어요 (${h.blocked_edge})${extra}`;
  switch (h.result) {
    case "search_empty": return `{search} 이상 없음${extra}`;
    case "search_steam": return `{power} 증기로 수색 실패${extra}`;
    case "dazed": return `{power} 증기에 휩싸임 (다음 라운드 행동 불가)${extra}`;
    case "scan_ok": {
      const dev = rep.events.find((e) => e.type === "scan" && e.uid === h.id)?.device;
      return `{signal} 추적: ${DEVICE_KO[dev ?? ""] ?? dev ?? "?"}${extra}`;
    }
    case "scan_noise": return `{signal} 노이즈${extra}`;
    case "scan_busy": return `{signal} 혼선 (추적 채널이 이미 다 쓰임)${extra}`;
  }
  if (glimpse) return extra.slice(3);
  return h.action === "move" ? "도착" : "–";
}

/** The round's public headline: trace, signal, markers, locked doors, steam. */
export function headline(rep: Report): string[] {
  const out = [`{target} 추적률 ${rep.trace}%`];
  if (rep.blackout) out.push("▒ 판독 불가 (광학 재부팅)");
  else {
    out.push(`{signal} 신호 강도 ${SIGNAL_KO[rep.signal] ?? rep.signal}`);
    out.push(rep.markers.length ? `◎ 표식 ${rep.markers.join(", ")}` : "◎ 표식 없음");
  }
  if (rep.locks.length) out.push(`{close} 잠긴 문 ${rep.locks.join(", ")}`);
  if (rep.steam.length) out.push(`{power} 증기 ${rep.steam.join(", ")}`);
  return out;
}

export function reportLines(rep: Report, name: (uid: string) => string): string[] {
  const out: string[] = [];
  out.push(`{signal} 라운드 ${rep.round} 판독 결과`);
  if (rep.timed_out) out.push("{clock} 제출 시간 종료 · 미제출자는 대기 처리");
  if (rep.blackout) out.push("▒▒▒ 신호 소실 — 이번 라운드 판독 불가 ▒▒▒");
  out.push(`추적률 ${rep.bar} ${rep.trace}%`);
  out.push(rep.distance !== null && rep.distance !== undefined
    ? `신호 강도: ${SIGNAL_KO[rep.signal] ?? rep.signal} (거리 ${rep.distance})`
    : `신호 강도: ${SIGNAL_KO[rep.signal] ?? rep.signal}`);
  if (rep.signature) out.push(rep.signature === "ping" ? "{alert} 추적기 역탐지 시그니처 감지" : `{alert} ${DEVICE_KO[rep.signature] ?? rep.signature} 계열 장치에서 비정상 접근 감지`);
  if (rep.markers.length) out.push(`◎ 신호 감지: ${rep.markers.join(", ")}`);
  if (rep.locks.length) out.push(`{close} 잠긴 문: ${rep.locks.join(", ")}`);
  for (const r of rep.steam) out.push(`{power} ${r} 에 증기가 가득하다`);
  // the fugitive's own log entry: the order as submitted and the engine's hidden notes
  if (rep.fugitive_order !== undefined) {
    const o = rep.fugitive_order;
    out.push(`{target} 내 행동: ${o?.move ? `이동 → ${o.move}` : "제자리"}${o?.hack ? ` + ${HACK_KO[o.hack] ?? o.hack}${o.target ? ` (${o.target})` : ""}` : ""}`);
    for (const s of rep.hidden_events ?? []) out.push(`{target} ${s}`);
  }
  for (const ev of rep.events) out.push(eventLine(ev, name));
  if (rep.traced) out.push("{alert} 추적률 100% — 침입자 신호 실시간 추적 중");
  if (rep.frozen) out.push("{alert} 침입자 신호가 한 지점에 고정되었다");
  if (rep.captured_by) out.push(`{trophy} 체포: ${name(rep.captured_by)} (${CAPTURE_HOW_KO[rep.capture_how ?? ""] ?? rep.capture_how}, R${rep.round})`);
  return out;
}

/** "47분 남음" style relative time, ticking client-side from server timestamps (no absolute clock anywhere). */
export function fmtRemain(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}초 남음`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  if (h >= 24) return `${Math.floor(h / 24)}일 ${h % 24}시간 남음`;
  if (h > 0) return `${h}시간 ${m}분 남음`;
  if (s < 120) return `${m}분 ${r}초 남음`;
  return `${m}분 남음`;
}

export function fmtCountdown(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  if (h >= 24) return `${Math.floor(h / 24)}일 ${h % 24}시간`;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  return `${m}:${String(r).padStart(2, "0")}`;
}
