/** Fugitive bar: RAM/trace, move pick (tap a reachable room), quickhack pick (+ door/room target), ping, confirm. */

import { api, msgFor, type Hack, type MapRow } from "../api";
import { tbus, toast } from "../bus";
import { describeFugitiveOrder, isFugitive, label, tstate } from "../state";
import { HACK_DESC, HACK_KO, MESSAGES, ORDER_KO } from "../strings";
import { $, el, setRich, show } from "./dom";

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
    if (f.hack === "hide") { toast(MESSAGES.hide_no_move, 2000); return; }
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
    const r = await api.fugitiveOrder({ move: f.hack === "hide" ? null : f.move, hack: f.hack, target: f.hack ? f.target : null });
    // the ws fugitive_submitted carries no order: the REST answer is the truth for my own bar
    const p = tstate.payload;
    if (p?.fugitive && r.order) { p.fugitive.order = r.order; p.fugitive_submitted = true; }
    toast(r.resolved ? "전원 제출 완료 · 정산해요" : `명령 접수: ${describeFugitiveOrder(r.order)}`);
    tbus.emit("state:changed", {});
  } catch (e) {
    toast(msgFor(e), 4000);
  }
}

async function cancelOrder(): Promise<void> {
  try {
    await api.cancelFugitiveOrder();
    const p = tstate.payload;
    if (p?.fugitive) { p.fugitive.order = null; p.fugitive_submitted = false; }
    toast("제출을 취소했어요");
    tbus.emit("state:changed", {});
  } catch (e) { toast(msgFor(e)); }
}

async function ping(): Promise<void> {
  try {
    const r = await api.ping();
    tstate.pingOrders = r.orders;
    const p = tstate.payload;
    if (p?.fugitive) { p.fugitive.ram = r.ram; p.fugitive.trace = r.trace; p.fugitive.pinged = r.pinged ?? true; }
    const lines = Object.entries(r.orders).map(([id, o]) => `${label(id)}: ${o ? (o.type === "move" ? `이동 → ${o.target}` : ORDER_KO[o.type]) : "미제출"}`);
    toast(`{signal} 핑 결과 · ${lines.join(" · ")}`, 6000);
    tbus.emit("state:changed", {});
  } catch (e) {
    toast(msgFor(e), 4000);
  }
}

/** Rooms by BFS distance from `from` over the map's adjacency. */
function distances(rows: MapRow[], from: string): Map<string, number> {
  const adj = new Map(rows.map((r) => [r.room, r.neighbors.split(",").filter(Boolean)]));
  const d = new Map<string, number>([[from, 0]]);
  const q = [from];
  while (q.length) {
    const cur = q.shift()!;
    for (const n of adj.get(cur) ?? []) if (!d.has(n)) { d.set(n, d.get(cur)! + 1); q.push(n); }
  }
  return d;
}

/** The door `edge` ("A1-A2") lies on a shortest way from `from` to `to`: locking it stops me in front of it. */
function edgeOnPath(rows: MapRow[], from: string, to: string, edge: string): boolean {
  const [a, b] = edge.split("-");
  const ds = distances(rows, from), dt = distances(rows, to);
  const total = ds.get(to);
  if (total === undefined) return false;
  const via = (x: string, y: string) => (ds.get(x) ?? Infinity) + 1 + (dt.get(y) ?? Infinity) === total;
  return via(a, b) || via(b, a);
}

function render(): void {
  const p = tstate.payload;
  const on = isFugitive() && !!p && !p.fugitive_ai && p.status === "ROUND_OPEN" && !!p.fugitive && tstate.phase !== "playback";
  show("fugbar", on);
  if (!on || !p?.fugitive) return;
  const f = p.fugitive;
  const pick = tstate.fpick;
  const ramMax = Number(p.config?.ram_max ?? 10);
  $("fug-ram").textContent = `RAM ${"▮".repeat(Math.max(0, f.ram))}${"▯".repeat(Math.max(0, ramMax - f.ram))} ${f.ram}/${ramMax}`;
  $("fug-trace").textContent = `추적률 ${f.trace}% · 경계도 ${f.tier}${f.frozen ? " · 동결" : ""}${f.hacks_disabled ? " · 덱 봉인" : ""}${f.hidden_until >= (p.round_no ?? 0) ? " · 은신 중" : ""}`;
  const status = $("fug-status");
  const submitted = !!f.order || !!p.fugitive_submitted;
  show("btn-fug-cancel", submitted);
  $("btn-fug-confirm-val").textContent = submitted ? "바꾼 행동으로 확정" : "이번 라운드 행동 확정";
  const pickText = `${describeFugitiveOrder(pick)}${pick.hack === "hide" ? " · 은신하면 이번 라운드는 제자리예요" : ""}`
    + `${pick.hack === "doorlock" && !pick.target ? " · 잠글 문을 눌러요" : ""}${pick.hack === "distract" && !pick.target ? " · 교란할 구역을 눌러요" : ""}`;
  setRich(status, submitted
    ? `{save} ${f.order ? describeFugitiveOrder(f.order) : "제출함"} · 바꾸기: ${pickText}`
    : `${f.room}에 있어요 · ${pickText}`);

  // a lock on my own way: the engine stops me in front of it (2 RAM and +trace for nothing)
  const warn = pick.hack === "doorlock" && !!pick.target && !!pick.move && !!p.view
    && edgeOnPath(p.view.map_rows, f.room, pick.move, pick.target);
  show("fug-warn", warn);
  if (warn) setRich($("fug-warn"), "{alert} 내가 갈 문을 잠그면 제자리에 멈춰요");

  const hacks = $("fug-hacks");
  hacks.innerHTML = "";
  for (const hk of HACKS) {
    const info = p.hacks?.[hk];
    const b = el("button", "chip" + (pick.hack === hk ? " active" : ""), `${HACK_KO[hk]} ${info ? `(${info.cost})` : ""}`);
    b.title = HACK_DESC[hk] ?? "";
    if (info && !info.ok) { b.classList.add("off"); b.title += `\n(${info.why})`; b.appendChild(el("span", "fug-why", shortWhy(info.why))); }
    b.onclick = () => {
      if (info && !info.ok) { toast(info.why, 4000); return; }
      pick.hack = pick.hack === hk ? null : hk;
      pick.target = null;
      if (pick.hack === "hide") pick.move = null;   // hiding means staying put this round
      changed();
    };
    hacks.appendChild(b);
  }
  const desc = $("fug-hack-desc");
  desc.textContent = pick.hack ? `${HACK_KO[pick.hack]}: ${HACK_DESC[pick.hack] ?? ""}` : "";
  show("fug-hack-desc", !!pick.hack);
  const pingInfo = p.hacks?.ping;
  const pingBtn = $<HTMLButtonElement>("btn-fug-ping");
  $("btn-fug-ping-val").textContent = `핑 (${pingInfo?.cost ?? "?"})${f.pinged ? " · 사용함" : pingInfo && !pingInfo.ok ? ` · ${shortWhy(pingInfo.why)}` : ""}`;
  pingBtn.disabled = f.pinged || !(pingInfo?.ok ?? false);
  pingBtn.title = f.pinged ? "이번 라운드에 이미 핑을 썼어요" : `${HACK_DESC.ping}${pingInfo && !pingInfo.ok ? `\n(${pingInfo.why})` : ""}`;
  $("fug-projection").textContent = projection(p, pick.hack, f.pinged);
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
  const add = hack ? Number(p.hacks?.[hack]?.trace ?? 0) : 0;
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
