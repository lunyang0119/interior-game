import Phaser from "phaser";
import { api, ApiError, msgFor } from "./api";
import { initBgm } from "./audio/bgm";
import { initSfx, play, SFX, SFX_VOL } from "./audio/sfx";
import { bus, toast } from "./bus";
import { DOCK_ROOM, makeCatalog, MAP_ROOM, placeName, unlockerOf } from "./catalog";
import { BootScene } from "./scenes/BootScene";
import { DockScene } from "./scenes/DockScene";
import { MapScene, type MapSceneData } from "./scenes/MapScene";
import { RoomScene, type RoomSceneData } from "./scenes/RoomScene";
import { applyComfort, applyProgress, state } from "./state";
import * as storage from "./storage";
import { initAccounts } from "./ui/accounts";
import { initAvatarEditor } from "./ui/avatarEditor";
import { initBoard } from "./ui/board";
import { initContextMenu } from "./ui/contextMenu";
import { initLog } from "./ui/log";
import { initNote } from "./ui/note";
import { $, initHud, renderIdentity, show } from "./ui/hud";
import { initShop } from "./ui/shop";
import { socket } from "./ws";
import { refreshThemeLink } from "./assets";

/** Accounts that may walk into locked places (debugging). The server still refuses to place anything there. */
const DEBUG_IDS = new Set(["안나"]);

/** Fetch the restoration picture (public endpoint; also refreshed by every ws `progress` message). */
async function loadProgress(): Promise<void> {
  try {
    const r = await api.rooms();
    applyProgress(Object.fromEntries(r.rooms.filter((x) => x.progress).map((x) => [x.id, x.progress!])), r.locked);
    applyComfort(Object.assign({}, ...r.rooms.map((x) => x.comfort ?? {})));
  } catch { /* offline: keep what we have */ }
}

/** True when `target` may not be entered yet; shows why (which room's stage opens it). */
function blockedByLock(target: string): boolean {
  if (!state.locked.has(target) || (state.id && DEBUG_IDS.has(state.id))) return false;
  const cat = state.catalog!;
  const u = unlockerOf(cat, target);
  toast(u ? `아직 들어갈 수 없어요 — ${placeName(cat, u.room.id)} '${u.stage.name}' 단계를 끝내면 열려요` : "아직 들어갈 수 없어요");
  return true;
}

