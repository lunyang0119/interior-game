import Phaser from "phaser";
import { drawList, type AvatarLook, type Chars } from "../catalog";

export function texKey(layer: string, idx: number): string {
  return `char_${layer}_${idx}`;
}

export function animKey(tex: string, anim: string): string {
  return `${tex}:${anim}`;
}

/** Which (layer, idx) sheets a look needs, in draw order. Layers with no variants are skipped. */
export function sheetsFor(look: AvatarLook, chars: Chars): { layer: string; idx: number }[] {
  return drawList(look, chars);
}

/** Loads only the sheets this look needs (if not cached) and registers their animations. */
export function ensureAvatarTextures(scene: Phaser.Scene, look: AvatarLook, chars: Chars): Promise<void> {
  const needed = sheetsFor(look, chars).filter((s) => !scene.textures.exists(texKey(s.layer, s.idx)));
  return new Promise((resolve) => {
    const finish = () => {
      for (const s of sheetsFor(look, chars)) registerAnims(scene, texKey(s.layer, s.idx), chars);
      resolve();
    };
    if (needed.length === 0) { finish(); return; }
    for (const s of needed) {
      scene.load.spritesheet(texKey(s.layer, s.idx), `/gen/chars/${s.layer}/${s.idx}.png`,
        { frameWidth: chars.frameW, frameHeight: chars.frameH });
    }
    scene.load.once(Phaser.Loader.Events.COMPLETE, finish);
    scene.load.start();
  });
}

function registerAnims(scene: Phaser.Scene, tex: string, chars: Chars): void {
  for (const [name, [start, end]] of Object.entries(chars.anims)) {
    const key = animKey(tex, name);
    if (scene.anims.exists(key)) continue;
    scene.anims.create({
      key,
      frames: scene.anims.generateFrameNumbers(tex, { start, end }),
      frameRate: name.startsWith("run") ? 10 : 5,
      repeat: -1,
    });
  }
}
