/** /train/ entry. Shares the account (storage.ts) and the catalog's asset version with the room game, nothing else.
 *  Phase 2a: admin map preview (`?preview=<map_id>`) rendered from room data only. */

import Phaser from "phaser";
import { api as roomApi } from "../api";
import { makeCatalog } from "../catalog";
import { state } from "../state";
import * as storage from "../storage";
import { refreshThemeLink } from "../assets";
import { api, ApiError, msgFor, type MapSummary } from "./api";
import { tbus } from "./bus";
import { TrainBoot } from "./scenes/TrainBoot";
import { TrainScene } from "./scenes/TrainScene";
import { S } from "./strings";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

let toastTimer: number | null = null;
function toast(text: string, ms = 2600): void {
  const el = $("toast");
  el.textContent = text;
  el.classList.remove("hidden");
  if (toastTimer !== null) clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el.classList.add("hidden"), ms);
}

function show(id: string, on = true): void { $(id).classList.toggle("hidden", !on); }

let game: Phaser.Game | null = null;

function startGame(data: object): void {
  if (game) { game.scene.getScene("Train")?.scene.restart(data); return; }
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

/** Resolve the fugitive/admin role, asking for the secret if this account does not hold it. */
async function ensureAdmin(): Promise<boolean> {
  try {
    const st = await api.state();
    if (st.role === "fugitive") return true;
  } catch (e) {
    toast(msgFor(e));
    return false;
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
      $("hud-title-val").textContent = S.previewTitle(m.id, m.rooms.length);
      startGame({ map: m, preview: true });
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
  await open(mapId);
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
  tbus.on("room:tap", ({ room }) => { if (room) toast(room, 900); });
  tbus.on("scene:ready", () => show("loading", false));

  const params = new URLSearchParams(location.search);
  const pv = params.get("preview");
  if (pv) {
    await preview(pv);
    return;
  }
  // Phase 2b: lobby / rounds. Until then the page is the preview only.
  show("loading", false);
  toast("아직 준비 중이에요. ?preview=car2077_12 로 맵을 볼 수 있어요", 6000);
}

void boot();
