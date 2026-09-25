import Phaser from "phaser";
import { api, ApiError, msgFor } from "./api";
import { bus, toast } from "./bus";
import { makeCatalog } from "./catalog";
import { CELL } from "./room/grid";
import { BootScene } from "./scenes/BootScene";
import { RoomScene } from "./scenes/RoomScene";
import { state } from "./state";
import * as storage from "./storage";
import { initAccounts } from "./ui/accounts";
import { initAvatarEditor } from "./ui/avatarEditor";
import { initContextMenu } from "./ui/contextMenu";
import { $, initHud, renderIdentity, show } from "./ui/hud";
import { initShop } from "./ui/shop";

async function loadAccount(id: string | null): Promise<void> {
  state.id = null;
  state.token = null;
  state.balance = 0;
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
  } catch (e) {
    state.token = null;
    if (e instanceof ApiError && e.status === 401) {
      toast(`${acct.id} 토큰이 더 이상 유효하지 않아. 계정에서 지우고 복구 링크로 다시 들어와`);
    } else {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  }
  renderIdentity();
}

async function boot(): Promise<void> {
  // 1. recovery link ?t=TOKEN → verify → store → strip from URL
  const recovered = storage.takeRecoveryToken();
  if (recovered) {
    try {
      const me = await api.meWith(recovered);
      storage.addAccount({ id: me.id, token: recovered });
      toast(`${me.id} 계정으로 들어왔어`);
    } catch {
      toast("복구 링크가 유효하지 않아");
    }
  }

  // 2. catalog (public)
  state.catalog = makeCatalog(await api.catalog());
  const room = state.catalog.room;

  // 3. active account
  await loadAccount(storage.activeAccount()?.id ?? null);

  // 4. UI
  initHud();
  initAccounts();
  initAvatarEditor();
  initShop();
  initContextMenu();

  // 5. game
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: "game",
    width: room.cols * CELL,
    height: room.rows * CELL,
    pixelArt: true,
    roundPixels: true,
    backgroundColor: "#1b1b24",
    scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    input: { activePointers: 1 },
    scene: [BootScene, RoomScene],
  });
  game.scene.start("Boot", { id: state.id });

  bus.on("account:switch", async ({ id }) => {
    await loadAccount(id || null);
    game.scene.getScene("Room").scene.restart({ id: state.id });
  });

  show("loading", false);
  if (!state.id) show("panel-accounts", true);
}

boot().catch((e) => {
  $("loading").textContent = `시작 실패: ${e instanceof ApiError ? msgFor(e.code) : e}`;
});
