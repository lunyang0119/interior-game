/** ⓘ rules & actions panel: the bot's TUTORIAL/HELP (server /api/train/help) reflowed for the web, a per-action
 *  reference (hunters: move/search/scan/stay; fugitive view: hacks with cost/trace/device), and the tracker legend.
 *  Opens by itself the first time an account visits /train (localStorage flag), then from the ⓘ chip. */

import { api, type HelpText } from "../api";
import { tbus, toast } from "../bus";
import { isFugitive, tstate } from "../state";
import { DEVICE_KO, HACK_KO } from "../strings";
import { $, el, openPanel } from "./dom";

const KEY_SEEN = "train_help_seen";
let text: HelpText | null = null;

export const LEGEND: [string, string][] = [
  ["◎", "마지막으로 잡힌 신호 위치 또는 교란 미끼. 둘을 구별할 방법은 없어요"],
  ["⛔", "지난 라운드에 잠겨 있던 문. 이번 라운드에도 잠길지는 정산 때 알 수 있어요"],
  ["☕", "증기가 찬 구역. 들어가면 다음 라운드 행동 불가, 수색도 실패해요"],
  ["👁 목격", "침입자와 같은 구역에서 라운드를 마치면 그 구역이 공개돼요. 체포는 아니에요 (은신·증기 중엔 목격 안 됨)"],
  ["신호 강도", "가장 가까운 승무원과 침입자의 거리. 강 = 바로 옆까지, 중 = 몇 칸 안, 약 = 멀리, 판독 불가 = 광학 재부팅"],
  ["시그니처", "침입자가 퀵핵을 쓴 장치 계열(커튼·커피포트·조명·스피커). 역탐지 = 핑을 썼다는 뜻"],
  ["추적률", "라운드마다 오르고 퀵핵을 쓸수록 더 올라요. 티어가 오르면 ◎ 표식이 더 최신 위치를 가리켜요 (T1 2라운드 지연 → T2 1라운드 → T3 실시간)"],
  ["행동 불가", "증기에 휩싸인 승무원은 그 라운드에 아무것도 못 해요. 제출 현황에서는 자동으로 '완료'로 쳐요"],
];

/** Strip the Discord command lines and turn `/이동 구역:B2` into the web wording. */
function reflow(s: string): string[] {
  return s.split("\n")
    .filter((l) => !/^##/.test(l) && !/라운드 메시지의 버튼|현황판이 위로 밀려나면|현황판 읽는 법/.test(l))
    .map((l) => l.replace(/`\/이동 구역:B2`/, "이동 (옆 구역 탭)").replace(/`\/수색`/, "수색 (내 구역 탭)").replace(/`\/추적`/, "추적").replace(/`\/대기`/, "대기")
      .replace(/\*\*/g, "").replace(/`/g, "").replace(/^• /, "· ").trim())
    .filter(Boolean);
}

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
  if (!text) {
    try { text = await api.help(); } catch (e) { toast("도움말을 불러오지 못했어요"); return; }
  }
  const box = $("help-body");
  box.innerHTML = "";
  const p = tstate.payload;
  box.appendChild(el("div", "panel-sub", "규칙"));
  for (const l of reflow(text.help)) box.appendChild(el("div", "small", l));
  box.appendChild(el("div", "panel-sub", "조작"));
  for (const l of reflow(text.tutorial)) box.appendChild(el("div", "small", l));

  box.appendChild(el("div", "panel-sub", "행동"));
  const scan = p?.config?.scan_budget ?? "?";
  const acts: [string, string][] = [
    ["이동", "옆 구역을 탭 → 확정. 문을 엇갈려 지나면 체포"],
    ["수색", "내 구역을 탭(또는 버튼) → 확정. 같은 구역에 있으면 체포, 은신 중이어도"],
    ["추적", `침입자 구역의 장치 계열을 알아내요. 라운드당 ${scan}명만, 겹치면 혼선`],
    ["대기", "제자리. 투표로 건너뛰어진 승무원도 대기로 처리돼요"],
  ];
  for (const [k, v] of acts) box.appendChild(row(k, v));
  if (isFugitive() && p?.hacks) {
    box.appendChild(el("div", "panel-sub", "퀵핵 (도주자)"));
    for (const [hk, info] of Object.entries(p.hacks)) {
      const dev = text.hack_devices?.[hk];
      box.appendChild(row(HACK_KO[hk] ?? hk, `RAM ${info.cost} · 추적률 +${info.trace}${dev ? ` · ${DEVICE_KO[dev] ?? dev} 장치 구역에서만` : ""}`));
    }
  }
  box.appendChild(el("div", "panel-sub", "표식·용어"));
  for (const [k, v] of LEGEND) box.appendChild(row(k, v));
  openPanel("panel-help");
}

function row(k: string, v: string): HTMLElement {
  const r = el("div", "help-row");
  r.append(el("b", "", k), el("span", "small", v));
  return r;
}
