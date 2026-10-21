/** Korean text of a round report (the bot's strings.py REPORT_* lines, minus Discord markdown), plus the tracker
 *  arithmetic the UI explains with: marker age by trace tier, candidate rooms from the public clues, and the
 *  rounds left before the intruder escapes. */

import type { Hack, MapRow, PlaybackHunter, Report, ReportEvent, TrainState } from "./api";
import { distances } from "./graph";
import { DEVICE_KO, HACK_KO, ORDER_KO } from "./strings";

export const SIGNAL_KO: Record<string, string> = { strong: "강", medium: "중", weak: "약", none: "없음", noise: "판독 불가" };
export const CAPTURE_HOW_KO: Record<string, string> = { search: "수색", swap: "같은 문 통과", colocate: "같은 구역" };
/** device signature → the quickhack bound to it (strings.py HACK_DEVICE; the help panel shows the same table) */
const HACK_OF_DEVICE: Record<string, Hack> = { speaker: "distract", light: "blackout", curtain: "hide", coffeepot: "overload" };
/** how long the quickhack notice stays on screen while a round plays back */
export const HACK_NOTICE_MS = 6500;

// ---------------------------------------------------------------------------
// tracker arithmetic (engine resolve_round step 7 / the safety freeze, mirrored for display only)
// ---------------------------------------------------------------------------

/** How old the ◎ marker is at `tier` (engine lag {0: none, 1: 2, 2: 1, 3: 0}; a frozen signal is live). */
export function markerLag(tier: number, frozen = false): number | null {
  if (frozen) return 0;
  return [null, 2, 1, 0][Math.max(0, Math.min(3, tier))] ?? null;
}

/** "표식 없음" / "◎ 2라운드 전 위치" / "◎ 지금 위치": what the marker means at this tier. */
export function markerAge(tier: number, frozen = false): string {
  const lag = markerLag(tier, frozen);
  if (lag === null) return "표식 없음";
  return lag === 0 ? "◎ 지금 위치" : `◎ ${lag}라운드 전 위치`;
}

/** The caption under a ◎ on the map ("2라운드 전 위치" / "지금 위치"); null below the first tier, where a marker
 *  can only be a decoy and must not claim an age. */
export function markerCaption(tier: number, frozen = false): string | null {
  const lag = markerLag(tier, frozen);
  if (lag === null) return null;
  return lag === 0 ? "지금 위치" : `${lag}라운드 전 위치`;
}

/** One-word stage of the tracker for the gauge. */
export function traceStage(tier: number, frozen = false): string {
  if (frozen) return "신호 고정";
  return ["조용함", "흔적 희미", "흔적 선명", "실시간 추적"][Math.max(0, Math.min(3, tier))];
}

/** The trace tier of a trace value under the payload's thresholds (engine trace_tier). */
export function tierOf(trace: number, cfg: Record<string, unknown> | undefined): number {
  const t1 = Number(cfg?.trace_t1 ?? 40), t2 = Number(cfg?.trace_t2 ?? 70), t3 = Number(cfg?.trace_t3 ?? 100);
  return trace >= t3 ? 3 : trace >= t2 ? 2 : trace >= t1 ? 1 : 0;
}

/** Rounds the crew still has (this round included) before the intruder escapes: the hard cap `max_rounds`, and
 *  once the trace hit 100 % the `overheat_rounds` countdown. null when the payload cannot tell. */
export function roundsLeft(p: TrainState): { left: number; traced: boolean } | null {
  const cfg = p.config ?? {};
  const max = Number(cfg.max_rounds ?? 0);
  const overheat = Number(cfg.overheat_rounds ?? 0);
  const done = Math.max(0, (p.round_no ?? 1) - 1);   // rounds already resolved
  let left = max > 0 ? max - done : Infinity;
  const traced = p.traced_round != null;
  if (traced && overheat > 0) left = Math.min(left, overheat - (done - p.traced_round!));
  if (!Number.isFinite(left)) return null;
  return { left: Math.max(0, left), traced };
}

export interface Clues {
  /** rooms the intruder can be in after the round, given the public clues (empty = nothing to go on) */
  rooms: string[];
  /** the clues used, in words ("신호 중", "장치 조명", "목격") */
  from: string[];
}

/** Where the intruder can be after `rep`, from the public report only: a glimpse pins the room; else the signal
 *  band (min distance from the crew's end-of-round rooms) and, when the scan reads the room after the move
 *  (scan_lag 0), the scanned device class. Blackout / signal off → null. */
