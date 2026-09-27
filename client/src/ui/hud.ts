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
  bus.on("room:changed", ({ name, id, ruined }) => {
    $("hud-room-val").textContent = name || id;
    $("hud-room-ruined").textContent = ruined > 0 ? ` · 🧹 ${ruined}` : "";
    show("hud-room", true);
  });
  bus.on("toast", ({ text, ms }) => {
    const t = $("toast");
    t.textContent = text;
    t.classList.remove("hidden");
    if (toastTimer !== null) clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => t.classList.add("hidden"), ms ?? 2200);
  });

  bus.on("place:state", ({ active, label, ok, mode, busy, span, spanMax }) => {
    show("placebar", active);
    show("bottombar", !active);
    $("place-label").textContent = label;
    $("place-confirm").classList.toggle("primary", ok);
    show("place-again", active && mode === "place"); // "one more" only makes sense for new items
    show("place-span", active && span != null); // wallpaper: pick how many columns it covers
    if (span != null) {
      $("place-span-val").textContent = String(span);
      ($("place-span-dec") as HTMLButtonElement).disabled = span <= 1;
      ($("place-span-inc") as HTMLButtonElement).disabled = spanMax != null && span >= spanMax;
    }
    for (const id of ["place-confirm", "place-again", "place-cancel"]) ($(id) as HTMLButtonElement).disabled = !!busy;
    if (active) closeAllPanels();
  });
  $("place-confirm").addEventListener("click", () => bus.emit("place:confirm"));
  $("place-again").addEventListener("click", () => bus.emit("place:confirm-again"));
  $("place-cancel").addEventListener("click", () => bus.emit("place:cancel"));
  // dock: hide the room-only bottom bar, show 나가기/낚시 at the top-left
  // which world scene is up decides the bars: shop only in rooms, 나가기/낚시 only on the dock
  bus.on("scene:changed", ({ scene }) => {
    closeAllPanels();
    show("placebar", false);
    show("dockbar", scene === "dock");
    show("fishbar", scene === "dock");
    show("fish-catch", false);
    show("bottombar", scene !== "dock");
    show("btn-shop", scene === "room");
    show("hud-room", scene !== "dock");
    show("panel-enter", false);
  });
  bus.on("map:enter-ask", ({ name }) => {
    if (!name) { show("panel-enter", false); return; }
    $("enter-text").textContent = `${name}에 들어가시겠어요?`;
    show("panel-enter", true);
  });
  $("enter-yes").addEventListener("click", () => { show("panel-enter", false); bus.emit("map:enter-answer", { yes: true }); });
  $("enter-no").addEventListener("click", () => { show("panel-enter", false); bus.emit("map:enter-answer", { yes: false }); });
  $("btn-dock-exit").addEventListener("click", () => bus.emit("dock:exit"));
  // fishing: the button is a hold button (pointer events so touch and mouse behave the same)
  const fishBtn = $("btn-fish");
  let fishDown = false;
  const down = (e: Event) => { e.preventDefault(); if (fishDown) return; fishDown = true; fishBtn.classList.add("holding"); bus.emit("fish:press"); };
  const up = () => { if (!fishDown) return; fishDown = false; fishBtn.classList.remove("holding"); bus.emit("fish:release"); };
  fishBtn.addEventListener("pointerdown", down);
  fishBtn.addEventListener("pointerup", up);
  fishBtn.addEventListener("pointercancel", up);
  fishBtn.addEventListener("pointerleave", up);
  fishBtn.addEventListener("contextmenu", (e) => e.preventDefault());
  window.addEventListener("blur", up);
  bus.on("fish:state", ({ status, holding, active, real }) => {
    $("fish-status").textContent = status;
    $("fish-status").classList.toggle("real", real);
    $("fish-meter").style.visibility = holding ? "visible" : "hidden";
    if (!holding) { $("fish-meter-fill").style.width = "0"; $("fish-meter-fill").classList.remove("enough"); }
    fishBtn.textContent = active ? (holding ? "🎣 잡는 중…" : "🎣 꾹!") : "🎣 낚시";
  });
  bus.on("fish:meter", ({ meter, enough }) => {
    $("fish-meter").style.visibility = "visible";
    $("fish-meter-fill").style.width = `${Math.round(meter * 100)}%`;
    $("fish-meter-fill").classList.toggle("enough", enough);
  });
  let catchTimer: number | null = null;
  bus.on("fish:catch", ({ ok, id, name, value, who }) => {
    const img = $("fish-catch-img") as HTMLImageElement;
    img.src = `/gen/fish/${id}.png`;
    img.style.visibility = ok ? "visible" : "hidden";
    $("fish-catch-text").textContent = ok
      ? (who && who !== state.id ? `${who}가 ${name}을(를) 낚았어요! +${value}💰` : `${name}을(를) 낚았어요! +${value}💰`)
      : `놓쳤어요… ${name}이(가) 도망쳤어요`;
    show("fish-catch", true);
    if (catchTimer !== null) clearTimeout(catchTimer);
    catchTimer = window.setTimeout(() => show("fish-catch", false), 2600);
  });
  $("place-span-dec").addEventListener("click", () => bus.emit("place:span", { delta: -1 }));
  $("place-span-inc").addEventListener("click", () => bus.emit("place:span", { delta: 1 }));

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
