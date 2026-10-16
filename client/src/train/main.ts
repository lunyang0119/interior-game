/** /train/ entry. Shares the account (storage.ts) and the catalog (asset version + character sheets) with the room
 *  game, nothing else. `?preview=<map_id>`: admin map preview. Otherwise: lobby → rounds, driven by /ws/train. */

import Phaser from "phaser";
import { api as roomApi } from "../api";
import { makeCatalog } from "../catalog";
import { state } from "../state";
import * as storage from "../storage";
import { refreshThemeLink } from "../assets";
import { api, ApiError, mapRooms, msgFor, type BotReason, type MapRoom, type MapSummary, type Report, type TrainState } from "./api";
import { tbus } from "./bus";
import { TrainBoot } from "./scenes/TrainBoot";
import { TrainScene, type TrainSceneData } from "./scenes/TrainScene";
import { label, lastPlayed, markPlayed, tstate, type Phase } from "./state";
import { S } from "./strings";
import { initAdmin } from "./ui/admin";
import { $, closePanels, initFolds, show } from "./ui/dom";
import { initFugitiveBar } from "./ui/fugitive";
import { initHud } from "./ui/hud";
import { initLobby } from "./ui/lobby";
import { initReport, reasonLine } from "./ui/report";
import { initHelp } from "./ui/help";
import { initRoundLog, remember } from "./ui/roundlog";
import { initTrainBgm, isMuted, setTrace, stop as stopBgm, toggleMute } from "./bgm";
import { initCues, roundCue } from "./cues";
import { initSubmit } from "./ui/submit";
import { initVote } from "./ui/vote";
import { tsocket } from "./ws";

let toastTimer: number | null = null;
function toast(text: string, ms = 2600): void {
  const el = $("toast");
  el.textContent = text;
  el.classList.remove("hidden");
  if (toastTimer !== null) clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el.classList.add("hidden"), ms);
}
tbus.on("toast", ({ text, ms }) => toast(text, ms));

function banner(text: string, ms = 4000): void {
  $("banner-text").textContent = text;
  show("banner");
  window.setTimeout(() => show("banner", false), ms);
}

// ---------------------------------------------------------------------------
// Phaser
// ---------------------------------------------------------------------------
let game: Phaser.Game | null = null;
let sceneMap = ""; // map id currently built in the scene

function startGame(data: TrainSceneData, key: string): void {
  sceneMap = key;
  if (game) {
    const sc = game.scene.getScene("Train");
    if (sc && game.scene.isActive("Train")) sc.scene.restart(data); else game.scene.start("Train", data);
    return;
  }
  game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: "game",
    backgroundColor: "#14141c",
    pixelArt: true,
    roundPixels: true,
    scale: { mode: Phaser.Scale.RESIZE, autoCenter: Phaser.Scale.NO_CENTER },
    input: { activePointers: 3 },
    scene: [TrainBoot, TrainScene],
  });
  game.scene.start("TrainBoot", data);
}

// ---------------------------------------------------------------------------
// admin claim + preview
// ---------------------------------------------------------------------------
async function ensureAdmin(): Promise<boolean> {
  // maps are public now; the claim panel below is only reached when the server refuses (old deploy)
  try {
    await api.maps();
    return true;
  } catch (e) {
    toast(msgFor(e));
  }
  show("loading", false);
  show("panel-claim");
  toast(S.previewNeedsAdmin);
  return new Promise<boolean>((resolve) => {
    const input = $<HTMLInputElement>("claim-secret");
    const go = async () => {
      const secret = input.value.trim();
      if (!secret) return;
      try {
        const r = await api.claim(secret);
        if (r.role === "fugitive") { show("panel-claim", false); toast(S.claimed); resolve(true); }
      } catch (e) {
        toast(msgFor(e));
      }
    };
    $("btn-claim").onclick = () => void go();
    input.onkeydown = (ev) => { if (ev.key === "Enter") void go(); };
    input.focus();
  });
}

