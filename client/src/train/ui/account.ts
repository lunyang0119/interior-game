/** The train page's account panel: the same localStorage accounts as the room game (storage.ts). Nickname = login
 *  (/api/register: an existing id gets a fresh token, a new one is created), switch / drop stored accounts, copy the
 *  recovery link, reach the admin claim. */

import { api as roomApi, ApiError, msgFor } from "../../api";
import { state } from "../../state";
import * as storage from "../../storage";
import { toast } from "../bus";
import { $, el, ic, openPanel, show } from "./dom";

export interface AccountHooks {
  /** switch the page to the stored account `id` (null = none left) */
  onSwitch: (id: string | null) => Promise<void>;
}

let hooks: AccountHooks;

export function initAccount(h: AccountHooks): void {
  hooks = h;
  const input = $<HTMLInputElement>("register-id");
  $("btn-register").onclick = () => void register();
  input.onkeydown = (ev) => { if (ev.key === "Enter") void register(); };
  $("btn-recovery").onclick = () => void copyRecovery();
  $("btn-account-claim").onclick = () => { openPanel("panel-claim"); $<HTMLInputElement>("claim-secret").focus(); };
}

/** Open the panel (rendering the stored accounts); on desktop the nickname box takes focus. */
export function openAccount(): void {
  render();
  openPanel("panel-account");
  if (matchMedia("(pointer: fine)").matches && !state.id) $<HTMLInputElement>("register-id").focus();
}

async function register(): Promise<void> {
  const input = $<HTMLInputElement>("register-id");
  const btn = $<HTMLButtonElement>("btn-register");
  const id = input.value.trim();
  if (!id || btn.disabled) return;
  btn.disabled = true;
  try {
    const r = await roomApi.register(id);
    storage.addAccount({ id: r.id, token: r.token });
    input.value = "";
    toast(r.existing ? `${r.id} 계정으로 들어왔어요` : `${r.id} 등록 완료`);
    show("panel-account", false);
    await hooks.onSwitch(r.id);
  } catch (e) {
    toast(e instanceof ApiError ? msgFor(e.code) : String(e));
  } finally {
    btn.disabled = false;
  }
}

async function copyRecovery(): Promise<void> {
  const acct = storage.activeAccount();
  if (!acct) { toast("계정이 없네요"); return; }
  const link = storage.recoveryLink(acct.token);
  try {
    await navigator.clipboard.writeText(link);
    toast("복구 링크를 복사했어요");
  } catch {
    prompt("복구 링크예요. 복사해 주세요", link);
  }
}

function render(): void {
  const list = $("accounts-list");
  list.innerHTML = "";
  const accounts = storage.accounts();
  if (accounts.length === 0) {
    list.appendChild(el("div", "small muted", "닉네임을 쓰고 들어와주세요. 이미 있는 계정이면 그 계정으로, 없으면 새로 만들어져요 (시트 닉네임의 일부만 써도 돼요)."));
    return;
  }
  for (const a of accounts) {
    const row = el("div", "acct" + (a.id === state.id ? " active" : ""));
    row.appendChild(el("span", "name", a.id));
    if (a.id !== state.id) {
      const sw = el("button", "primary", "전환");
      sw.onclick = () => { storage.setActive(a.id); show("panel-account", false); void hooks.onSwitch(a.id); };
      row.appendChild(sw);
    }
    const rm = el("button", "");
    rm.appendChild(ic("close"));
    rm.appendChild(el("span", "", "삭제"));
    rm.onclick = () => {
      if (!confirm(`${a.id}를 이 기기에서 지울까요? (닉네임으로 다시 들어올 수 있어요)`)) return;
      storage.removeAccount(a.id);
      const next = storage.activeAccount();
      if (a.id === state.id) void hooks.onSwitch(next?.id ?? null);
      render();
    };
    row.appendChild(rm);
    list.appendChild(row);
  }
}
