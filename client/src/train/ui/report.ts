/** 📡 panel: the last report as text, every hunter's room + public order, fugitive extras. */

import { tbus } from "../bus";
import { isBot, isFugitive, isOver, label, tstate } from "../state";
import { HACK_KO, ORDER_KO } from "../strings";
import type { BotReason, Report } from "../api";
import { actionText, resultText } from "../report";
import { $, el, richEl, setRich, show } from "./dom";

/** "R3 🕶 도주자-AI: 이동 → B2 + hide — 이유" / "R3 🤖 제미나이-1: 수색 — 이유" */
export function reasonLine(r: BotReason): string {
  const who = r.uid === "fugitive" ? "{target} 도주자-AI" : `{chat} ${label(r.uid)}`;
  const order = r.uid === "fugitive"
    ? `${r.target ? `이동 → ${r.target}` : "대기"}${r.order && r.order !== "stay" ? ` + ${HACK_KO[r.order] ?? r.order}${r.hack_target ? ` ${r.hack_target}` : ""}` : ""}`
    : `${ORDER_KO[r.order as keyof typeof ORDER_KO] ?? r.order}${r.target ? ` → ${r.target}` : ""}`;
  return `R${r.round} ${who}: ${order}${r.accepted ? "" : ` (규칙 위반: ${r.note})`} · ${r.reason}`;
}

export function initReport(): void {
  tbus.on("state:changed", render);
  tbus.on("history:changed", render);
  render();
}

/** The newest round whose result is already on screen (not the one still playing back). */
function lastShown(): Report | null {
  const playing = tstate.playing?.round ?? Infinity;
  const h = tstate.history.filter((r) => r.round < playing);
  return h.length ? h[h.length - 1] : null;
}

function render(): void {
  const p = tstate.payload;
  const crew = $("report-crew");
  crew.innerHTML = "";
  // config keys the admin overrode at runtime: names only, so the crew knows the rules moved
  const keys = p?.override_keys ?? [];
  show("report-overrides", keys.length > 0);
  if (keys.length) setRich($("report-overrides"), `{sliders} 관제가 바꾼 설정: ${keys.join(", ")}`);
  if (!p || !p.view) return;
  const last = lastShown();
  const orders = isFugitive() ? (p.fugitive?.pinged ? (tstate.pingOrders ?? p.orders ?? {}) : null) : (p.orders ?? {});
  for (const h of p.view.hunters) {
    const o = orders ? orders[h.name] : undefined;
    let txt = `${h.tag}. ${isBot(h.name) ? "{chat} " : ""}${label(h.name)} · ${h.room}`;
    if (h.dazed) txt += " · {power} 행동 불가";
    else if (orders === null) txt += h.submitted ? " · 제출함" : " · 미제출";
    else if (o) txt += ` · ${o.type === "move" ? `이동 → ${o.target}` : ORDER_KO[o.type]}`;
    else txt += " · 미제출";
    const row = el("div", "crew-row stacked");
    row.appendChild(richEl("div", "", txt));
    // what this crew member did last round and what came of it
    const pb = last?.playback.hunters.find((x) => x.id === h.name);
    if (last && pb) row.appendChild(richEl("div", "small muted", `R${last.round}: ${actionText(pb)} · ${resultText(pb, last)}`));
    if (h.color) row.style.borderLeft = `4px solid ${h.color}`;
    crew.appendChild(row);
  }
  if (isFugitive() && !p.fugitive_ai && !p.fugitive?.pinged && p.status === "ROUND_OPEN") crew.appendChild(el("div", "small muted", "승무원 명령 내용은 핑을 써야 보여요"));
  if (isFugitive() && p.position_history) crew.appendChild(el("div", "small muted", `이동 기록: ${p.position_history.join(" → ")}`));
  // AI reasoning: the fugitive view (admin) sees it live, everyone sees the whole log once the chase is over
  const log = isOver(p.status) ? p.ai_log : isFugitive() ? p.bot_reasons : undefined;
  if (log?.length) {
    crew.appendChild(el("div", "panel-sub", "AI의 판단"));
    for (const r of [...log].reverse()) crew.appendChild(richEl("div", "small", reasonLine(r)));
  }
}