async function loadAccount(id: string | null): Promise<void> {
  state.id = null;
  state.token = null;
  state.balance = 0;
  socket.close();
  const acct = id ? storage.accounts().find((a) => a.id === id) ?? null : null;
  if (!acct) { renderIdentity(); return; }
  state.token = acct.token;
  try {
    const me = await api.me();
    state.id = me.id;
    state.balance = me.balance;
    state.contributions = me.contributions;
    state.avatar = me.avatar;
    bus.emit("money", { balance: me.balance });
    // one socket per account, owned here so walking between rooms never drops it
    socket.connect(acct.token);
  } catch (e) {
    state.token = null;
    if (e instanceof ApiError && e.status === 401) {
      toast(`${acct.id} 로그인이 풀렸어요 (다른 기기에서 들어왔을 수 있어요). 닉네임을 다시 입력해서 들어와주세요.`);
    } else {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  }
  renderIdentity();
}

type SceneName = "Room" | "Map" | "Dock";

async function boot(): Promise<void> {
  // 1. recovery link ?t=TOKEN → verify → store → strip from URL
  const recovered = storage.takeRecoveryToken();
  if (recovered) {
    try {
      const me = await api.meWith(recovered);
      storage.addAccount({ id: me.id, token: recovered });
      toast(`${me.id} 계정으로 들어왔어요`);
    } catch {
      toast("복구 링크가 유효하지 않아요");
    }
  }

  // 2. catalog (public) + pixel font (so the first frame already uses it; ignore failures)
  const [cat] = await Promise.all([
    api.catalog(),
    document.fonts.load('16px "Stardust"').catch(() => undefined),
    document.fonts.load('16px "Label"').catch(() => undefined),
  ]);
  state.catalog = makeCatalog(cat);
  refreshThemeLink(); // versioned theme.css: beats the day-long /media cache after `preprocess.py ui`
  const base = state.catalog.room;
  const hasMap = !!state.catalog.map;
  state.roomId = base.id;

  // 3. active account (+ the restoration picture, which does not need one)
  await Promise.all([loadAccount(storage.activeAccount()?.id ?? null), loadProgress()]);

  // 4. UI
  initHud();
  initAccounts();
  initAvatarEditor();
  initShop();
  initContextMenu();
  initNote();
  initLog();
  initBoard();
  void initBgm();
  void initSfx();

  // 5. game
  // the canvas is the whole window; each scene's camera shows a window of its world (CameraController)
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: "game",
    width: window.innerWidth,
    height: window.innerHeight,
    pixelArt: true,
    roundPixels: true,
    backgroundColor: "#1b1b24",
    scale: { mode: Phaser.Scale.RESIZE, autoCenter: Phaser.Scale.NO_CENTER },
    input: { activePointers: 2 }, // two fingers: pan + pinch zoom
    scene: [BootScene, RoomScene, MapScene, DockScene],
  });
  (window as unknown as { __game: Phaser.Game }).__game = game; // debugging / e2e hooks

  const active = (): SceneName => game.scene.isActive("Dock") ? "Dock" : game.scene.isActive("Map") ? "Map" : "Room";
  const roomData = (room?: string, spawn?: { x: number; y: number }): RoomSceneData =>
    ({ id: state.id, room: room ?? (state.catalog!.rooms.has(state.roomId) ? state.roomId : base.id), spawn });

  /** Only one world scene runs at a time; the DOM bars follow via scene:changed. The loading overlay covers the
   *  switch until the scene says scene:ready (or a safety timer runs out). */
  let loadingTimer: number | null = null;
  const goto = (name: SceneName, data?: RoomSceneData | MapSceneData): void => {
    for (const s of ["Room", "Map", "Dock"] as SceneName[]) if (s !== name && game.scene.isActive(s)) game.scene.stop(s);
    show("loading", true);
    if (loadingTimer !== null) clearTimeout(loadingTimer);
    loadingTimer = window.setTimeout(() => show("loading", false), 2500);
    if (name !== "Dock") { if (location.hash === "#dock") history.replaceState(null, "", location.pathname + location.search); }
    else location.hash = "dock";
    game.scene.start(name, data);
    bus.emit("scene:changed", { scene: name.toLowerCase() as "room" | "map" | "dock" });
  };
  const goRoom = (room?: string, spawn?: { x: number; y: number }) => goto("Room", roomData(room, spawn));
  const goMap = (from?: string) => { if (hasMap) goto("Map", { from }); else { toast("바깥은 아직 준비 중이에요"); } };
  const goDock = () => goto("Dock");

  game.scene.start("Boot", roomData());

  bus.on("account:switch", async ({ id }) => {
    await Promise.all([loadAccount(id || null), loadProgress()]);
    const cur = active();
    if (cur === "Dock") goDock(); else if (cur === "Map") goMap(); else goRoom();
  });
  // a socket (re)connect may have missed a `progress` broadcast
  socket.on("open", () => void loadProgress());

  // walking onto an exit inside a room (locked places come from the restoration stages, see restore.py)
  bus.on("room:exit", ({ from, to, spawn }) => {
    if (blockedByLock(to)) return;
    if (to === MAP_ROOM) { goMap(from); return; }
    if (!state.catalog?.rooms.has(to)) { toast("아직 갈 수 없는 곳이에요"); return; }
    goRoom(to, spawn);
  });

  // said yes at a door on the map
  bus.on("map:enter", ({ room }) => {
    if (blockedByLock(room)) return;
    if (room === DOCK_ROOM) { goDock(); return; }
    if (!state.catalog?.rooms.has(room)) { toast("아직 갈 수 없는 곳이에요"); return; }
    goRoom(room);
  });
  // the server refused a presence enter (e.g. a stage was reset by hand): say so, the scene itself is harmless
  socket.on("error", (m: { code: string; room?: string }) => {
    if (m.code === "room_locked") toast(`${m.room ? placeName(state.catalog!, m.room) : "거기"}(은)는 아직 잠겨 있어요`);
  });

  // dock: 나가기 goes back to the map (or the base room when there is no map yet); #dock deep-links in
  bus.on("dock:enter", () => { if (active() !== "Dock") goDock(); });
  bus.on("dock:exit", () => { if (active() !== "Dock") return; if (hasMap) goMap(DOCK_ROOM); else goRoom(); });
  window.addEventListener("hashchange", () => { if (location.hash === "#dock") bus.emit("dock:enter"); else if (active() === "Dock") bus.emit("dock:exit"); });
  // (#dock on load is handled by BootScene so the room scene never starts underneath)

  // connection chip: "다시 연결 중" while the socket is down; a replaced/rotated session stays down for good
  socket.on("open", () => bus.emit("net:state", { online: true }));
  socket.on("close", (m: { code?: number }) => {
    if (!state.token) return; // no account: nothing to reconnect
    bus.emit("net:state", { online: false, reason: m.code === 4000 ? "replaced" : m.code === 4001 ? "rotated" : undefined });
  });
  bus.on("account:switch", () => bus.emit("net:state", { online: true })); // hide until the new socket reports

  socket.on("cat", (m: { player: string; first_today: boolean }) => {
    if (m.player === state.id) return; // my own pet is answered by the room scene
    play(SFX.meow, { volume: SFX_VOL.ui });
    toast(`${m.player}가 고양이를 쓰다듬었어요`);
  });
  socket.on("fish", (m) => {
    if (m.id === state.id) return; // my own result is shown by the dock scene
    if (active() === "Dock") bus.emit("loot:got", { ok: true, kind: "fish", id: m.loot, name: m.name, value: m.value, who: m.id });
    else toast(`${m.id}가 부두에서 ${m.name}을(를) 낚았어요${m.value > 0 ? ` (+${m.value}💰)` : ""}`);
  });

  show("loading", false);
  if (!state.id) show("panel-accounts", true);
}

boot().catch((e) => {
  $("loading").textContent = `시작 실패. 게오에게 멘션주세요: ${e instanceof ApiError ? msgFor(e.code) : e}`;
});
