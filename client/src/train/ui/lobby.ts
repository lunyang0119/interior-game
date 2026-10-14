/** Lobby / idle panel: who is aboard, join/leave, and (admin) create + start. */

import { api, msgFor, type MapSummary } from "../api";
import { tbus, toast } from "../bus";
import { isFugitive, me, tstate } from "../state";
import { $, button, el, openPanel, show } from "./dom";

let maps: MapSummary[] = [];

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
        actions.innerHTML = "";
        const row = el("div", "row");
        const n = el("select");
        for (let i = 2; i <= 6; i++) { const o = el("option", "", `${i}명`); o.value = String(i); if (i === 4) o.selected = true; n.appendChild(o); }
        const m = el("select");
        const auto = el("option", "", "맵: 인원에 맞게"); auto.value = ""; m.appendChild(auto);
        for (const x of maps) { const o = el("option", "", `${x.id} (${x.rooms}칸)`); o.value = x.id; m.appendChild(o); }
        row.append(n, m, button("새 추적 열기", async () => {
          try { await api.create(Number(n.value), m.value || undefined); } catch (e) { toast(msgFor(e)); }
        }, "primary"));
        actions.appendChild(row);
      });
    }
    return;
  }

  const lobby = p?.lobby ?? [];
  info.textContent = `맵 ${p?.map_id} · 승무원 ${lobby.length}/${p?.hunter_count}명`;
  for (const id of lobby) {
    const row = el("div", "lobby-row", `🚃 ${id}${id === me() ? " (나)" : ""}`);
    list.appendChild(row);
  }
  if (!lobby.length) list.appendChild(el("div", "small muted", "아직 아무도 탑승하지 않았어요"));
  if (isFugitive()) {
    actions.appendChild(button("출발 (라운드 1 시작)", async () => {
      try { await api.start(); } catch (e) { toast(msgFor(e)); }
    }, "primary"));
    actions.appendChild(button("추적 취소", async () => {
      if (!confirm("이 추적을 닫을까요?")) return;
      try { await api.endGame(); } catch (e) { toast(msgFor(e)); }
    }, "danger"));
  } else if (me() && lobby.includes(me()!)) {
    actions.appendChild(button("하차", async () => { try { await api.leave(); } catch (e) { toast(msgFor(e)); } }));
  } else if (me()) {
    actions.appendChild(button("탑승", async () => { try { await api.join(); } catch (e) { toast(msgFor(e)); } }, "primary"));
  }
}
