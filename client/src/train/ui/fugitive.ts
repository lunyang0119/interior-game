/** Fugitive bar: RAM/trace, move pick (tap a reachable room), quickhack pick (+ door/room target), ping, confirm. */

import { api, msgFor, type Hack } from "../api";
import { tbus, toast } from "../bus";
import { describeFugitiveOrder, isFugitive, tstate } from "../state";
import { HACK_KO, ORDER_KO } from "../strings";
import { $, el, show } from "./dom";

const HACKS: Hack[] = ["doorlock", "distract", "blackout", "hide", "overload"];

export function initFugitiveBar(): void {
  $("btn-fug-confirm").onclick = () => void confirmOrder();
  $("btn-fug-cancel").onclick = () => void cancelOrder();
  $("btn-fug-ping").onclick = () => void ping();
  $("btn-fug-clear").onclick = () => { tstate.fpick = { move: null, hack: null, target: null }; changed(); };
  tbus.on("room:tap", ({ room, door }) => {
    const p = tstate.payload;
    if (!isFugitive() || !p || p.fugitive_ai || p.status !== "ROUND_OPEN" || !p.fugitive || tstate.phase === "playback") return;
    const f = tstate.fpick;
    if (f.hack === "doorlock" && door) {
      if ((p.lockable_edges ?? []).includes(door)) { f.target = door; changed(); } else toast("여기서는 잠글 수 없는 문이에요", 1500);
      return;
    }
    if (!room) return;
    if (f.hack === "distract") { f.target = room; changed(); return; }
    if (room === p.fugitive.room) { f.move = null; changed(); return; }
    if ((p.reachable ?? []).includes(room)) { f.move = room; changed(); } else toast("한 라운드에 갈 수 없는 구역이에요", 1500);
  });
  tbus.on("state:changed", render);
  render();
}

function changed(): void {
  tbus.emit("pick:changed", {});
  render();
}

async function confirmOrder(): Promise<void> {
  const f = tstate.fpick;
  if (f.hack === "doorlock" && !f.target) { toast("잠글 문을 눌러 주세요"); return; }
  if (f.hack === "distract" && !f.target) { toast("교란할 구역을 눌러 주세요"); return; }
  try {
    const r = await api.fugitiveOrder({ move: f.move, hack: f.hack, target: f.hack ? f.target : null });
    toast(r.resolved ? "전원 제출 완료 — 정산해요" : `명령 접수: ${describeFugitiveOrder(r.order)}`);
  } catch (e) {
    toast(msgFor(e), 4000);
  }
}

async function cancelOrder(): Promise<void> {
  try { await api.cancelFugitiveOrder(); toast("제출을 취소했어요"); } catch (e) { toast(msgFor(e)); }
}

async function ping(): Promise<void> {
  try {
    const r = await api.ping();
    tstate.pingOrders = r.orders;
    const lines = Object.entries(r.orders).map(([id, o]) => `${id}: ${o ? (o.type === "move" ? `이동 → ${o.target}` : ORDER_KO[o.type]) : "미제출"}`);
    toast(`📡 핑 — ${lines.join(" · ")}`, 6000);
    render();
  } catch (e) {
    toast(msgFor(e), 4000);
  }
}