async function preview(mapId: string): Promise<void> {
  if (!(await ensureAdmin())) return;
  let maps: MapSummary[] = [];
  try { maps = (await api.maps()).maps; } catch (e) { toast(msgFor(e)); }
  const bar = $("preview-maps");
  bar.innerHTML = "";
  const open = async (id: string) => {
    try {
      const m = await api.map(id);
      const url = new URL(location.href);
      url.searchParams.set("preview", id);
      history.replaceState(null, "", url.toString());
      for (const b of bar.querySelectorAll("button")) b.classList.toggle("active", b.dataset.id === id);
      $("hud-status").textContent = S.previewTitle(m.id, m.rooms.length);
      startGame({ rooms: m.rooms, preview: true }, m.id);
    } catch (e) {
      toast(e instanceof ApiError && e.code === "unknown_map" ? S.unknownMap : msgFor(e));
    }
  };
  for (const m of maps) {
    const b = document.createElement("button");
    b.textContent = `${m.id.replace("car2077_", "")}칸`;
    b.title = `${m.id} (${m.cols}×${m.rows})`;
    b.dataset.id = m.id;
    b.onclick = () => void open(m.id);
    bar.appendChild(b);
  }
  $<HTMLInputElement>("preview-grid").onchange = (ev) => tbus.emit("preview:grid", { on: (ev.target as HTMLInputElement).checked });
  show("previewbar");
  for (const id of ["btn-lobby", "btn-report", "btn-home-cam"]) show(id, false);
  tbus.on("room:tap", ({ room }) => { if (room) toast(room, 900); });
  await open(mapId);
}

// ---------------------------------------------------------------------------
// game flow
// ---------------------------------------------------------------------------
function phaseFor(p: TrainState): Phase {
  switch (p.status) {
    case "LOBBY": return "lobby";
    case "ROUND_OPEN": return "submit";
    case "PAUSED": return "paused";
    case "CAPTURED": return "captured";
    default: return "idle";
  }
}

/** New payload from the server: rebuild the scene if the map changed, then let every UI piece re-render. */
function applyState(p: TrainState): void {
  const prev = tstate.payload;
  tstate.payload = p;
  if (prev?.game_id !== p.game_id || prev?.round_no !== p.round_no) {
    tstate.pick = null;
    tstate.fpick = { move: null, hack: null, target: null };
    tstate.pingOrders = null;
  }
  if (tstate.phase !== "playback") tstate.phase = phaseFor(p);
  if (p.report) remember(p.report);
  if (prev?.game_id !== p.game_id) { tstate.history.length = 0; tstate.thinking.clear(); tbus.emit("history:changed", {}); }
  if (p.view && p.status !== "LOBBY" && p.status !== "IDLE") setTrace(p.report?.trace ?? p.view.trace ?? 0); else stopBgm();
  const rooms: MapRoom[] | null = p.view ? mapRooms(p.view.map_rows) : null;
  const key = p.view ? `${p.game_id}:${p.view.map_id}` : "";
  if (rooms && key !== sceneMap) startGame({ rooms }, key);
  else if (rooms && tstate.phase !== "playback") tbus.emit("scene:sync", {});
  if (!rooms && game && sceneMap) { game.scene.stop("Train"); sceneMap = ""; }
  show("loading", false);
  tbus.emit("state:changed", {});
}

let playQueue: Promise<void> = Promise.resolve();
const pendingPlays: { report: Report; gameId: number | null }[] = [];   // ordered by round (G8)
let draining = false;

/** Queue a round's report; rounds play in order, one at a time; "건너뛰기" drains the rest instantly. */
function play(report: Report, gameId: number | null): Promise<void> {
  remember(report);
  if (pendingPlays.some((x) => x.report.round === report.round && x.gameId === gameId)) return playQueue;
  pendingPlays.push({ report, gameId });
  pendingPlays.sort((a, b) => a.report.round - b.report.round);
  if (!draining) {
    draining = true;
    playQueue = (async () => {
      while (pendingPlays.length) {
        const next = pendingPlays.shift()!;
        await playOne(next.report, next.gameId);
      }
      tstate.skipping = false;
      draining = false;
      throttle();
    })();
  }
  return playQueue;
}

function playOne(report: Report, gameId: number | null): Promise<void> {
  return new Promise<void>((resolve) => {
    tstate.phase = "playback";
    tstate.playing = report;
    tstate.unseenResult = false;
    closePanels();
    throttle();
    tbus.emit("state:changed", {});
    const off = tbus.on("playback:done", ({ report: r }) => {
      if (r !== report) return;
      off();
      markPlayed(gameId, report.round);
      tstate.playing = null;
      if (tstate.payload) tstate.phase = phaseFor(tstate.payload);
      tbus.emit("state:changed", {});
      if (report.captured_by && tstate.payload?.status === "CAPTURED") {
        const name = report.captured_by;
        const particle = /[가-힣]$/.test(name) && (name.charCodeAt(name.length - 1) - 0xac00) % 28 !== 0 ? "이" : "가";
        banner(`수수께끼의 인영을 ${name}${particle} 잡았다!\nConflict Resolved.`, 7000);
      }
      resolve();
    });
    // the scene may still be booting (first payload): wait for it before starting the playback
    const kick = () => tbus.emit("playback:start", { report });
    if (game && game.scene.isActive("Train")) kick();
    else { const offReady = tbus.on("scene:ready", () => { offReady(); kick(); }); }
  });
}

