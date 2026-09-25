import { api, ApiError, msgFor } from "../api";
import { bus } from "../bus";
import { state } from "../state";

export function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} missing`);
  return el;
}

export function show(id: string, on: boolean): void {
  $(id).classList.toggle("hidden", !on);
}

export function closeAllPanels(): void {
  document.querySelectorAll<HTMLElement>(".panel").forEach((p) => p.classList.add("hidden"));
}

export function togglePanel(id: string): void {
  const open = $(id).classList.contains("hidden");
  closeAllPanels();
  if (open) show(id, true);
}

let toastTimer: number | null = null;

/** Click handler that ignores re-taps while the async work is in flight (buttons show disabled meanwhile). */
export function guard(btn: HTMLElement, fn: () => Promise<void>): void {
  const b = btn as HTMLButtonElement;
  b.addEventListener("click", async () => {
    if (b.disabled) return;
    b.disabled = true;
    try { await fn(); } finally { b.disabled = false; }
  });
}

export function initHud(): void {
  document.querySelectorAll<HTMLElement>("[data-close]").forEach((b) => {
    b.addEventListener("click", () => show(b.dataset.close!, false));
  });

  bus.on("money", ({ balance }) => { $("hud-balance-val").textContent = balance.toLocaleString(); });
  bus.on("online", ({ count }) => { $("hud-online-val").textContent = String(count); });
  bus.on("toast", ({ text, ms }) => {
    const t = $("toast");
    t.textContent = text;
    t.classList.remove("hidden");
    if (toastTimer !== null) clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => t.classList.add("hidden"), ms ?? 2200);
  });

  bus.on("place:state", ({ active, label, ok, mode }) => {
    show("placebar", active);
    show("bottombar", !active);
    $("place-label").textContent = label;
    $("place-confirm").classList.toggle("primary", ok);
    show("place-again", active && mode === "place"); // "one more" only makes sense for new items
    if (active) closeAllPanels();
  });
  $("place-confirm").addEventListener("click", () => bus.emit("place:confirm"));
  $("place-again").addEventListener("click", () => bus.emit("place:confirm-again"));
  $("place-cancel").addEventListener("click", () => bus.emit("place:cancel"));

  guard($("btn-sync"), async () => {
    if (!state.token) { bus.emit("toast", { text: "먼저 계정을 골라주세요" }); return; }
    try {
      const r = await api.sync();
      state.balance = r.balance;
      state.contributions = r.contributions;
      bus.emit("money", { balance: r.balance });
      bus.emit("toast", { text: r.refreshed ? "시트 동기화 완료" : "잠시 뒤에 다시 시도해주세요" });
    } catch (e) {
      bus.emit("toast", { text: e instanceof ApiError ? msgFor(e.code) : String(e) });
    }
  });

  renderIdentity();
}

export function renderIdentity(): void {
  $("hud-id").textContent = state.id ?? "계정 없음";
  $("hud-balance-val").textContent = state.id ? state.balance.toLocaleString() : "–";
}
