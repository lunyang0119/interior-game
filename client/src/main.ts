import Phaser from "phaser";
import { api, ApiError, msgFor } from "./api";
import { initBgm } from "./audio/bgm";
import { bus, toast } from "./bus";
import { DOCK_ROOM, makeCatalog, MAP_ROOM } from "./catalog";
import { CELL } from "./room/grid";
import { BootScene } from "./scenes/BootScene";
import { DockScene } from "./scenes/DockScene";
import { MapScene, type MapSceneData } from "./scenes/MapScene";
import { RoomScene, type RoomSceneData } from "./scenes/RoomScene";
import { state } from "./state";
import * as storage from "./storage";
import { initAccounts } from "./ui/accounts";
import { initAvatarEditor } from "./ui/avatarEditor";
import { initContextMenu } from "./ui/contextMenu";
import { $, initHud, renderIdentity, show } from "./ui/hud";
import { initShop } from "./ui/shop";
import { socket } from "./ws";

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
  const base = state.catalog.room;
  const hasMap = !!state.catalog.map;
  state.roomId = base.id;

  // 3. active account
  await loadAccount(storage.activeAccount()?.id ?? null);

  // 4. UI
  initHud();
  initAccounts();
  initAvatarEditor();
  initShop();
  initContextMenu();
  void initBgm();

  // 5. game
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: "game",
    width: base.cols * CELL,
    height: base.rows * CELL,
    pixelArt: true,
    roundPixels: true,
    backgroundColor: "#1b1b24",
    scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    input: { activePointers: 1 },
    scene: [BootScene, RoomScene, MapScene, DockScene],
  });
  (window as unknown as { __game: Phaser.Game }).__game = game; // debugging / e2e hooks

  const active = (): SceneName => game.scene.isActive("Dock") ? "Dock" : game.scene.isActive("Map") ? "Map" : "Room";
  const roomData = (room?: string, spawn?: { x: number; y: number }): RoomSceneData =>
    ({ id: state.id, room: room ?? (state.catalog!.rooms.has(state.roomId) ? state.roomId : base.id), spawn });

  /** Only one world scene runs at a time; the DOM bars follow via scene:changed. */
  const goto = (name: SceneName, data?: RoomSceneData | MapSceneData): void => {
    for (const s of ["Room", "Map", "Dock"] as SceneName[]) if (s !== name && game.scene.isActive(s)) game.scene.stop(s);
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
    await loadAccount(id || null);
    const cur = active();
    if (cur === "Dock") goDock(); else if (cur === "Map") goMap(); else goRoom();
  });

  // walking onto an exit inside a room
  bus.on("room:exit", ({ from, to, spawn }) => {
    if (to === MAP_ROOM) {
      if (from === base.id && state.ruined > 0) { toast(`${base.name || "여관"} 정리가 다 끝나면 바깥으로 나갈 수 있어요 (부서진 물건 ${state.ruined}개 남음)`); return; }
      goMap(from);
      return;
    }
    if (!state.catalog?.rooms.has(to)) { toast("아직 갈 수 없는 곳이에요"); return; }
    goRoom(to, spawn);
  });

  // said yes at a door on the map
  bus.on("map:enter", ({ room }) => {
    if (room === DOCK_ROOM) { goDock(); return; }
    if (!state.catalog?.rooms.has(room)) { toast("아직 갈 수 없는 곳이에요"); return; }
    goRoom(room);
  });

  // dock: 나가기 goes back to the map (or the base room when there is no map yet); #dock deep-links in
  bus.on("dock:enter", () => { if (active() !== "Dock") goDock(); });
  bus.on("dock:exit", () => { if (active() !== "Dock") return; if (hasMap) goMap(DOCK_ROOM); else goRoom(); });
  window.addEventListener("hashchange", () => { if (location.hash === "#dock") bus.emit("dock:enter"); else if (active() === "Dock") bus.emit("dock:exit"); });
  if (location.hash === "#dock") bus.emit("dock:enter");

  show("loading", false);
  if (!state.id) show("panel-accounts", true);
}

boot().catch((e) => {
  $("loading").textContent = `시작 실패. 게오에게 멘션주세요: ${e instanceof ApiError ? msgFor(e.code) : e}`;
});
