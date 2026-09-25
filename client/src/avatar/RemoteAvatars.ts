import Phaser from "phaser";
import type { AvatarLook, Chars } from "../catalog";
import type { OnlineState } from "../ws";
import { Avatar } from "./Avatar";
import { ensureAvatarTextures } from "./AvatarLoader";

/** Other players currently online, driven by WebSocket messages. */
export class RemoteAvatars {
  private avatars = new Map<string, Avatar>();
  private pending = new Map<string, OnlineState>();

  constructor(private scene: Phaser.Scene, private chars: Chars) {}

  get count(): number {
    return this.avatars.size + this.pending.size;
  }

  async join(s: OnlineState): Promise<void> {
    this.pending.set(s.id, s);
    await ensureAvatarTextures(this.scene, s.avatar, this.chars);
    const latest = this.pending.get(s.id);
    if (!latest) return; // left while loading
    this.pending.delete(s.id);
    this.avatars.get(s.id)?.destroy();
    const a = new Avatar(this.scene, this.chars, latest.avatar, 0, 0, latest.id, true);
    a.applyRemote(latest.x, latest.y, latest.dir, false);
    a.update(0, 1_000_000); // snap to position
    this.avatars.set(s.id, a);
  }

  leave(id: string): void {
    this.pending.delete(id);
    this.avatars.get(id)?.destroy();
    this.avatars.delete(id);
  }

  move(id: string, x: number, y: number, dir: string, moving: boolean): void {
    const p = this.pending.get(id);
    if (p) { p.x = x; p.y = y; p.dir = dir; return; }
    this.avatars.get(id)?.applyRemote(x, y, dir, moving);
  }

  async look(id: string, look: AvatarLook): Promise<void> {
    const p = this.pending.get(id);
    if (p) { p.avatar = look; return; }
    const a = this.avatars.get(id);
    if (!a) return;
    await ensureAvatarTextures(this.scene, look, this.chars);
    if (this.avatars.get(id) === a) a.setLook(look);
  }

  reset(list: OnlineState[]): void {
    for (const id of [...this.avatars.keys()]) this.leave(id);
    this.pending.clear();
    for (const s of list) void this.join(s);
  }

  update(time: number, delta: number): void {
    for (const a of this.avatars.values()) a.update(time, delta);
  }

  destroy(): void {
    this.reset([]);
  }
}