export function candidates(rep: Report, rows: MapRow[], cfg: Record<string, unknown> | undefined): Clues | null {
  const glimpse = rep.events.find((e) => e.type === "glimpse" && e.room);
  if (glimpse) return { rooms: [glimpse.room!], from: ["목격"] };
  if (rep.blackout || rep.signal === "noise" || rep.signal === "none" || !rows.length) return null;
  const [a, b] = String(cfg?.signal_bands ?? "1,3").split(",").map((x) => Number(x));
  const crew = [...new Set(Object.values(rep.hunters).map((h) => h.room))];
  if (!crew.length) return null;
  const near = new Map<string, number>();
  for (const room of crew) for (const [r, d] of distances(rows, room)) near.set(r, Math.min(near.get(r) ?? Infinity, d));
  const inBand = (d: number) => rep.signal === "strong" ? d <= a : rep.signal === "medium" ? d > a && d <= b : d > b;
  let rooms = rows.map((r) => r.room).filter((r) => inBand(near.get(r) ?? Infinity));
  const from = [`신호 ${SIGNAL_KO[rep.signal] ?? rep.signal}`];
  if (Number(cfg?.scan_lag ?? 1) === 0) {
    const devices = [...new Set(rep.events.filter((e) => e.type === "scan" && e.device).map((e) => e.device!))];
    for (const dev of devices) {
      const ofDev = new Set(rows.filter((r) => r.device === dev).map((r) => r.room));
      rooms = rooms.filter((r) => ofDev.has(r));
      from.push(`장치 ${DEVICE_KO[dev] ?? dev}`);
    }
  }
  return { rooms, from };
}

/** "{search} 후보 구역 3곳: A1 · B2 · C1 (신호 중 · 장치 조명)" for a round card / headline; null without clues. */
export function candidateLine(rep: Report, rows: MapRow[], cfg: Record<string, unknown> | undefined): string | null {
  const c = candidates(rep, rows, cfg);
  if (!c) return null;
  if (!c.rooms.length) return `{search} 후보 구역 없음 (${c.from.join(" · ")})`;
  return `{search} 후보 구역 ${c.rooms.length}곳: ${c.rooms.join(" · ")} (${c.from.join(" · ")})`;
}

// ---------------------------------------------------------------------------
// report text
// ---------------------------------------------------------------------------

/** The quickhack notice for a round: what the intruder did and where, as far as this client may know.
 *  The crew gets public facts only (locked doors, steam rooms, the blackout, the device signature);
 *  the intruder sees their own order and whether it actually fired (the engine voids a hack it can no longer pay for). */
export function hackNotice(rep: Report, fugitiveView: boolean): string | null {
  if (fugitiveView && rep.fugitive_order !== undefined) {
    const o = rep.fugitive_order;
    const hidden = rep.hidden_events ?? [];
    const voided = hidden.find((s) => /^퀵핵 .* 무효: /.test(s));
    const stopped = hidden.find((s) => /앞에서 정지/.test(s));
    const parts: string[] = [];
    if (o?.hack) {
      parts.push(voided
        ? `{alert} 퀵핵 무효 · ${voided.replace(/^퀵핵 \S+ 무효: /, "")}`
        : `{target} 퀵핵 실행 · ${HACK_KO[o.hack] ?? o.hack}${o.target ? ` (${o.target})` : ""}`);
    }
    if (stopped) parts.push(`{exit} ${stopped}`);
    return parts.length ? parts.join(" · ") : null;
  }
  const parts: string[] = [];
  if (rep.locks.length) parts.push(`{exit} 문 잠금: ${rep.locks.join(", ")}`);
  if (rep.steam.length) parts.push(`{power} 과부하: ${rep.steam.join(", ")}에 증기`);
  if (rep.blackout) parts.push("▒ 광학 재부팅: 이번 라운드 탐색기 판독 불가");
  if (rep.signature === "ping") parts.push("{signal} 핑: 침입자가 승무원 행동을 들여다봤어요");
  else if (rep.signature) {
    const hk = HACK_OF_DEVICE[rep.signature];
    const dev = DEVICE_KO[rep.signature] ?? rep.signature;
    if (hk === "distract") parts.push(`{speaker} 교란: ${dev} 장치 비정상 접근 · 가짜 표식이 섞여 있어요 (진짜와 겹치면 하나로 보여요)`);
    else if (hk === "hide") parts.push(`{target} 은신: ${dev} 장치 비정상 접근 · 침입자가 몸을 숨겼어요`);
    else if (!(hk === "blackout" && rep.blackout) && !(hk === "overload" && rep.steam.length)) parts.push(`{alert} ${dev} 계열 장치에서 비정상 접근 감지`);
  }
  return parts.length ? `퀵핵 감지 · ${parts.join(" · ")}` : null;
}

