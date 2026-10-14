/** Hunter order bar: pick by tapping rooms (or the quick buttons), then "이번 라운드 행동 확정". */

import { api, msgFor, type OrderType } from "../api";
import { tbus, toast } from "../bus";
import { isHunter, tstate } from "../state";
import { ORDER_KO } from "../strings";
import { $, show } from "./dom";

function describe(o: { type: OrderType; target: string | null } | null): string {
  if (!o) return "";
  return o.type === "move" ? `이동 → ${o.target}` : ORDER_KO[o.type];
}

export function initSubmit(): void {
  $("btn-pick-search").onclick = () => pick("search");
  $("btn-pick-scan").onclick = () => pick("scan");
  $("btn-pick-stay").onclick = () => pick("stay");
  $("btn-order-confirm").onclick = () => void confirmOrder();
  $("btn-order-cancel").onclick = () => void cancelOrder();
  tbus.on("room:tap", ({ room }) => {
    const p = tstate.payload;
    if (!isHunter() || !p || p.status !== "ROUND_OPEN" || !room || !p.you || !p.you.room || p.you.dazed || tstate.phase === "playback") return;
    if (room === p.you.room) { pick("search"); return; }
    const here = p.view?.map_rows.find((r) => r.room === p.you!.room);
    if (here && here.neighbors.split(",").includes(room)) {
      pick("move", room);
      // last round's locks are information only: a lock lasts the round it was cast, hunters learn it at resolution
      const edge = [p.you.room, room].sort().join("-");
      if ((p.view?.locks ?? []).includes(edge)) toast("⛔ 지난 라운드에 잠겨 있던 문이에요. 이번에도 잠길지는 정산 때 알 수 있어요", 3000);
    } else toast("바로 갈 수 없는 구역이에요 (옆 구역만)", 1500);
  });
  tbus.on("state:changed", render);
  // a new round opens → unfold the bar if I still have to act (G3)
  let lastRound = -1;
  tbus.on("state:changed", () => {
    const p = tstate.payload;
    const r = p?.round_no ?? -1;
    if (p?.status === "ROUND_OPEN" && r !== lastRound) {
      lastRound = r;
      if (isHunter() && p.you && !p.you.order && !p.you.dazed) $("orderbar").classList.remove("folded");
    }
  });
  tbus.on("orderbar:unfold", () => $("orderbar").classList.remove("folded"));
  render();
}

function pick(type: OrderType, target: string | null = null): void {
  tstate.pick = { type, target };
  tbus.emit("pick:changed", {});
  render();
}

async function confirmOrder(): Promise<void> {
  const o = tstate.pick;
  if (!o) { toast("먼저 행동을 골라 주세요"); return; }
  try {
    const changed = !!tstate.payload?.you?.order;
    await api.order(o.type, o.target);
    tstate.pick = null;
    toast(changed ? `명령 변경: ${describe(o)}` : `명령 접수: ${describe(o)} · 마감 전까지 다시 제출하면 덮어써요`);
  } catch (e) {
    toast(msgFor(e));
  }
}

async function cancelOrder(): Promise<void> {
  try { await api.cancelOrder(); toast("제출을 취소했어요"); } catch (e) { toast(msgFor(e)); }
}

function render(): void {
  const p = tstate.payload;
  const on = isHunter() && !!p && p.status === "ROUND_OPEN" && tstate.phase !== "playback" && !!p.you;
  show("orderbar", on);
  if (!on || !p?.you) return;
  const you = p.you;
  const status = $("order-status");
  // picking stays available after a submit: a new pick + 확정 overwrites the order on the server
  show("order-pick", !you.dazed);
  show("btn-order-confirm", !you.dazed);
  show("btn-order-cancel", !!you.order);
  const confirmBtn = $("btn-order-confirm");
  $("btn-order-confirm-val").textContent = you.order ? "바꾼 행동으로 확정" : "이번 라운드 행동 확정";
  if (you.dazed) status.textContent = "☕ 증기에 휩싸여 이번 라운드는 행동할 수 없어요";
  else if (you.order && tstate.pick) status.textContent = `✅ ${describe(you.order)} → 바꾸기: ${describe(tstate.pick)}`;
  else if (you.order) status.textContent = `✅ 제출함: ${describe(you.order)} · 마감 전까지 바꿀 수 있어요`;
  else if (tstate.pick) status.textContent = `선택: ${describe(tstate.pick)}`;
  else status.textContent = `${you.room}에 있어요 · 옆 구역을 누르면 이동, 지금 구역을 누르면 수색`;
  confirmBtn.toggleAttribute("disabled", !tstate.pick);
}
