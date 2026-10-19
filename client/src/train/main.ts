/** /train/ entry. Shares the account (storage.ts) and the catalog (asset version + character sheets) with the room
 *  game, nothing else. `?preview=<map_id>`: admin map preview. Otherwise: lobby → rounds, driven by /ws/train. */

import Phaser from "phaser";
import { api as roomApi } from "../api";
import { makeCatalog } from "../catalog";
import { state } from "../state";
import * as storage from "../storage";
import { refreshThemeLink } from "../assets";
import { api, ApiError, mapRooms, msgFor, type BotReason, type LogEntry, type MapRoom, type MapSummary, type Report, type TrainState } from "./api";
import { tbus } from "./bus";
import { TrainBoot } from "./scenes/TrainBoot";
import { TrainScene, type TrainSceneData } from "./scenes/TrainScene";
import { isFugitive, isHunter, isOver, label, lastPlayed, markPlayed, tstate, type Phase } from "./state";
import { ORDER_KO, S } from "./strings";
import { initAccount, openAccount } from "./ui/account";
import { initAdmin } from "./ui/admin";
import { $, closePanels, initFolds, setRich, show } from "./ui/dom";
import { initFugitiveBar } from "./ui/fugitive";
import { initHud } from "./ui/hud";
import { initLobby } from "./ui/lobby";
import { initReport, reasonLine } from "./ui/report";
import { initHelp } from "./ui/help";
import { initRoundLog, remember } from "./ui/roundlog";
import { hideRoundCard, initRoundCard, showRoundCard } from "./ui/roundcard";
import { initTrainBgm, isMuted, setTrace, stop as stopBgm, toggleMute } from "./bgm";
import { initCues, roundCue } from "./cues";
import { initSubmit } from "./ui/submit";
import { initVote } from "./ui/vote";
import { tsocket } from "./ws";

// toasts queue up (at most 3 waiting) so a burst of messages (bot reasons, hack notices) is not overwritten
const TOAST_QUEUE_MAX = 3;
const toastQueue: { text: string; ms: number }[] = [];
let toastTimer: number | null = null;
let toastShown = "";

/** Below the HUD's real bottom edge: on phones the HUD wraps to several lines. */
function placeToast(el: HTMLElement): void {
  const hud = document.getElementById("hud");
  const bottom = hud && !hud.classList.contains("hidden") ? hud.getBoundingClientRect().bottom : 0;
  el.style.top = bottom > 0 ? `${Math.round(bottom + 6)}px` : "";
}

function nextToast(): void {
  const el = $("toast");
  const t = toastQueue.shift();
  if (!t) { el.classList.add("hidden"); toastTimer = null; toastShown = ""; return; }
  toastShown = t.text;
  setRich(el, t.text);
  placeToast(el);
  el.classList.remove("hidden");
  toastTimer = window.setTimeout(nextToast, t.ms);
}

function toast(text: string, ms = 2600): void {
  if (text === toastShown || toastQueue.some((t) => t.text === text)) return;
  toastQueue.push({ text, ms });
  while (toastQueue.length > TOAST_QUEUE_MAX) toastQueue.shift();
  if (toastTimer === null) nextToast();
}
tbus.on("toast", ({ text, ms }) => toast(text, ms));
// a tap closes the toast early and shows the next queued one
$("toast").onclick = () => { if (toastTimer !== null) window.clearTimeout(toastTimer); nextToast(); };

let bannerTimer: number | null = null;
function banner(text: string, ms = 4000): void {
  $("banner-text").textContent = text;
  show("banner");
  if (bannerTimer !== null) window.clearTimeout(bannerTimer);
  bannerTimer = window.setTimeout(() => { bannerTimer = null; show("banner", false); }, ms);
}

/** "가" / "이" after a Korean name (the last syllable's final consonant). */
function particle(name: string): string {
  return /[가-힣]$/.test(name) && (name.charCodeAt(name.length - 1) - 0xac00) % 28 !== 0 ? "이" : "가";
}

