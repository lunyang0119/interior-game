/** 🛠 admin panel: flow controls on top (pause/resume/extend/resolve-now), presets, then the dangerous buttons set
 *  apart with an inline two-step confirm, and the tunables folded away. Bound to GET/PUT /api/train/config. */

import { api, msgFor, type ConfigResponse } from "../api";
import { tbus, toast } from "../bus";
import { isAdmin, isOver, tstate } from "../state";
import { $, button, el, setRich, show } from "./dom";

let cfg: ConfigResponse | null = null;
let tuneOpen = false;
let cfgGame: number | null = null;

/** One-click playtest timings (runtime overrides only; data/train_config.json keeps the real defaults). */
const TEST_PRESET: Record<string, unknown> = { round_timer_sec: 120, vote_skip_after_sec: 30, fugitive_grace_sec: 30 };

export function initAdmin(): void {
  $("btn-admin-reload").onclick = () => void load();
  $("btn-admin-tune").onclick = () => { tuneOpen = !tuneOpen; show("admin-config", tuneOpen); show("btn-admin-reload", tuneOpen);
    $("btn-admin-tune").querySelector("span")!.textContent = tuneOpen ? "튠값 접기" : "튠값 펼치기"; if (tuneOpen && !cfg) void load(); };
  tbus.on("state:changed", render);
  render();
}

async function load(): Promise<void> {
  if (!isAdmin() || !tstate.payload || tstate.payload.status === "IDLE") return;
  try { cfg = await api.getConfig(); renderConfig(); } catch (e) { toast(msgFor(e)); }
}

/** `label` may carry `{icon}` tokens. */
function act(label: string, fn: () => Promise<unknown>, cls = ""): HTMLButtonElement {
  const b = button("", async () => { try { await fn(); } catch (e) { toast(msgFor(e), 4000); } }, cls);
  setRich(b, label);
  return b;
}

/** Dangerous action: first tap arms the button ("정말 종료 (3초)"), a second tap within 3 s fires; otherwise it reverts. */
function armed(label: string, confirmLabel: string, fn: () => Promise<unknown>): HTMLButtonElement {
  let timer: number | null = null;
  const b = button(label, async () => {
    if (timer === null) {
      b.textContent = confirmLabel;
      b.classList.add("armed");
      timer = window.setTimeout(() => { timer = null; b.textContent = label; b.classList.remove("armed"); }, 3000);
      return;
    }
    window.clearTimeout(timer); timer = null;
    b.textContent = label; b.classList.remove("armed");
    try { await fn(); } catch (e) { toast(msgFor(e), 4000); }
  }, "danger");
  return b;
}

function render(): void {
  const p = tstate.payload;
  const flow = $("admin-flow");
  const presets = $("admin-presets");
  const danger = $("admin-danger");
  flow.innerHTML = ""; presets.innerHTML = ""; danger.innerHTML = "";
  if (!isAdmin() || !p) return;
  if (p.game_id !== cfgGame) { cfgGame = p.game_id; cfg = null; $("admin-config").innerHTML = ""; }   // a new game: reload its config
  const st = p.status;
  // during the fugitive's grace the server moves the grace deadline by the same amount (F08)
  const grace = st === "ROUND_OPEN" && p.grace_until != null;
  const ext = (label: string, sec: number) => { const b = act(label, () => api.extend(sec)); if (grace) b.title = "유예 시간도 같이 늘어나요"; return b; };
  if (st === "ROUND_OPEN") flow.append(act("{pause} 일시정지", api.pause), ext("{clock} +10분", 600), ext("{clock} +1시간", 3600));
  else if (st === "PAUSED") flow.append(act("{play} 재개", api.resume), ext("{clock} +10분", 600), ext("{clock} +1시간", 3600));
  if (isOver(st)) {
    const on = !!p.route;
    flow.append(act(on ? "경로 공개 끄기" : "경로 공개 (모두에게)", () => api.reveal(!on), on ? "" : "primary"));
    flow.appendChild(el("div", "small muted", on ? "승무원·관전자 화면에 도주자의 라운드별 경로와 체포 지점이 그려져요" : "체포 후에만 켤 수 있어요. 켜면 도주자의 전체 경로가 모두에게 보여요"));
  }
  if (st !== "IDLE" && !isOver(st)) {
    presets.append(
      act("테스트 프리셋 (2분·투표 30초·유예 30초)", async () => { cfg = await api.setConfig(TEST_PRESET); toast("테스트 프리셋을 적용했어요. 다음 라운드부터 2분 타이머예요"); renderConfig(); }),
      act("기본값으로", async () => { cfg = await api.resetConfig(); toast("이 판의 덮어쓴 값을 모두 지웠어요"); renderConfig(); }),
    );
  }
  if (st === "ROUND_OPEN" || st === "PAUSED") danger.appendChild(armed("라운드 지금 정산", "정말 정산 (3초)", api.endRound));
  if (st !== "IDLE") danger.appendChild(armed("추적 종료", "정말 종료 (3초)", api.endGame));
  show("admin-danger", danger.children.length > 0);
  // the tunables are not rebuilt on state pushes (typed values would be lost): only after load / apply / preset
  if (tuneOpen && !cfg && st !== "IDLE") void load();
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
  box.appendChild(act("적용", async () => {
    if (!Object.keys(pending).length) { toast("바뀐 값이 없어요"); return; }
    cfg = await api.setConfig(pending);
    toast("설정을 반영했어요");
    renderConfig();
  }, "primary"));
  box.appendChild(el("div", "small muted", `맵 ${cfg.map_id} · 굵은 키 = 이 판에서 덮어쓴 값. 라운드 타이머·유예·투표 개방은 서버 정책, 나머지는 엔진 값이에요.`));
}
