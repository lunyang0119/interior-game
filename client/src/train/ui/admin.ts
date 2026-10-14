/** 🛠 admin panel (fugitive only): flow controls + the tunables bound to GET/PUT /api/train/config. */

import { api, msgFor, type ConfigResponse } from "../api";
import { tbus, toast } from "../bus";
import { isAdmin, tstate } from "../state";
import { $, button, el } from "./dom";

let cfg: ConfigResponse | null = null;

/** One-click playtest timings (runtime overrides only; data/train_config.json keeps the real defaults). */
const TEST_PRESET: Record<string, unknown> = { round_timer_sec: 120, vote_skip_after_sec: 30, fugitive_grace_sec: 30 };

export function initAdmin(): void {
  $("btn-admin-reload").onclick = () => void load();
  tbus.on("state:changed", render);
  render();
}

async function load(): Promise<void> {
  if (!isAdmin() || !tstate.payload || tstate.payload.status === "IDLE") return;
  try { cfg = await api.getConfig(); renderConfig(); } catch (e) { toast(msgFor(e)); }
}

function act(label: string, fn: () => Promise<unknown>, cls = ""): HTMLButtonElement {
  return button(label, async () => { try { await fn(); } catch (e) { toast(msgFor(e), 4000); } }, cls);
}

function render(): void {
  const p = tstate.payload;
  const flow = $("admin-flow");
  flow.innerHTML = "";
  if (!isAdmin() || !p) return;
  const st = p.status;
  if (st === "ROUND_OPEN") {
    flow.append(act("⏸ 일시정지", api.pause), act("+10분", () => api.extend(600)), act("+1시간", () => api.extend(3600)),
      act("라운드 지금 정산", () => confirm("미제출자는 대기로 처리돼요. 지금 정산할까요?") ? api.endRound() : Promise.resolve(), "danger"));
  } else if (st === "PAUSED") {
    flow.append(act("▶ 재개", api.resume), act("+10분", () => api.extend(600)), act("+1시간", () => api.extend(3600)));
  }
  if (st !== "IDLE") flow.append(act("추적 종료", () => confirm("이 추적을 끝낼까요?") ? api.endGame() : Promise.resolve(), "danger"));
  if (!cfg && st !== "IDLE") void load(); else renderConfig();
}

function renderConfig(): void {
  const box = $("admin-config");
  box.innerHTML = "";
  if (!cfg) return;
  const keys = Object.keys(cfg.defaults).filter((k) => !["render_mode", "hunter_colors"].includes(k));
  const pending: Record<string, string> = {};
  for (const k of keys) {
    const row = el("div", "cfg-row");
    const lab = el("label", "", k);
    if (k in cfg.overrides) lab.classList.add("overridden");
    const inp = el("input");
    inp.value = String(cfg.config[k]);
    inp.placeholder = String(cfg.defaults[k]);
    inp.onchange = () => { pending[k] = inp.value; };
    row.append(lab, inp);
    box.appendChild(row);
  }
  const apply = act("적용", async () => {
    if (!Object.keys(pending).length) { toast("바뀐 값이 없어요"); return; }
    cfg = await api.setConfig(pending);
    toast("설정을 반영했어요");
    renderConfig();
  }, "primary");
  const presets = el("div", "row");
  presets.append(
    act("테스트 프리셋 (2분·투표 30초·유예 30초)", async () => {
      cfg = await api.setConfig(TEST_PRESET);
      toast("테스트 프리셋을 적용했어요. 다음 라운드부터 2분 타이머예요");
      renderConfig();
    }),
    act("기본값으로", async () => {
      cfg = await api.resetConfig();
      toast("이 판의 덮어쓴 값을 모두 지웠어요");
      renderConfig();
    }),
  );
  box.appendChild(apply);
  box.appendChild(presets);
  box.appendChild(el("div", "small muted", `맵 ${cfg.map_id} · 굵은 키 = 이 판에서 덮어쓴 값. 라운드 타이머·유예·투표 개방은 서버 정책, 나머지는 엔진 값이에요.`));
}