function render(): void {
  const p = tstate.payload;
  const on = isFugitive() && !!p && !p.fugitive_ai && p.status === "ROUND_OPEN" && !!p.fugitive && tstate.phase !== "playback";
  show("fugbar", on);
  if (!on || !p?.fugitive) return;
  const f = p.fugitive;
  const ramMax = Number(p.config?.ram_max ?? 10);
  $("fug-ram").textContent = `RAM ${"▮".repeat(Math.max(0, f.ram))}${"▯".repeat(Math.max(0, ramMax - f.ram))} ${f.ram}/${ramMax}`;
  $("fug-trace").textContent = `추적률 ${f.trace}% · 경계도 ${f.tier}${f.frozen ? " · 동결" : ""}${f.hacks_disabled ? " · 덱 봉인" : ""}${f.hidden_until >= (p.round_no ?? 0) ? " · 은신 중" : ""}`;
  const status = $("fug-status");
  const submitted = !!f.order;
  show("btn-fug-cancel", submitted);
  $("btn-fug-confirm-val").textContent = submitted ? "바꾼 행동으로 확정" : "이번 라운드 행동 확정";
  const pickText = `${describeFugitiveOrder(tstate.fpick)}${tstate.fpick.hack === "doorlock" && !tstate.fpick.target ? " — 잠글 문을 눌러요" : ""}${tstate.fpick.hack === "distract" && !tstate.fpick.target ? " — 교란할 구역을 눌러요" : ""}`;
  status.textContent = submitted
    ? `✅ ${describeFugitiveOrder(f.order)} · 바꾸기: ${pickText}`
    : `${f.room}에 있어요 · ${pickText}`;

  const hacks = $("fug-hacks");
  hacks.innerHTML = "";
  for (const hk of HACKS) {
    const info = p.hacks?.[hk];
    const b = el("button", "chip" + (tstate.fpick.hack === hk ? " active" : ""), `${HACK_KO[hk]} ${info ? `(${info.cost})` : ""}`);
    if (info && !info.ok) { b.classList.add("off"); b.title = info.why; b.appendChild(el("span", "fug-why", shortWhy(info.why))); }
    b.onclick = () => {
      if (info && !info.ok) { toast(info.why, 4000); return; }
      tstate.fpick.hack = tstate.fpick.hack === hk ? null : hk;
      tstate.fpick.target = null;
      changed();
    };
    hacks.appendChild(b);
  }
  const pingInfo = p.hacks?.ping;
  const pingBtn = $<HTMLButtonElement>("btn-fug-ping");
  $("btn-fug-ping-val").textContent = `핑 (${pingInfo?.cost ?? "?"})${pingInfo && !pingInfo.ok && !f.pinged ? ` · ${shortWhy(pingInfo.why)}` : ""}`;
  pingBtn.disabled = f.pinged || !(pingInfo?.ok ?? false);
  pingBtn.title = f.pinged ? "이번 라운드에 이미 핑을 썼어요" : (pingInfo?.why ?? "");
  $("fug-projection").textContent = projection(p, tstate.fpick.hack, f.pinged);
}

/** The engine's reason, shortened for a button: "RAM 부족 (1/3)" → "RAM 부족 (3 필요)", device rule → "이 방엔 X 없음". */
function shortWhy(why: string): string {
  const ram = why.match(/RAM 부족 \((\d+)\/(\d+)\)/);
  if (ram) return `RAM 부족 (${ram[2]} 필요)`;
  const dev = why.match(/(커튼|커피포트|조명|스피커) 장치가 있는 구역에서만/);
  if (dev) return `이 방엔 ${dev[1]} 없음`;
  if (/봉인/.test(why)) return "핵 봉인됨";
  if (/비활성/.test(why)) return "꺼져 있음";
  return why;
}

/** "추적률 48 → 63 · 다음 라운드 티어 2 (표식 1라운드 지연)" for the selected hack (and this round's ping). */
function projection(p: NonNullable<typeof tstate.payload>, hack: Hack | null, pinged: boolean): string {
  const f = p.fugitive;
  const c = p.config ?? {};
  if (!f) return "";
  const passive = Number(c.trace_passive ?? 0);
  const t = [Number(c.trace_t1 ?? 40), Number(c.trace_t2 ?? 70), Number(c.trace_t3 ?? 100)];
  const add = (hack ? Number(p.hacks?.[hack]?.trace ?? 0) : 0) + (pinged ? 0 : 0);
  if (!hack && !pinged) return "";
  const next = Math.min(100, f.trace + add + passive);
  const tier = next >= t[2] ? 3 : next >= t[1] ? 2 : next >= t[0] ? 1 : 0;
  const lag = ["표식 없음", "표식 2라운드 지연", "표식 1라운드 지연", "표식 실시간"][tier];
  const parts = [];
  if (hack) parts.push(`${HACK_KO[hack]} +${Number(p.hacks?.[hack]?.trace ?? 0)}`);
  if (pinged) parts.push("핑 반영됨");
  parts.push(`기본 +${passive}`);
  return `추적률 ${f.trace} → ${next} (${parts.join(", ")}) · 다음 라운드 경계도 ${tier} (${lag})`;
}
