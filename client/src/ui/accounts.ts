import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { state } from "../state";
import * as storage from "../storage";
import { $, closeAllPanels, show, togglePanel } from "./hud";

export function initAccounts(): void {
  $("btn-accounts").addEventListener("click", () => { render(); togglePanel("panel-accounts"); });

  $("btn-register").addEventListener("click", async () => {
    const input = $("register-id") as HTMLInputElement;
    const id = input.value.trim();
    if (!id) return;
    try {
      const r = await api.register(id);
      storage.addAccount({ id: r.id, token: r.token });
      input.value = "";
      toast(r.created ? `${r.id} 등록 완료 (시트에 새 행 추가됨). 복구 링크를 저장해둬` : `${r.id} 등록 완료. 복구 링크를 어딘가 저장해둬`);
      bus.emit("account:switch", { id: r.id });
      closeAllPanels();
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  });

  $("btn-recovery").addEventListener("click", async () => {
    const acct = storage.activeAccount();
    if (!acct) { toast("계정이 없어"); return; }
    const link = storage.recoveryLink(acct.token);
    try {
      await navigator.clipboard.writeText(link);
      toast("복구 링크 복사됨. 남한테 주면 그 사람이 네 계정으로 들어와");
    } catch {
      prompt("복구 링크 (복사해)", link);
    }
  });

  $("btn-rotate").addEventListener("click", async () => {
    if (!state.id) return;
    if (!confirm("토큰을 새로 발급하면 기존 복구 링크는 무효가 돼. 진행?")) return;
    try {
      const r = await api.rotate();
      storage.updateToken(r.id, r.token);
      state.token = r.token;
      toast("토큰 재발급 완료");
      bus.emit("account:switch", { id: r.id });
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  });

  $("btn-logins").addEventListener("click", async () => {
    if (!state.id) return;
    const out = $("logins-out");
    try {
      const r = await api.logins();
      out.textContent = r.logins.map((l) =>
        `${new Date(l.ts * 1000).toLocaleString()}  ${l.ok ? "✓" : "✗"} ${l.action.padEnd(9)} ip:${l.ip_hash}  ${l.ua}`).join("\n") || "기록 없음";
      show("logins-out", out.classList.contains("hidden"));
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  });
}

function render(): void {
  const list = $("accounts-list");
  list.innerHTML = "";
  const accounts = storage.accounts();
  if (accounts.length === 0) {
    list.innerHTML = `<div class="small" style="color:var(--muted)">아직 계정이 없어. 시트에 있는 ID로 등록해.</div>`;
    return;
  }
  for (const a of accounts) {
    const row = document.createElement("div");
    row.className = "acct" + (a.id === state.id ? " active" : "");
    row.innerHTML = `<span class="name">${a.id}</span>`;
    if (a.id !== state.id) {
      const sw = document.createElement("button");
      sw.textContent = "전환";
      sw.className = "primary";
      sw.addEventListener("click", () => { storage.setActive(a.id); bus.emit("account:switch", { id: a.id }); closeAllPanels(); });
      row.appendChild(sw);
    }
    const rm = document.createElement("button");
    rm.textContent = "삭제";
    rm.addEventListener("click", () => {
      if (!confirm(`${a.id}를 이 기기에서 지울까? (복구 링크 없으면 못 돌아와)`)) return;
      storage.removeAccount(a.id);
      const next = storage.activeAccount();
      bus.emit("account:switch", { id: next?.id ?? "" });
      render();
    });
    row.appendChild(rm);
    list.appendChild(row);
  }
}
