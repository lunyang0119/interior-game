/** ⓘ rules & actions panel, written for the web (not the Discord bot's HELP/TUTORIAL text): goal and endings, the four
 *  crew actions, capture rules, how to read the report, a quick-hack table (fugitive view only, with cost/trace/device
 *  from the payload config) and how rounds advance. Opens by itself the first time an account visits /train
 *  (localStorage flag), then from the ⓘ chip. */

import { api } from "../api";
import { tbus, toast } from "../bus";
import { isFugitive, tstate } from "../state";
import { DEVICE_KO, HACK_DESC, HACK_KO } from "../strings";
import { $, el, openPanel, richEl } from "./dom";

const KEY_SEEN = "train_help_seen";
/** hack key -> device class it needs (from the server's help text); null until fetched, {} if the fetch failed */
let hackDevices: Record<string, string | null> | null = null;

const GOAL: [string, string][] = [
  ["목표", "침입자 체포"],
  ["체포", "같은 방에 있어도 못 잡아요. '수색'을 사용하거나 침입자와 같은 복도를 지나가야 해요"],
  ["탈출", "신호가 동결되기 전에 못 잡으면 침입자가 열차를 빠져나가 침입자가 이겨요"],
];

const CREW_ACTIONS: [string, string][] = [
  ["이동", "옆 구역을 탭하고 확정해요. 문을 지나 그 구역으로 가요"],
  ["수색", "침입자가 있는 구역을 수색하면 체포예요"],
  ["추적", "이번 라운드 정산 뒤 침입자가 있는 구역의 장치 계열을 알아내요."],
  ["대기", "제자리에 있어요. 건너뛰기 투표로 넘어간 승무원도 대기로 처리돼요"],
];

const CAPTURE: [string, string][] = [
  ["수색", "침입자가 있는 구역을 수색하면 체포예요"],
  ["같은 문", "침입자와 같은 라운드에 같은 문을 지나면 체포예요. 마주 보고 엇갈려도, 같은 방향으로 뒤따라가도 똑같아요"],
  ["{camera} 목격", "수색 없이 침입자와 같은 구역에서 라운드를 마치면 그 구역이 공개될 뿐 체포는 아니에요. 은신·증기 중엔 목격되지 않아요"],
];

const TRACKER: [string, string][] = [
  ["추적률", "라운드마다 오르고 침입자가 퀵핵을 쓸수록 더 올라요"],
  ["경계도", "추적률이 오르면 올라가요. 높을수록 ◎ 표식이 더 최신 위치를 가리켜요 (1 = 2라운드 지연, 2 = 1라운드 지연, 3 = 실시간)"],
  ["동결·탈출", "추적률이 끝까지 차면 신호가 한 지점에 동결돼요. 동결되기 전에 잡지 못하면 침입자가 탈출해요"],
];

const READING: [string, string][] = [
  ["◎", "마지막으로 잡힌 신호 위치 또는 교란 미끼예요. 둘을 구별할 방법은 없어요"],
  ["신호 강도", "가장 가까운 승무원과 침입자의 거리예요. 강 = 바로 옆 / 중 = 몇 칸 안 / 약 = 멀리 / 판독 불가 = 광학 재부팅 퀵핵"],
  ["시그니처", "침입자가 퀵핵을 쓴 장치 계열(커튼·커피포트·조명·스피커)이 남아요. 핑을 쓰면 역탐지 시그니처가 남아요"],
  ["{close} 잠긴 문", "지난 라운드에 잠겨 있던 문이에요. 이번 라운드에도 잠길지는 정산 때 알 수 있어요"],
  ["{power} 증기", "증기가 찬 구역이에요. 거기서 라운드를 마친 승무원은 다음 라운드 행동 불가, 그 구역 수색도 실패해요"]
];

const FLOW: [string, string][] = [
  ["마감", "모두가 행동을 결정하면 자동적으로 다음 턴으로 넘어가요. 마감시간(1시간)까지 못 낸 사람은 대기로 처리돼요"],
  ["건너뛰기 투표", "미제출 승무원을 기다리기 어려우면 투표로 건너뛸 수 있어요. 건너뛴 사람은 자동으로 대기 상태가 돼요"],
  ["일시정지", "운영자가 일시정지하면 마감 시계가 멈췄다가 재개 때 이어져요"],
  ["확정", "마감 전엔 다른 행동을 골라 다시 확정하면 덮어써요"],
];

export function initHelp(): void {
  $("btn-help").onclick = () => void openHelp();
  // closing the help brings the lobby panel back (openPanel hid it)
  $("panel-help").querySelector("[data-close]")?.addEventListener("click", () => tbus.emit("state:changed", {}));
  let seen = false;
  try { seen = localStorage.getItem(KEY_SEEN) === "1"; } catch { /* ignore */ }
  if (!seen) {
    const off = tbus.on("state:changed", () => { off(); void openHelp(); });
  }
}

export async function openHelp(): Promise<void> {
  try { localStorage.setItem(KEY_SEEN, "1"); } catch { /* ignore */ }
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
  section("추적률·경계도", TRACKER);
  section("행동", CREW_ACTIONS);
  section("체포 조건", CAPTURE);
  section("보고 읽는 법", READING);

  if (isFugitive() && p?.hacks) {
    box.appendChild(el("div", "panel-sub", "퀵핵 (도주자)"));
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