/** Capture / escape banners already shown, per game and round (a replay or a re-sent state never repeats them). */
const endBanners = new Set<string>();
const END_BANNER_MS = 7000;

/** The end-of-chase banner for `report` once its playback is over; true when one was shown. */
function endBanner(report: Report, gameId: number | null): boolean {
  const p = tstate.payload;
  const key = `${gameId}:${report.round}`;
  if (endBanners.has(key) || !isOver(p?.status)) return false;
  if (report.captured_by && p?.status === "CAPTURED") {
    const name = label(report.captured_by);
    endBanners.add(key);
    banner(`수수께끼의 인영을 ${name}${particle(name)} 잡았다!\nConflict Resolved.`, END_BANNER_MS);
    return true;
  }
  if (p?.status === "ESCAPED" && tstate.escape && tstate.escape.round === report.round) {
    endBanners.add(key);
    banner(tstate.escape.line, END_BANNER_MS);
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Phaser
// ---------------------------------------------------------------------------
let game: Phaser.Game | null = null;
let sceneMap = ""; // map id currently built in the scene
/** ?preview=: the admin pans around a map, no idle throttling */
let previewMode = false;

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
  previewMode = true;
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
    case "CAPTURED": case "ESCAPED": return "captured";
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
  if (prev?.game_id !== p.game_id) {
    // a new game: whatever the old one was still playing back is over
    pendingPlays.length = 0;
    abortPlayback();
    tstate.history.length = 0; tstate.thinking.clear(); tstate.escape = null; tbus.emit("history:changed", {});
    hideRoundCard();
  }
  // the round log: every report the payload carries (a new device / refresh sees more than the newest round)
  if (p.log?.length) for (const e of p.log) remember(withEntry(e.report, e));
  else if (p.reports?.length) for (const r of p.reports) remember(r);
  if (p.report) remember(p.report);
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
/** finishes the running playOne() early (watchdog, new game) so the queue can never stay stuck */
let abortPlayback: () => void = () => undefined;
/** a playback that is still "running" after this much visible time has hung (a whole round plays in ~15 s) */
const PLAYBACK_WATCHDOG_MS = 60_000;

/** The fugitive's round_resolved / payload log carries the engine's hidden notes: pin them on the report. */
function withEntry(report: Report, entry: Partial<LogEntry> | undefined): Report {
  if (entry) {
    if (entry.fugitive_order !== undefined) report.fugitive_order = entry.fugitive_order;
    if (entry.hidden_events) report.hidden_events = entry.hidden_events;
  }
  return report;
}

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
      // "내 차례": the cue of a round that opened during the playback fires now, when the order bar shows up
      if (cueAfterPlayback) { cueAfterPlayback = false; if (myTurn()) roundCue(); }
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
    hideRoundCard();
    throttle();
    tbus.emit("state:changed", {});
    let finished = false;
    let offReady: (() => void) | null = null;
    let guard = 0;
    const finish = () => {
      if (finished) return;
      finished = true;
      off();
      offReady?.();
      window.clearTimeout(guard);
      abortPlayback = () => undefined;
      markPlayed(gameId, report.round);
      tstate.playing = null;
      if (tstate.payload) tstate.phase = phaseFor(tstate.payload);
      tbus.emit("state:changed", {});
      const ended = endBanner(report, gameId);
      // the round result card for the last queued round (earlier ones are in the round log); after the end banner
      if (pendingPlays.length === 0) showRoundCard(report, ended ? END_BANNER_MS : 0);
      resolve();
    };
    const off = tbus.on("playback:done", ({ report: r }) => { if (r.round === report.round) finish(); });
    // safety net: a stalled animation must never freeze the page in the playback phase. Hidden tabs do not
    // count (the game loop sleeps there), so the timer re-arms until the tab is visible again.
    const watch = () => {
      if (document.hidden) { guard = window.setTimeout(watch, PLAYBACK_WATCHDOG_MS); return; }
      console.warn(`train: playback of R${report.round} did not finish, skipping it`);
      abortPlayback();
    };
    guard = window.setTimeout(watch, PLAYBACK_WATCHDOG_MS);
    abortPlayback = () => {
      if (finished) return;
      tstate.skipping = true;        // whatever is still animating fast-forwards
      tbus.emit("playback:abort", {});
      finish();
    };
    // the scene may still be booting (first payload): wait for it before starting the playback
    const kick = () => tbus.emit("playback:start", { report });
    if (game && game.scene.isActive("Train")) kick();
    else { offReady = tbus.on("scene:ready", () => { offReady?.(); offReady = null; kick(); }); }
  });
}