// ---------------------------------------------------------------------------
// battery: low FPS + paused tweens while nothing plays; the loop sleeps while the tab is hidden (E12).
// The WebSocket and the HUD's setInterval timers are DOM-side and keep running.
// ---------------------------------------------------------------------------
const IDLE_FPS = 10;
let throttled = false;
function throttle(): void {
  if (!game) return;
  const want = tstate.phase !== "playback";
  if (want === throttled) return;
  throttled = want;
  const loop = game.loop as unknown as { fpsLimit: number; hasFpsLimit: boolean; _limitRate: number };
  loop.fpsLimit = want ? IDLE_FPS : 0;
  loop.hasFpsLimit = want;
  loop._limitRate = want ? 1000 / IDLE_FPS : 0;
  tbus.emit("throttle", { on: want });
}
document.addEventListener("visibilitychange", () => {
  if (!game) return;
  if (document.hidden) game.loop.sleep(); else game.loop.wake(true);
});

/** hello/state after a (re)connect: replay a round this browser has not seen to its end. */
function maybeReplay(p: TrainState): void {
  const rep = p.report;
  if (!rep || !p.view) return;
  if (rep.round > lastPlayed(p.game_id)) void play(rep, p.game_id);
}

type OrderMsg = { type: "move" | "search" | "scan" | "stay"; target: string | null } | null;

function wireSocket(): void {
  tsocket.on("open", () => show("hud-conn", false));
  tsocket.on("close", (m: { code: number }) => { show("hud-conn", true); if (m.code === 4401) toast(S.needLogin, 6000); });
  tsocket.on("hello", (m: { role: string; state: TrainState }) => { applyState(m.state); maybeReplay(m.state); });
  tsocket.on("state", (m: { state: TrainState }) => { applyState(m.state); maybeReplay(m.state); });
  tsocket.on("round_open", (m: { round: number; deadline_ts: number; vote_after_ts: number | null }) => {
    const p = tstate.payload;
    if (!p) return;
    p.status = "ROUND_OPEN"; p.deadline_ts = m.deadline_ts; p.grace_until = null; p.paused_remaining = null; p.vote_after_ts = m.vote_after_ts; p.votes = {};
    tstate.thinking.clear();
    applyState(p);
    if ((p.role === "hunter" && p.you && !p.you.dazed) || (p.role === "fugitive" && !p.fugitive_ai)) roundCue();
  });
  tsocket.on("submitted", (m: { id: string; submitted: boolean; order?: OrderMsg }) => {
    const p = tstate.payload;
    if (!p?.view) return;
    const h = p.view.hunters.find((x) => x.name === m.id);
    if (h) h.submitted = m.submitted;
    if (m.submitted) tstate.thinking.delete(m.id);
    if (p.orders && m.order !== undefined) p.orders[m.id] = m.order;
    if (p.you && p.you.id === m.id) p.you.order = m.order ?? (m.submitted ? p.you.order : null);
    if (p.votes && m.submitted) delete p.votes[m.id];
    if (p.hunters_full?.[m.id]) p.hunters_full[m.id].submitted = m.submitted;
    applyState(p);
  });
  tsocket.on("hunter_order", (m: { id: string; order: OrderMsg }) => {
    const p = tstate.payload;
    if (!p?.view) return;
    const h = p.view.hunters.find((x) => x.name === m.id);
    if (h) h.submitted = m.order !== null;
    if (!tstate.pingOrders) tstate.pingOrders = {};
    tstate.pingOrders[m.id] = m.order;
    if (p.hunters_full?.[m.id]) { p.hunters_full[m.id].order = m.order; p.hunters_full[m.id].submitted = m.order !== null; }
    toast(`${m.id}: ${m.order ? (m.order.type === "move" ? `이동 → ${m.order.target}` : m.order.type) : "제출 취소"}`, 2500);
    applyState(p);
  });
  tsocket.on("fugitive_submitted", (m: { submitted: boolean; round: number }) => {
    const p = tstate.payload;
    if (!p || (p.round_no ?? m.round) !== m.round) return;
    p.fugitive_submitted = m.submitted;
    if (p.fugitive) p.fugitive.order = m.submitted ? (p.fugitive.order ?? { move: null, hack: null, target: null }) : null;
    tstate.thinking.delete("fugitive");
    applyState(p);
  });
  tsocket.on("deadline", (m: { deadline_ts: number; reason: string; paused_remaining?: number | null }) => {
    const p = tstate.payload;
    if (!p) return;
    if (m.reason === "grace") { p.grace_until = m.deadline_ts; toast("승무원 전원 제출 — 침입자에게 유예 시간이 주어졌어요"); }
    else { p.deadline_ts = m.deadline_ts; if (m.paused_remaining != null) p.paused_remaining = m.paused_remaining; toast("마감이 연장됐어요"); }
    applyState(p);
  });
  tsocket.on("vote", (m: { target: string; voters: string[]; need: number; passed: boolean; void?: boolean }) => {
    const p = tstate.payload;
    if (!p) return;
    p.votes = p.votes ?? {};
    if (m.passed || m.void) delete p.votes[m.target]; else p.votes[m.target] = m.voters;
    p.need = m.need;
    if (m.passed) toast(`${m.target}은(는) 투표로 이번 라운드 대기 처리됐어요`);
    applyState(p);
  });
  tsocket.on("round_resolved", (m: { report: Report; state: TrainState }) => {
    applyState(m.state);
    if (document.hidden) tstate.unseenResult = true;
    void play(m.report, m.state.game_id);
  });
  tbus.on("playback:skip", () => { tstate.skipping = true; });
  tbus.on("playback:replay", ({ report }) => { if (tstate.phase !== "playback") void play(report, tstate.payload?.game_id ?? null); });
  tsocket.on("captured", (m: { room: string }) => {
    const p = tstate.payload;
    if (p) { p.status = "CAPTURED"; if (p.view) p.view.capture_room = m.room; }
    // the capture line itself is shown when the playback finishes (play())
  });
  tsocket.on("started", (m: { line: string }) => banner(m.line, 3500));
  tsocket.on("bot_thinking", (m: { id: string; round: number }) => {
    tstate.thinking.add(m.id);
    tbus.emit("state:changed", {});
    toast(`${m.id === "fugitive" ? "🕶" : "🤖"} ${label(m.id)} — R${m.round} 판단 중…`, 2500);
  });
  tsocket.on("bot_reason", (m: { reason: BotReason }) => {
    const p = tstate.payload;
    if (p) { p.bot_reasons = [...(p.bot_reasons ?? []), m.reason].slice(-24); tbus.emit("state:changed", {}); }
    toast(reasonLine(m.reason), 7000);
  });
  tsocket.on("paused", (m: { paused_remaining: number }) => {
    const p = tstate.payload;
    if (p) { p.status = "PAUSED"; p.paused_remaining = m.paused_remaining; applyState(p); toast("관제가 라운드를 잠시 멈췄어요"); }
  });
  tsocket.on("resumed", (m: { deadline_ts: number; vote_after_ts: number | null }) => {
    const p = tstate.payload;
    if (p) { p.status = "ROUND_OPEN"; p.deadline_ts = m.deadline_ts; p.paused_remaining = null; p.vote_after_ts = m.vote_after_ts; applyState(p); toast("라운드가 다시 진행돼요"); }
  });
  tsocket.on("ended", () => {
    applyState({ game_id: null, status: "IDLE", role: tstate.payload?.role ?? "spectator", you: null });
    toast("추적이 끝났어요");
  });
}

