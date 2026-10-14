/** 📡 panel: the last report as text, every hunter's room + public order, fugitive extras. */

import { tbus } from "../bus";
import { reportLines } from "../report";
import { isBot, isFugitive, label, tstate } from "../state";
import { ORDER_KO } from "../strings";
import { $, el } from "./dom";

export function initReport(): void {
  tbus.on("state:changed", render);
  render();
}

function render(): void {
  const p = tstate.payload;
  const rep = $("report-text");
  const crew = $("report-crew");
  rep.innerHTML = "";
  crew.innerHTML = "";
  if (!p || !p.view) { rep.textContent = "아직 보고가 없어요"; return; }
  if (p.report) for (const line of reportLines(p.report, (uid) => uid)) rep.appendChild(el("div", "", line));
  else rep.textContent = "라운드 1 — 아직 판독 결과가 없어요";
  const orders = isFugitive() ? (p.fugitive?.pinged ? (tstate.pingOrders ?? p.orders ?? {}) : null) : (p.orders ?? {});
  for (const h of p.view.hunters) {
    const o = orders ? orders[h.name] : undefined;
    let txt = `${h.tag}. ${isBot(h.name) ? "🤖 " : ""}${label(h.name)} — ${h.room}`;
    if (h.dazed) txt += " · ☕ 행동 불가";
    else if (orders === null) txt += h.submitted ? " · 제출함" : " · 미제출";
    else if (o) txt += ` · ${o.type === "move" ? `이동 → ${o.target}` : ORDER_KO[o.type]}`;
    else txt += " · 미제출";
    const row = el("div", "crew-row", txt);
    if (h.color) row.style.borderLeft = `4px solid ${h.color}`;
    crew.appendChild(row);
  }
  if (isFugitive() && !p.fugitive?.pinged && p.status === "ROUND_OPEN") crew.appendChild(el("div", "small muted", "승무원 명령 내용은 핑을 써야 보여요"));
  if (isFugitive() && p.position_history) crew.appendChild(el("div", "small muted", `이동 기록: ${p.position_history.join(" → ")}`));
  const reasons = (p.bot_reasons ?? []).filter((r) => r.round === (p.round_no ?? p.view?.round_no) || r.round === (p.report?.round ?? -1));
  if (p.status === "CAPTURED" && p.ai_log?.length) {
    crew.appendChild(el("div", "panel-sub", "AI의 판단 기록"));
    for (const r of p.ai_log) {
      const who = r.uid === "fugitive" ? "🕶 도주자-AI" : `🤖 ${label(r.uid)}`;
      const order = r.uid === "fugitive"
        ? `${r.target ? `이동 → ${r.target}` : "대기"}${r.order && r.order !== "stay" ? ` + ${r.order}${r.hack_target ? ` ${r.hack_target}` : ""}` : ""}`
        : `${ORDER_KO[r.order as keyof typeof ORDER_KO] ?? r.order}${r.target ? ` → ${r.target}` : ""}`;
      crew.appendChild(el("div", "small", `R${r.round} ${who}: ${order}${r.accepted ? "" : ` (규칙 위반: ${r.note})`} — ${r.reason}`));
    }
  } else if (isFugitive() && reasons.length) {
    crew.appendChild(el("div", "panel-sub", "AI 승무원의 판단"));
    for (const r of reasons) {
      const order = `${ORDER_KO[r.order as keyof typeof ORDER_KO] ?? r.order}${r.target ? ` → ${r.target}` : ""}`;
      crew.appendChild(el("div", "small", `R${r.round} 🤖 ${label(r.uid)}: ${order}${r.accepted ? "" : ` (규칙 위반이라 대기 처리: ${r.note})`} — ${r.reason}`));
    }
  }
}
