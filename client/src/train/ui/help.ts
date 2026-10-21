/** ⓘ rules & actions panel, written for the web (not the Discord bot's HELP/TUTORIAL text): goal and endings, the four
 *  crew actions, capture rules, how to read the tracker, a quick-hack table (intruder view only, with cost/trace/device
 *  from the payload config) and how rounds advance. The first-round intro card (ui/intro.ts) covers the basics; this
 *  panel opens only from the 도움말 chip. */

import { api } from "../api";
import { tbus, toast } from "../bus";
import { isFugitive, tstate } from "../state";
import { DEVICE_KO, HACK_DESC, HACK_KO, ORDER_DESC } from "../strings";
import { $, el, openPanel, richEl } from "./dom";

/** hack key -> device class it needs (from the server's help text); null until fetched, {} if the fetch failed */
let hackDevices: Record<string, string | null> | null = null;

const GOAL: [string, string][] = [
  ["숨바꼭질", "침입자 한 명이 열차 어딘가에 숨어요. 승무원은 매 라운드 한 가지 행동으로 침입자를 찾아 체포해요"],
  ["체포", "같은 구역에 있어도 못 잡아요. 그 구역을 '수색'하거나, 침입자와 같은 라운드에 같은 문을 지나야 해요"],
  ["탈출", "정해진 라운드 안에 못 잡으면 침입자가 열차를 빠져나가요. 추적률이 100%가 되면 짧은 카운트다운이 따로 시작돼요"],
];

const CREW_ACTIONS: [string, string][] = [
  ["이동", `${ORDER_DESC.move}. 문을 지나 그 구역으로 가요`],
  ["수색", ORDER_DESC.search],
  ["신호 탐색", `${ORDER_DESC.scan}. 라운드당 쓸 수 있는 사람 수가 정해져 있어요`],
  ["대기", `${ORDER_DESC.stay}. 건너뛰기 투표로 넘어간 승무원도 대기로 처리돼요`],
];

const CAPTURE: [string, string][] = [
  ["수색", "침입자가 있는 구역을 수색하면 체포예요"],
  ["같은 문", "침입자와 같은 라운드에 같은 문을 지나면 체포예요. 마주 보고 엇갈려도, 같은 방향으로 뒤따라가도 똑같아요"],
  ["{camera} 목격", "수색 없이 침입자와 같은 구역에서 라운드를 마치면 그 구역이 공개될 뿐 체포는 아니에요. 은신·증기 중엔 목격되지 않아요"],
];

const TRACKER: [string, string][] = [
  ["추적률", "라운드마다 오르고 침입자가 퀵핵을 쓸수록 더 올라요. 높을수록 ◎ 표식이 더 최신 위치를 가리켜요 (흔적 희미 = 2라운드 전, 흔적 선명 = 1라운드 전, 실시간 = 지금 위치)"],
  ["◎ 표식", "표식 밑에 몇 라운드 전 위치인지 적혀 있어요. 교란 퀵핵이 띄운 가짜 표식과 구별할 방법은 없어요"],
  ["신호 강도", "가장 가까운 승무원과 침입자의 거리예요. 강 = 바로 옆 / 중 = 몇 칸 안 / 약 = 멀리 / 판독 불가 = 광학 재부팅 퀵핵"],
  ["후보 구역", "신호 강도와 신호 탐색 결과를 합쳐 침입자가 있을 수 있는 구역을 맵에 칠해요 (라운드 결과 카드에도 적혀요)"],
  ["퀵핵 흔적", "침입자가 퀵핵을 쓴 장치 계열(커튼·커피포트·조명·스피커)이 남아요. 핑을 쓰면 역탐지 흔적이 남아요"],
  ["{close} 잠긴 문", "지난 라운드에 잠겨 있던 문이에요. 이번 라운드에도 잠길지는 결과가 나와야 알 수 있어요"],
  ["{power} 증기", "증기가 찬 구역이에요. 거기서 라운드를 마친 승무원은 다음 라운드 행동 불가, 그 구역 수색도 실패해요"],
];

const FLOW: [string, string][] = [
  ["마감", "모두가 행동을 확정하면 바로 다음 라운드로 넘어가요. 마감 시간(1시간)까지 못 낸 사람은 대기로 처리돼요"],
  ["건너뛰기 투표", "미제출 승무원을 기다리기 어려우면 투표로 건너뛸 수 있어요. 건너뛴 사람은 자동으로 대기 상태가 돼요"],
  ["일시정지", "방장이 일시정지하면 마감 시계가 멈췄다가 재개 때 이어져요"],
  ["확정", "마감 전엔 다른 행동을 골라 다시 확정하면 덮어써요"],
];

export function initHelp(): void {
  $("btn-help").onclick = () => void openHelp();
  // closing the help brings the lobby panel back (openPanel hid it)
  $("panel-help").querySelector("[data-close]")?.addEventListener("click", () => tbus.emit("state:changed", {}));
}

export async function openHelp(): Promise<void> {
  if (!hackDevices && isFugitive()) {
    try { hackDevices = (await api.help()).hack_devices ?? {}; } catch { hackDevices = {}; toast("퀵핵 장치 정보를 불러오지 못했어요"); }
  }
  const box = $("help-body");
  box.innerHTML = "";
  const p = tstate.payload;
  const section = (title: string, rows: [string, string][]) => {
    box.appendChild(el("div", "panel-sub", title));
    for (const [k, v] of rows) box.appendChild(row(k, v));
  };

  section("목표", GOAL);
  section("행동", CREW_ACTIONS);
  section("체포 조건", CAPTURE);
  section("추적기 읽는 법", TRACKER);

  if (isFugitive() && p?.hacks) {
    box.appendChild(el("div", "panel-sub", "퀵핵 (침입자)"));
    for (const [hk, info] of Object.entries(p.hacks)) {
      const dev = hackDevices?.[hk];
      const meta = `RAM ${info.cost} · 추적률 +${info.trace}${dev ? ` · ${DEVICE_KO[dev] ?? dev} 장치 구역에서만` : ""}`;
      box.appendChild(row(HACK_KO[hk] ?? hk, `${HACK_DESC[hk] ?? ""} (${meta})`.trim()));
    }
  }

  section("진행", FLOW);
  openPanel("panel-help");
}

function row(k: string, v: string): HTMLElement {
  const r = el("div", "help-row");
  r.append(richEl("b", "", k), richEl("span", "small", v));
  return r;
}