async function boot(): Promise<void> {
  const acct = storage.activeAccount();
  $("hud-id-val").textContent = acct?.id ?? "–";
  if (!acct) {
    show("loading", false);
    toast(S.needLogin, 6000);
    return;
  }
  state.token = acct.token;
  state.id = acct.id;
  try {
    state.catalog = makeCatalog(await roomApi.catalog()); // asset version (cache-busting) + character sheets
    refreshThemeLink();
  } catch (e) {
    toast(msgFor(e));
  }
  for (const btn of document.querySelectorAll<HTMLButtonElement>("[data-close]")) btn.onclick = () => show(btn.dataset.close!, false);
  tbus.on("scene:ready", () => show("loading", false));

  const params = new URLSearchParams(location.search);
  const pv = params.get("preview");
  if (pv) {
    await preview(pv);
    return;
  }

  initFolds();
  initHud();
  initLobby();
  initSubmit();
  initFugitiveBar();
  initVote();
  initReport();
  initAdmin();
  initRoundLog();
  initHelp();
  initCues();
  void initTrainBgm();
  const bgmBtn = () => { $("btn-bgm-val").textContent = isMuted() ? "소리 꺼짐" : "소리"; };
  $("btn-bgm").onclick = () => { toggleMute(); bgmBtn(); };
  bgmBtn();
  // the claim panel is reachable from the account chip for the admin-to-be
  $("hud-id").onclick = () => { show("panel-claim"); $<HTMLInputElement>("claim-secret").focus(); };
  $("btn-claim").onclick = async () => {
    const secret = $<HTMLInputElement>("claim-secret").value.trim();
    if (!secret) return;
    try {
      await api.claim(secret);
      show("panel-claim", false);
      toast(S.claimed);
      applyState(await api.state());
    } catch (e) { toast(msgFor(e)); }
  };
  wireSocket();
  tsocket.connect(acct.token);
}

void boot();
