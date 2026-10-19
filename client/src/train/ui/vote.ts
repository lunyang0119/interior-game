/** Vote-to-skip panel: unsubmitted hunters with a vote button, counts out of `need`. */

import { api, msgFor } from "../api";
import { fmtRemain } from "../report";
import { tbus, toast } from "../bus";
import { isHunter, label, me, tstate } from "../state";
import { $, button, el, setRich } from "./dom";

export function initVote(): void {
  tbus.on("state:changed", render);
  // the window opens by the clock, not by a server message: refresh the open panel every few seconds
  window.setInterval(() => { if (!$("panel-vote").classList.contains("hidden")) render(); }, 3000);
  render();
}

function render(): void {
  const p = tstate.payload;
  const list = $("vote-list");
  list.innerHTML = "";
  if (!p || !p.view) return;
  const now = Date.now() / 1000;
  const open = p.status === "ROUND_OPEN" && p.vote_after_ts != null && now >= p.vote_after_ts;
  setRich($("vote-info"), open
    ? `아직 제출하지 않은 승무원을 "대기"로 넘길 수 있어요. 그 사람을 뺀 승무원의 과반(${p.need ?? 1}명)이 찬성하면 통과되고, 전원 제출이 되면 바로 다음 라운드로 넘어가요.`
    : `라운드가 열리고 ${Math.round(Number(p.config?.vote_skip_after_sec ?? 600) / 60)}분이 지나면 미제출자를 건너뛰는 투표를 열 수 있어요. 관제는 {gear} 패널의 vote_skip_after_sec 로 이 시간을 바꿀 수 있어요.`);
  for (const h of p.view.hunters) {
    if (h.submitted || h.dazed) continue;
    const voters = p.votes?.[h.name] ?? [];
    const row = el("div", "vote-row");
    row.appendChild(el("span", "", `${label(h.name)}${tstate.thinking.has(h.name) ? " (판단 중…)" : ""} — ${voters.length}/${p.vote_need?.[h.name] ?? p.need ?? 1}표${voters.length ? ` (${voters.map(label).join(", ")})` : ""}`));
    if (!open && isHunter() && h.name !== me() && p.status === "ROUND_OPEN" && p.vote_after_ts != null) {
      const b = button(`투표 가능까지 ${fmtRemain(p.vote_after_ts - now).replace(" 남음", "")}`, () => undefined);
      b.disabled = true;
      row.appendChild(b);
    }
    if (open && isHunter() && h.name !== me()) {
      const b = button(voters.includes(me()!) ? "찬성함" : "건너뛰기 찬성", async () => {
        try {
          const r = await api.vote(h.name);
          toast(r.passed ? `${label(h.name)}은(는) 이번 라운드 대기로 처리됐어요` : `찬성 ${r.votes.length}/${r.need}`);
        } catch (e) { toast(msgFor(e)); }
      }, voters.includes(me()!) ? "" : "primary");
      b.disabled = voters.includes(me()!);
      row.appendChild(b);
    }
    list.appendChild(row);
  }
  if (!list.children.length) list.appendChild(el("div", "small muted", "승무원은 모두 제출했어요"));
  if (p.status === "ROUND_OPEN") list.appendChild(el("div", "small muted", p.fugitive_submitted ? "도주자: 제출함" : tstate.thinking.has("fugitive") ? "도주자: AI가 판단 중…" : "도주자: 아직 미제출 (전원 제출 후 유예 시간이 지나면 대기 처리)"));
}
