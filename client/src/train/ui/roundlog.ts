/** Round result log inside the 보고 panel: one line per event in resolution order, every round this session has
 *  seen, newest first, scrollable. 다시 보기 sits in the panel; 재생 건너뛰기 floats over the map while a round plays. */

import type { Report } from "../api";
import { tbus } from "../bus";
import { reportLines } from "../report";
import { label, tstate } from "../state";
import { $, el, show } from "./dom";

export function initRoundLog(): void {
  $("btn-log-skip").onclick = () => tbus.emit("playback:skip", {});
  $("btn-log-replay").onclick = () => { const r = latest(); if (r) tbus.emit("playback:replay", { report: r }); };
  tbus.on("state:changed", render);
  tbus.on("history:changed", render);
  render();
}

function latest(): Report | null {
  const h = tstate.history;
  return h.length ? h[h.length - 1] : null;
}

/** Keep one report per round (reconnects re-send the last one). */
export function remember(rep: Report): void {
  const h = tstate.history;
  const i = h.findIndex((r) => r.round === rep.round);
  if (i >= 0) {
    // the fugitive's hidden notes ride only on the ws round_resolved / payload log copy: keep them across re-sends
    if (rep.fugitive_order === undefined && h[i].fugitive_order !== undefined) rep.fugitive_order = h[i].fugitive_order;
    if (!rep.hidden_events && h[i].hidden_events) rep.hidden_events = h[i].hidden_events;
    h[i] = rep;
  } else { h.push(rep); h.sort((a, b) => a.round - b.round); }
  tbus.emit("history:changed", {});
}

function render(): void {
  const p = tstate.payload;
  const on = !!p?.view && p.status !== "LOBBY" && p.status !== "IDLE";
  const playing = tstate.phase === "playback";
  show("skipbar", playing);
  show("btn-log-replay", on && !playing && tstate.history.length > 0);
  const box = $("roundlog-body");
  box.innerHTML = "";
  if (!on || !tstate.history.length) { box.appendChild(el("div", "small muted", "아직 판독 결과가 없어요")); return; }
  for (const rep of [...tstate.history].reverse()) {
    const playing = rep.round === tstate.playing?.round;
    const sec = el("div", "log-round" + (playing ? " playing" : ""));
    const lines = reportLines(rep, (uid) => label(uid));
    sec.appendChild(el("div", "log-head", lines[0] + (playing ? " · 재생 중" : "")));
    for (const l of lines.slice(1)) sec.appendChild(el("div", "small", l));
    box.appendChild(sec);
  }
}
