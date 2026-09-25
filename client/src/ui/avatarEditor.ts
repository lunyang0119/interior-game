import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { AVATAR_LAYERS, DEFAULT_LOOK, type AvatarLook, type LayerSpec } from "../catalog";
import { catalog, state } from "../state";
import { $, show, togglePanel } from "./hud";

const SCALE = 4;

let draft: AvatarLook = { ...DEFAULT_LOOK };
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

let previewSeq = 0;

async function preview(): Promise<void> {
  const chars = catalog().chars;
  const canvas = $("avatar-preview") as HTMLCanvasElement;
  const ctx = canvas.getContext("2d")!;
  const seq = ++previewSeq;
  const frame = chars.anims["idle_down"]?.[0] ?? 0;
  const images: HTMLImageElement[] = [];
  for (const layer of chars.layerOrder) {
    const spec = chars.layers[layer];
    const count = spec?.count ?? 0;
    if (count <= 0) continue;
    const idx = Math.min((draft as unknown as Record<string, number>)[layer] ?? 0, count - 1);
    if (spec.none && idx === 0) continue;
    images.push(await sheet(layer, idx));
  }
  if (seq !== previewSeq) return; // a newer preview started while loading
  canvas.width = chars.frameW * SCALE;
  canvas.height = chars.frameH * SCALE;
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (const im of images) {
    ctx.drawImage(im, frame * chars.frameW, 0, chars.frameW, chars.frameH, 0, 0, canvas.width, canvas.height);
  }
}

/** Style groups for a layer: with `groups` from the manifest, else every index is its own style. */
function groupsOf(spec: LayerSpec): number[][] {
  return spec.groups ?? Array.from({ length: spec.count }, (_, i) => [i]);
}

const refreshers: (() => void)[] = [];

function refreshAll(): void {
  for (const r of refreshers) r();
  void preview();
}

function stepper(label: string, get: () => string, onStep: (d: number) => void): HTMLElement {
  const row = document.createElement("div");
  row.className = "layer";
  const minus = document.createElement("button");
  minus.textContent = "◀";
  const text = document.createElement("span");
  const plus = document.createElement("button");
  plus.textContent = "▶";
  const refresh = () => { text.textContent = `${label}  ${get()}`; };
  refreshers.push(refresh);
  minus.addEventListener("click", () => { onStep(-1); refreshAll(); });
  plus.addEventListener("click", () => { onStep(1); refreshAll(); });
  row.append(minus, text, plus);
  refresh();
  return row;
}

function renderControls(): void {
  const chars = catalog().chars;
  const box = $("avatar-layers");
  box.innerHTML = "";
  refreshers.length = 0;
  for (const layer of AVATAR_LAYERS) {
    const spec = chars.layers[layer];
    if (!spec || spec.count <= 0) continue;
    const groups = groupsOf(spec);
    const label = spec.label ?? layer;
    const find = () => {
      const idx = draft[layer];
      const g = groups.findIndex((grp) => grp.includes(idx));
      return g < 0 ? { g: 0, c: 0 } : { g, c: groups[g].indexOf(idx) };
    };
    const styleText = () => {
      const { g } = find();
      return spec.none && g === 0 ? `없음 (1/${groups.length})` : `${g + 1}/${groups.length}`;
    };
    // style row: jump between groups (keep colour slot when the next style has it)
    box.appendChild(stepper(label, styleText, (d) => {
      const { g, c } = find();
      const ng = (g + d + groups.length) % groups.length;
      draft[layer] = groups[ng][Math.min(c, groups[ng].length - 1)];
    }));
    // colour row only when some style has colour variants
    if (groups.some((grp) => grp.length > 1)) {
      const colorRow = stepper(`${label} 색`, () => {
        const { g, c } = find();
        return groups[g].length > 1 ? `${c + 1}/${groups[g].length}` : "–";
      }, (d) => {
        const { g, c } = find();
        const grp = groups[g];
        draft[layer] = grp[(c + d + grp.length) % grp.length];
      });
      colorRow.classList.add("sub");
      box.appendChild(colorRow);
    }
  }
  if (!box.children.length) box.textContent = "바꿀 수 있는 레이어가 없어요 (preprocess build 필요)";
}

export function initAvatarEditor(): void {
  $("btn-avatar").addEventListener("click", () => {
    if (!state.id) { toast("먼저 계정을 골라주세요"); return; }
    draft = { ...DEFAULT_LOOK, ...state.avatar };
    renderControls();
    void preview();
    togglePanel("panel-avatar");
  });
  $("avatar-random").addEventListener("click", () => {
    const chars = catalog().chars;
    for (const layer of AVATAR_LAYERS) {
      const n = chars.layers[layer]?.count ?? 0;
      if (n > 0) draft[layer] = Math.floor(Math.random() * n);
    }
    renderControls();
    void preview();
  });
  $("avatar-save").addEventListener("click", async () => {
    try {
      const r = await api.putAvatar(draft);
      state.avatar = r.avatar;
      bus.emit("avatar:saved", r.avatar);
      show("panel-avatar", false);
      toast("아바타를 저장했어요");
    } catch (e) {
      toast(e instanceof ApiError ? msgFor(e.code) : String(e));
    }
  });
}
