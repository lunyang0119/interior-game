/** 📡 panel: the last report as text, every hunter's room + public order, fugitive extras. */

import { tbus } from "../bus";
import { reportLines } from "../report";
import { isFugitive, tstate } from "../state";
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
    let txt = `${h.tag}. ${h.name} — ${h.room}`;
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
}
