import { api, ApiError, msgFor } from "../api";
import { bus, toast } from "../bus";
import { AVATAR_LAYERS, DEFAULT_LOOK, drawList, type AvatarLook, type LayerSpec } from "../catalog";
import { catalog, state } from "../state";
import { $, guard, show, togglePanel } from "./hud";

const SCALE = 4;
const REPEAT_DELAY_MS = 400;
const REPEAT_EVERY_MS = 110;

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
  for (const { layer, idx } of drawList(draft, chars)) images.push(await sheet(layer, idx));
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
const dimmers: (() => void)[] = [];

/** True when an exclusive layer (premade preset) is active, so the other layers are not drawn. */
function presetActive(): boolean {
  const chars = catalog().chars;
  return drawList(draft, chars).some((d) => chars.layers[d.layer]?.exclusive);
}

/** Turn every exclusive layer off so the layered look shows again. */
function leavePreset(): void {
  const chars = catalog().chars;
  for (const layer of AVATAR_LAYERS) {
    const spec = chars.layers[layer];
    if (spec?.exclusive) draft[layer] = spec.none ?? 0;
  }
}

function refreshAll(): void {
  for (const r of refreshers) r();
  for (const d of dimmers) d();
  void preview();
}

/** Tap = one step; hold = auto-repeat (hair alone has hundreds of entries). */
function repeatButton(glyph: string, onStep: () => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.textContent = glyph;
  let delay: number | null = null;
  let timer: number | null = null;
  let repeated = false;
  const stop = () => {
    if (delay !== null) clearTimeout(delay);
    if (timer !== null) clearInterval(timer);
    delay = timer = null;
  };
  b.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    repeated = false;
    stop();
    delay = window.setTimeout(() => {
      repeated = true;
      onStep();
      timer = window.setInterval(onStep, REPEAT_EVERY_MS);
    }, REPEAT_DELAY_MS);
  });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(ev, stop);
  // the click that follows a hold must not add one more step
  b.addEventListener("click", () => { if (!repeated) onStep(); repeated = false; });
  return b;
}

function stepper(label: string, get: () => string, onStep: (d: number) => void): HTMLElement {
  const row = document.createElement("div");
  row.className = "layer";
  const text = document.createElement("span");
  const refresh = () => { text.textContent = `${label}  ${get()}`; };
  refreshers.push(refresh);
  const minus = repeatButton("◀", () => { onStep(-1); refreshAll(); });
  const plus = repeatButton("▶", () => { onStep(1); refreshAll(); });
  row.append(minus, text, plus);
  refresh();
  return row;
}

function renderControls(): void {
  const chars = catalog().chars;
  const box = $("avatar-layers");
  box.innerHTML = "";
  refreshers.length = 0;
  dimmers.length = 0;
  for (const layer of AVATAR_LAYERS) {
    const spec = chars.layers[layer];
    if (!spec || spec.count <= 0) continue;
    const groups = groupsOf(spec);
    const label = spec.label ?? layer;
    // layers hidden by an active exclusive layer (preset) are greyed out; touching one leaves the preset
    const dimmable = !spec.exclusive;
    const wake = () => { if (dimmable && presetActive()) leavePreset(); };
    const find = () => {
      const idx = draft[layer];
      const g = groups.findIndex((grp) => grp.includes(idx));
      return g < 0 ? { g: 0, c: 0 } : { g, c: groups[g].indexOf(idx) };
    };
    const noneIdx = spec.none;
    const noneGroup = noneIdx === undefined ? -1 : groups.findIndex((grp) => grp.includes(noneIdx));
    const styleText = () => {
      const { g } = find();
      return g === noneGroup ? `없음 (${g + 1}/${groups.length})` : `${g + 1}/${groups.length}`;
    };
    // style row: jump between groups (keep colour slot when the next style has it)
    const row = stepper(label, styleText, (d) => {
      wake();
      const { g, c } = find();
      const ng = (g + d + groups.length) % groups.length;
      draft[layer] = groups[ng][Math.min(c, groups[ng].length - 1)];
    });
    if (dimmable) dimmers.push(() => row.classList.toggle("off", presetActive()));
    box.appendChild(row);
    // colour row only when some style has colour variants
    if (groups.some((grp) => grp.length > 1)) {
      const colorRow = stepper(`${label} 색`, () => {
        const { g, c } = find();
        return groups[g].length > 1 ? `${c + 1}/${groups[g].length}` : "–";
      }, (d) => {
        wake();
        const { g, c } = find();
        const grp = groups[g];
        draft[layer] = grp[(c + d + grp.length) % grp.length];
      });
      colorRow.classList.add("sub");
      if (dimmable) dimmers.push(() => colorRow.classList.toggle("off", presetActive()));
      box.appendChild(colorRow);
    }
  }
  if (!box.children.length) box.textContent = "바꿀 수 있는 레이어가 없어요 (preprocess build 필요)";
  for (const d of dimmers) d();
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
      const spec = chars.layers[layer];
      const n = spec?.count ?? 0;
      if (n <= 0) continue;
      draft[layer] = spec.exclusive ? (spec.none ?? 0) : Math.floor(Math.random() * n); // random = layered look
    }
    refreshAll();
  });
  guard($("avatar-save"), async () => {
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