// ---------------------------------------------------------------------------
// battery: low FPS + paused tweens while nothing plays; the loop sleeps while the tab is hidden (E12).
// The WebSocket and the HUD's setInterval timers are DOM-side and keep running.
// ---------------------------------------------------------------------------
const IDLE_FPS = 10;
let throttled = false;
function throttle(): void {
  if (!game || previewMode) return;
  const want = tstate.phase !== "playback";
  if (want === throttled) return;
  throttled = want;
  const loop = game.loop as unknown as { fpsLimit: number; hasFpsLimit: boolean; _limitRate: number };
  loop.fpsLimit = want ? IDLE_FPS : 0;
  loop.hasFpsLimit = want;
  loop._limitRate = want ? 1000 / IDLE_FPS : 0;
  // Phaser binds step / stepLimitFPS only in start()/wake(): re-bind now so the limit applies without a tab switch
  if (!document.hidden && game.loop.running) { game.loop.sleep(); game.loop.wake(true); }
  tbus.emit("throttle", { on: want });
}
tbus.on("scene:ready", () => throttle());

/** It is my move right now: the order bar is (or is about to be) open and I have not submitted. */
function myTurn(): boolean {
  const p = tstate.payload;
  if (!p || p.status !== "ROUND_OPEN") return false;
  if (isHunter()) return !!p.you && !p.you.order && !p.you.dazed;
  return isFugitive() && !p.fugitive_ai && !p.fugitive_submitted;
}
let cueAfterPlayback = false;
document.addEventListener("visibilitychange", () => {
  if (!game) return;
  if (document.hidden) game.loop.sleep(); else game.loop.wake(true);
});

/** hello/state after a (re)connect: replay every round this browser has not seen to its end, oldest first.
 *  The fugitive payload carries the full engine log (with the hidden notes), everyone else the recent public reports. */
function maybeReplay(p: TrainState): void {
  if (!p.view) return;
  const seen = lastPlayed(p.game_id);
  let reps: Report[] = p.log?.length ? p.log.map((e) => withEntry(e.report, e))
    : p.reports?.length ? p.reports
      : p.report ? [p.report] : [];
  if (seen === 0) reps = reps.slice(-1);   // a browser that never watched this game only needs the newest round
  // the round on screen right now is not "unseen" (a state push mid-playback must not queue it a second time)
  const playing = tstate.playing?.round ?? 0;
  for (const rep of reps) if (rep.round > seen && rep.round !== playing) void play(rep, p.game_id);
}

type OrderMsg = { type: "move" | "search" | "scan" | "stay"; target: string | null } | null;