export function eventLine(ev: ReportEvent, name: (uid: string) => string): string {
  const n = name(ev.uid);
  switch (ev.type) {
    case "door_locked": return `{exit} ${n}: 문이 잠겨 있다 (${ev.edge})`;
    case "dazed": return `{power} ${n}: 커피포트가 과부하로 터졌다. 증기에 휩싸여 다음 라운드 행동 불가`;
    case "search_steam": return `{power} ${n}: 증기 때문에 ${ev.room} 수색 실패`;
    case "search_empty": return `{search} ${n}: ${ev.room} 수색 — 이상 없음`;
    case "scan": return `{signal} ${n}: 신호 탐색 · 침입자가 있는 구역의 장치는 ${DEVICE_KO[ev.device ?? ""] ?? ev.device} 계열`;
    case "scan_noise": return `{signal} ${n}: 노이즈 — 판독 실패`;
    case "scan_busy": return `{signal} ${n}: 채널 혼선 — 이번 라운드 탐색 채널이 이미 사용 중`;
    case "contact_miss": return `{alert} ${n}: ${ev.room} 에서 접촉! 그러나 신호가 손끝을 스쳐 빠져나갔다`;
    case "glimpse": return `{camera} ${n}: ${ev.room} 에서 침입자를 목격! 수색하지 않아 놓쳤다`;
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
    case "scan_ok": return `탐색: ${DEVICE_KO[device ?? ""] ?? "?"}`;
    case "scan_noise": return "노이즈";
    case "scan_busy": return "혼선";
    default: return null;
  }
}

/** "이동 → B2" / "수색 (A1)" / "신호 탐색" / "대기": what a crew member did this round (round card, crew list). */
export function actionText(h: PlaybackHunter): string {
  if (h.action === "move") return `이동 → ${h.to}`;
  if (h.action === "search") return `수색 (${h.from})`;
  return ORDER_KO[h.action] ?? h.action;
}

/** What came of it, in words (DOM text, may carry `{icon}` tokens). `rows` adds the rooms a scanned device class
 *  can mean ("조명 계열 (A1 · C2 중 한 곳)"). */
export function resultText(h: PlaybackHunter, rep: Report, rows: MapRow[] = []): string {
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
      const rooms = rows.filter((r) => r.device === dev).map((r) => r.room).sort();
      const where = rooms.length ? ` (${rooms.join(" · ")} 중 한 곳)` : "";
      return `{signal} ${DEVICE_KO[dev ?? ""] ?? dev ?? "?"} 계열${where}${extra}`;
    }
    case "scan_noise": return `{signal} 노이즈 (판독 실패)${extra}`;
    case "scan_busy": return `{signal} 혼선 (탐색 채널이 이미 다 쓰임)${extra}`;
  }
  if (glimpse) return extra.slice(3);
  return h.action === "move" ? "도착" : "–";
}

/** The round's public headline: trace + marker age, signal, markers, locked doors, steam. */
export function headline(rep: Report): string[] {
  const out = [`{target} 추적률 ${rep.trace}% · ${markerAge(rep.tier, rep.frozen)}`];
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
  out.push(`{signal} 라운드 ${rep.round} 결과`);
  if (rep.timed_out) out.push("{clock} 제출 시간 종료 · 미제출자는 대기 처리");
  if (rep.blackout) out.push("▒▒▒ 신호 소실 — 이번 라운드 판독 불가 ▒▒▒");
  out.push(`추적률 ${rep.bar} ${rep.trace}% · ${markerAge(rep.tier, rep.frozen)}`);
  out.push(rep.distance !== null && rep.distance !== undefined
    ? `신호 강도: ${SIGNAL_KO[rep.signal] ?? rep.signal} (거리 ${rep.distance})`
    : `신호 강도: ${SIGNAL_KO[rep.signal] ?? rep.signal}`);
  if (rep.signature) out.push(rep.signature === "ping" ? "{alert} 핑 흔적 감지 (침입자가 승무원 행동을 봤다)" : `{alert} ${DEVICE_KO[rep.signature] ?? rep.signature} 계열 장치에서 비정상 접근 감지`);
  if (rep.markers.length) out.push(`◎ 신호 감지: ${rep.markers.join(", ")}`);
  if (rep.locks.length) out.push(`{close} 잠긴 문: ${rep.locks.join(", ")}`);
  for (const r of rep.steam) out.push(`{power} ${r} 에 증기가 가득하다`);
  // the intruder's own log entry: the order as submitted and the engine's hidden notes
  if (rep.fugitive_order !== undefined) {
    const o = rep.fugitive_order;
    out.push(`{target} 내 행동: ${o?.move ? `이동 → ${o.move}` : "제자리"}${o?.hack ? ` + ${HACK_KO[o.hack] ?? o.hack}${o.target ? ` (${o.target})` : ""}` : ""}`);
    for (const s of rep.hidden_events ?? []) out.push(`{target} ${s}`);
  }
  for (const ev of rep.events) out.push(eventLine(ev, name));
  if (rep.traced) out.push("{alert} 추적률 100% — 침입자 위치가 실시간으로 보인다. 탈출 카운트다운 시작");
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
