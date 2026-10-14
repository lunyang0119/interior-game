/** Korean text of a round report (the bot's strings.py REPORT_* lines, minus Discord markdown). */

import type { Report, ReportEvent } from "./api";
import { DEVICE_KO } from "./strings";

export const SIGNAL_KO: Record<string, string> = { strong: "강", medium: "중", weak: "약", none: "없음", noise: "판독 불가" };
export const CAPTURE_HOW_KO: Record<string, string> = { search: "수색", swap: "문에서 조우", colocate: "같은 구역" };

export function eventLine(ev: ReportEvent, name: (uid: string) => string): string {
  const n = name(ev.uid);
  switch (ev.type) {
    case "door_locked": return `🚪 ${n}: 문이 잠겨 있다 (${ev.edge})`;
    case "dazed": return `☕ ${n}: 커피포트가 과부하로 터졌다. 증기에 휩싸여 다음 라운드 행동 불가`;
    case "search_steam": return `☕ ${n}: 증기 때문에 ${ev.room} 수색 실패`;
    case "search_empty": return `🔍 ${n}: ${ev.room} 수색 — 이상 없음`;
    case "scan": return `📶 ${n}: 침입자 신호가 ${DEVICE_KO[ev.device ?? ""] ?? ev.device} 계열 장치 근처에서 잡힌다`;
    case "scan_noise": return `📶 ${n}: 노이즈 — 판독 실패`;
    case "scan_busy": return `📶 ${n}: 채널 혼선 — 이번 라운드 추적 채널이 이미 사용 중`;
    case "contact_miss": return `💥 ${n}: ${ev.room} 에서 접촉! 그러나 신호가 손끝을 스쳐 빠져나갔다`;
    case "glimpse": return `👁 ${n}: ${ev.room} 에서 침입자 신호의 주인을 목격! 수색하지 않아 놓쳤다`;
    default: return `${n}: ${ev.type}`;
  }
}

/** Short bubble over a hunter after the walk (playback). */
export function resultBubble(result: string | null, action: string, device?: string): string | null {
  switch (result) {
    case "captured": return "체포!";
    case "search_empty": return "🔍 이상 없음";
    case "search_steam": return "☕ 수색 실패";
    case "dazed": return "☕ 증기…";
    case "scan_ok": return `📶 ${DEVICE_KO[device ?? ""] ?? "?"}`;
    case "scan_noise": return "📶 노이즈";
    case "scan_busy": return "📶 혼선";
    default: return action === "stay" ? null : null;
  }
}

export function reportLines(rep: Report, name: (uid: string) => string): string[] {
  const out: string[] = [];
  out.push(`📡 라운드 ${rep.round} 판독 결과`);
  if (rep.timed_out) out.push("⏱ 제출 시간 종료 — 미제출자는 대기 처리");
  if (rep.blackout) out.push("▒▒▒ 신호 소실 — 이번 라운드 판독 불가 ▒▒▒");
  out.push(`추적률 ${rep.bar} ${rep.trace}%`);
  out.push(rep.distance !== null && rep.distance !== undefined
    ? `신호 강도: ${SIGNAL_KO[rep.signal] ?? rep.signal} (거리 ${rep.distance})`
    : `신호 강도: ${SIGNAL_KO[rep.signal] ?? rep.signal}`);
  if (rep.signature) out.push(rep.signature === "ping" ? "⚠ 추적기 역탐지 시그니처 감지" : `⚠ ${DEVICE_KO[rep.signature] ?? rep.signature} 계열 장치에서 비정상 접근 감지`);
  if (rep.markers.length) out.push(`◎ 신호 감지: ${rep.markers.join(", ")}`);
  if (rep.locks.length) out.push(`⛔ 잠긴 문: ${rep.locks.join(", ")}`);
  for (const r of rep.steam) out.push(`☕ ${r} 에 증기가 가득하다`);
  for (const ev of rep.events) out.push(eventLine(ev, name));
  if (rep.traced) out.push("‼ 추적률 100% — 침입자 신호 실시간 추적 중");
  if (rep.frozen) out.push("‼ 침입자 신호가 한 지점에 고정되었다");
  if (rep.captured_by) out.push(`★ 체포: ${name(rep.captured_by)} (${CAPTURE_HOW_KO[rep.capture_how ?? ""] ?? rep.capture_how}, R${rep.round})`);
  return out;
}

export function fmtCountdown(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  if (h >= 24) return `${Math.floor(h / 24)}일 ${h % 24}시간`;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  return `${m}:${String(r).padStart(2, "0")}`;
}