function wireSocket(): void {
  tsocket.on("open", () => show("hud-conn", false));
  tsocket.on("close", (m: { code: number }) => {
    if (m.code === 4401) {
      // the stored token is dead (logged in elsewhere / token rotated): no retry, ask for the nickname again
      show("hud-conn", false);
      toast(S.loginLost(state.id ?? ""), 7000);
      openAccount();
      return;
    }
    show("hud-conn", !!state.token); // a deliberate close (account switch) is not a lost connection
  });
  tsocket.on("hello", (m: { role: string; state: TrainState }) => { applyState(m.state); maybeReplay(m.state); });
  tsocket.on("state", (m: { state: TrainState }) => { applyState(m.state); maybeReplay(m.state); });
  tsocket.on("round_open", (m: { round: number; deadline_ts: number; vote_after_ts: number | null }) => {
    const p = tstate.payload;
    if (!p) return;
    p.status = "ROUND_OPEN"; p.deadline_ts = m.deadline_ts; p.grace_until = null; p.paused_remaining = null; p.vote_after_ts = m.vote_after_ts; p.votes = {};
    tstate.thinking.clear();
    applyState(p);
    // round_open lands right after round_resolved: while the previous round still plays, wait for the order bar
    if (draining || tstate.phase === "playback") cueAfterPlayback = true;
    else if (myTurn()) roundCue();
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
    toast(`${label(m.id)}: ${m.order ? (m.order.type === "move" ? `이동 → ${m.order.target}` : ORDER_KO[m.order.type] ?? m.order.type) : "제출 취소"}`, 2500);
    applyState(p);
  });
  tsocket.on("fugitive_submitted", (m: { submitted: boolean; round: number }) => {
    const p = tstate.payload;
    if (!p || (p.round_no ?? m.round) !== m.round) return;
    p.fugitive_submitted = m.submitted;
    // the message carries no order: the fugitive's own REST response fills p.fugitive.order (fugitive.ts)
    if (p.fugitive && !m.submitted) p.fugitive.order = null;
    tstate.thinking.delete("fugitive");
    applyState(p);
  });
  tsocket.on("deadline", (m: { deadline_ts: number; reason: string; paused_remaining?: number | null; grace_until?: number | null }) => {
    const p = tstate.payload;
    if (!p) return;
    if (m.reason === "grace") {
      p.grace_until = m.deadline_ts;
      const min = Math.max(1, Math.round((m.deadline_ts - Date.now() / 1000) / 60));
      toast(isFugitive() && !p.fugitive_ai
        ? `승무원 전원 제출 · 내 제출을 기다리는 중 · 유예 ${min}분`
        : `승무원 전원 제출 · 도주자 제출을 기다리는 중 · 유예 ${min}분`, 4000);
    }
    else if (m.reason === "grace_cancel") { p.grace_until = null; p.deadline_ts = m.deadline_ts; toast("제출이 취소되어 유예가 풀렸어요"); }
    else {
      if (m.grace_until !== undefined) p.grace_until = m.grace_until;
      p.deadline_ts = m.grace_until != null ? Math.max(m.deadline_ts, p.deadline_ts ?? 0) : m.deadline_ts;
      if (m.paused_remaining != null) p.paused_remaining = m.paused_remaining;
      toast(p.grace_until != null ? "유예가 연장됐어요" : "마감이 연장됐어요");
    }
    applyState(p);
  });
  tsocket.on("vote", (m: { target: string; voters: string[]; need: number; passed: boolean; void?: boolean }) => {
    const p = tstate.payload;
    if (!p) return;
    p.votes = p.votes ?? {};
    if (m.passed || m.void) delete p.votes[m.target]; else p.votes[m.target] = m.voters;
    p.need = m.need;
    if (m.passed) toast(`${label(m.target)}은(는) 투표로 이번 라운드 대기 처리됐어요`);
    applyState(p);
  });
  tsocket.on("round_resolved", (m: { report: Report; state: TrainState; log_entry?: LogEntry }) => {
    // queue the playback first: it flips the phase to "playback" so applyState does not teleport the crew to
    // their new rooms (scene:sync) a frame before the walk starts from the old ones
    void play(withEntry(m.report, m.log_entry), m.state.game_id);
    applyState(m.state);
    if (document.hidden) tstate.unseenResult = true;
  });
  tbus.on("playback:skip", () => { tstate.skipping = true; });
  tbus.on("playback:replay", ({ report }) => { if (tstate.phase !== "playback") void play(report, tstate.payload?.game_id ?? null); });
  tsocket.on("captured", (m: { room: string }) => {
    const p = tstate.payload;
    if (p) { p.status = "CAPTURED"; if (p.view) p.view.capture_room = m.room; }
    // the capture line itself is shown when the playback finishes (play())
  });
  tsocket.on("escaped", (m: { round: number; line: string }) => {
    const p = tstate.payload;
    tstate.escape = { round: m.round, line: m.line };
    if (p) { p.status = "ESCAPED"; applyState(p); }
    // normally that round is still playing back (the banner follows it); otherwise show it now
    const queued = pendingPlays.some((x) => x.report.round === m.round);
    const key = `${p?.game_id ?? null}:${m.round}`;
    if (tstate.playing?.round !== m.round && !queued && !endBanners.has(key)) { endBanners.add(key); banner(m.line, END_BANNER_MS); }
  });
  tsocket.on("started", (m: { line: string }) => banner(m.line, 3500));
  tsocket.on("bot_thinking", (m: { id: string; round: number }) => {
    tstate.thinking.add(m.id);
    tbus.emit("state:changed", {});
    // everyone sees "(판단 중)" on the HUD; the toast is for the controls (admin) and the fugitive only
    if (isFugitive() || tstate.payload?.admin) toast(`${m.id === "fugitive" ? "{target}" : "{chat}"} ${label(m.id)} · R${m.round} 판단 중…`, 2500);
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

/** Switch the page to the stored account `id` (null = none): token, HUD chip, socket. Whatever the previous account
 *  saw of the game is dropped; the server's hello on the new socket rebuilds lobby / round / scene for the new role. */
async function loadAccount(id: string | null): Promise<void> {
  const acct = id ? storage.accounts().find((a) => a.id === id) ?? null : null;
  tsocket.close();
  state.token = acct?.token ?? null;
  state.id = acct?.id ?? null;
  $("hud-id-val").textContent = acct?.id ?? "–";
  if (tstate.payload) applyState({ game_id: null, status: "IDLE", role: "spectator", you: null });
  if (!acct) {
    show("loading", false);
    toast(S.needLogin, 6000);
    openAccount();
    return;
  }
  if (previewMode) { location.reload(); return; } // the preview is wired once at boot; start over as the new account
  tsocket.connect(acct.token);
}

async function boot(): Promise<void> {
  // a recovery link ?t=TOKEN (same as the room game): verify → store → strip from the URL
  const recovered = storage.takeRecoveryToken();
  if (recovered) {
    try {
      const who = await roomApi.meWith(recovered);
      storage.addAccount({ id: who.id, token: recovered });
      toast(`${who.id} 계정으로 들어왔어요`);
    } catch {
      toast("복구 링크가 유효하지 않아요");
    }
  }
  const acct = storage.activeAccount();
  $("hud-id-val").textContent = acct?.id ?? "–";
  state.token = acct?.token ?? null;
  state.id = acct?.id ?? null;
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
    previewMode = true;
    initAccount({ onSwitch: loadAccount });
    if (!acct) { await loadAccount(null); return; }
    await preview(pv);
    return;
  }

  initFolds();
  initAccount({ onSwitch: loadAccount });
  initHud();
  initLobby();
  initSubmit();
  initFugitiveBar();
  initVote();
  initReport();
  initAdmin();
  initRoundLog();
  initRoundCard();
  initHelp();
  initCues();
  void initTrainBgm();
  const bgmBtn = () => { $("btn-bgm-val").textContent = isMuted() ? "소리 꺼짐" : "소리"; };
  $("btn-bgm").onclick = () => { toggleMute(); bgmBtn(); };
  bgmBtn();
  // the account chip: log in / switch (the claim panel for the admin-to-be hangs off that panel)
  $("hud-id").onclick = () => openAccount();
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
  await loadAccount(acct?.id ?? null);
}

void boot();
