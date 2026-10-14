/** Lobby / idle panel: who is aboard, join/leave, and (admin) create + start. */

import { api, msgFor, type MapSummary } from "../api";
import { tbus, toast } from "../bus";
import { isAdmin, isBot, label, me, tstate } from "../state";
import { $, button, el, openPanel, show } from "./dom";

let maps: MapSummary[] = [];
let countdown: number | null = null;

export function initLobby(): void {
  tbus.on("state:changed", render);
  render();
}

async function loadMaps(): Promise<void> {
  if (maps.length) return;
  try { maps = (await api.maps()).maps; } catch { /* keep "auto" only */ }
}

function render(): void {
  const p = tstate.payload;
  const st = p?.status ?? "IDLE";
  const list = $("lobby-list");
  const actions = $("lobby-actions");
  const info = $("lobby-info");
  list.innerHTML = "";
  actions.innerHTML = "";
  if (st !== "LOBBY" && st !== "IDLE") { show("panel-lobby", false); return; }
  openPanel("panel-lobby");

  if (st === "IDLE") {
    info.textContent = "진행 중인 추적이 없어요. 새 추적을 열면 이 계정이 관제(도주자)가 돼요.";
    {
      void loadMaps().then(() => {
        if ((tstate.payload?.status ?? "IDLE") !== "IDLE") return;   // a game opened while the maps were loading
        actions.innerHTML = "";
        const row = el("div", "row");
        const n = el("select");
        for (let i = 2; i <= 6; i++) { const o = el("option", "", `${i}명`); o.value = String(i); if (i === 4) o.selected = true; n.appendChild(o); }
        const m = el("select");
        const auto = el("option", "", "맵: 인원에 맞게"); auto.value = ""; m.appendChild(auto);
        for (const x of maps) { const o = el("option", "", `${x.id} (${x.rooms}칸)`); o.value = x.id; m.appendChild(o); }
        const ai = el("label", "small");
        const aiBox = el("input"); aiBox.type = "checkbox";
        ai.append(aiBox, " 도주자도 AI");
        ai.title = "도주자를 Gemini가 맡아요. 연 사람은 관제를 유지하면서 승무원으로 탑승할 수 있어요";
        row.append(n, m, button("새 추적 열기", async () => {
          try { await api.create(Number(n.value), m.value || undefined, aiBox.checked); } catch (e) { toast(msgFor(e)); }
        }, "primary"));
        if (tstate.payload?.ai_available) row.appendChild(ai);
        actions.appendChild(row);
      });
    }
    return;
  }

  const lobby = p?.lobby ?? [];
  info.textContent = `맵 ${p?.map_id} · 승무원 ${lobby.length}/${p?.hunter_count}명 · 도주자: ${p?.fugitive_ai ? "🤖 AI" : "관제"}`;
  for (const id of lobby) {
    const row = el("div", "lobby-row", `${isBot(id) ? "🤖" : "🚃"} ${label(id)}${id === me() ? " (나)" : ""}`);
    list.appendChild(row);
  }
  const bots = lobby.filter(isBot).length;
  if (isAdmin() && p?.ai_available && lobby.length < (p.hunter_count ?? 0)) {
    actions.appendChild(button(`AI 승무원으로 채우기 (${(p.hunter_count ?? 0) - lobby.length}명)`, async () => {
      try { await api.addBots(p.hunter_count ?? 2); } catch (e) { toast(msgFor(e)); }
    }));
  }
  if (isAdmin() && bots) {
    actions.appendChild(button(`AI 승무원 내리기 (${bots}명)`, async () => {
      try { await api.removeBots(); } catch (e) { toast(msgFor(e)); }
    }));
  }
  if (!lobby.length) list.appendChild(el("div", "small muted", "아직 아무도 탑승하지 않았어요"));
  if (isAdmin() && p?.ai_available) {
    actions.appendChild(button(p.fugitive_ai ? "도주자: AI → 내가 맡기" : "도주자: 내가 → AI에게 맡기기", async () => {
      try { await api.setFugitiveAi(!p.fugitive_ai); } catch (e) { toast(msgFor(e)); }
    }));
  }
  if (isAdmin()) {
    const go = button("출발 (라운드 1 시작)", () => {
      // 3-second countdown so a crew member still reading can shout; tapping again cancels
      if (countdown !== null) { window.clearInterval(countdown); countdown = null; go.textContent = "출발 (라운드 1 시작)"; toast("출발을 취소했어요"); return; }
      let n = 3;
      go.textContent = `출발 ${n}… (취소)`;
      countdown = window.setInterval(async () => {
        n--;
        if (n > 0) { go.textContent = `출발 ${n}… (취소)`; return; }
        window.clearInterval(countdown!); countdown = null;
        try { await api.start(); } catch (e) { toast(msgFor(e)); go.textContent = "출발 (라운드 1 시작)"; }
      }, 1000);
    }, "primary");
    actions.appendChild(go);
    actions.appendChild(button("추적 취소", async () => {
      if (!confirm("이 추적을 닫을까요?")) return;
      try { await api.endGame(); } catch (e) { toast(msgFor(e)); }
    }, "danger"));
  }
  if (isAdmin() && !p?.fugitive_ai) {
    // the admin is the fugitive: no riding
  } else if (me() && lobby.includes(me()!)) {
    actions.appendChild(button("하차", async () => { try { await api.leave(); } catch (e) { toast(msgFor(e)); } }));
  } else if (me()) {
    actions.appendChild(button("탑승", async () => { try { await api.join(); } catch (e) { toast(msgFor(e)); } }, "primary"));
  }
}
