import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { AVATAR_LAYERS, type AvatarLook } from "../catalog";
import { catalog, state } from "../state";
import { $, show, togglePanel } from "./hud";

const LABELS: Record<string, string> = { skin: "캐릭터", hair: "머리", hair_color: "머리색", outfit: "옷", acc: "악세서리" };
const SCALE = 4;

let draft: AvatarLook = { skin: 0, hair: 0, hair_color: 0, outfit: 0, acc: 0 };
const imgCache = new Map<string, Promise<HTMLImageElement>>();

function sheet(layer: string, idx: number): Promise<HTMLImageElement> {
  const url = `/gen/chars/${layer}/${idx}.png`;
  let p = imgCache.get(url);
  if (!p) {
    p = new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = url; });
    imgCache.set(url, p);
  }
  return p;
}

async function preview(): Promise<void> {
  const chars = catalog().chars;
  const canvas = $("avatar-preview") as HTMLCanvasElement;
  const ctx = canvas.getContext("2d")!;
  canvas.width = chars.frameW * SCALE;
  canvas.height = chars.frameH * SCALE;
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const frame = chars.anims["idle_down"]?.[0] ?? 0;
  for (const layer of chars.layerOrder) {
    const count = chars.layers[layer]?.count ?? 0;
    if (count <= 0) continue;
    const idx = Math.min((draft as unknown as Record<string, number>)[layer] ?? 0, count - 1);
    const im = await sheet(layer, idx);
    ctx.drawImage(im, frame * chars.frameW, 0, chars.frameW, chars.frameH, 0, 0, canvas.width, canvas.height);
  }
}

function renderControls(): void {
  const chars = catalog().chars;
  const box = $("avatar-layers");
  box.innerHTML = "";
  for (const layer of AVATAR_LAYERS) {
    const count = chars.layers[layer]?.count ?? 0;
    if (count <= 0) continue;
    const row = document.createElement("div");
    row.className = "layer";
    const minus = document.createElement("button");
    minus.textContent = "−";
    const label = document.createElement("span");
    const plus = document.createElement("button");
    plus.textContent = "+";
    const refresh = () => { label.textContent = `${LABELS[layer] ?? layer}  ${draft[layer] + 1}/${count}`; void preview(); };
    minus.addEventListener("click", () => { draft[layer] = (draft[layer] - 1 + count) % count; refresh(); });
    plus.addEventListener("click", () => { draft[layer] = (draft[layer] + 1) % count; refresh(); });
    row.append(minus, label, plus);
    box.appendChild(row);
    refresh();
  }
  if (!box.children.length) box.textContent = "바꿀 수 있는 레이어가 아직 없어 (정식 팩 오면 생김)";
}

export function initAvatarEditor(): void {
  $("btn-avatar").addEventListener("click", () => {
    if (!state.id) { toast("먼저 계정을 골라"); return; }
    draft = { ...state.avatar };
    renderControls();
    void preview();
    togglePanel("panel-avatar");
  });
  $("avatar-save").addEventListener("click", async () => {
    try {
      const r = await api.putAvatar(draft);
      state.avatar = r.avatar;
      bus.emit("avatar:saved", r.avatar);
      show("panel-avatar", false);
      toast("아바타 저장됨");
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  });
}
