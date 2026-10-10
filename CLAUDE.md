# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Shared Room Decorator": a small multiplayer web game where friends decorate shared rooms together. Currency comes from a Google Sheet (per-person earnings) summed into one **shared pool**; anyone can spend it on furniture. Online players' avatars walk around the rooms, an overworld map, and a fishing dock.

- `client/` — Phaser 3 + Vite + TypeScript
- `server/` — FastAPI + SQLite (single uvicorn worker; presence is in memory)
- `tools/preprocess/` — Python pipeline turning licensed LimeZu asset packs in `assets/` (gitignored) into `client/public/gen/`, plus a browser-based slice/room/map/dock editor
- `data/` — hand-edited game data (the source of truth for catalog, rooms, map, dock, fishing, UI theme)

README.md, `tools/preprocess/README.md` (asset pipeline + editor + data file formats) and `REVIEW.md` are written in Korean and are the primary docs.

## Commands

```bash
# server (from server/, venv at server/.venv)
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
pytest                                  # all server tests (testpaths = tests)
pytest tests/test_placement.py -k name  # single test

# client (from client/) — dev server proxies /api and /ws to localhost:8000
npm run dev
npm run build        # tsc --noEmit && vite build → outputs to ../server/static

# asset pipeline (from repo root; needs assets/ and pillow)
python tools/preprocess/preprocess.py build      # slices.json/map_slices.json → client/public/gen/
python tools/preprocess/preprocess.py editor     # browser editor (slices, items, rooms, map, dock)
python tools/preprocess/preprocess.py media      # BGM/fonts/SFX → client/public/media/
python tools/preprocess/preprocess.py ui         # data/ui_theme.json → media/theme.css
pytest tools/preprocess/tests
```

With `SHEET_URL` empty, the server uses `data/fake_sheet.json` for balances — fine for local dev. Config is env vars / `server/.env` (see `server/app/config.py`).

## Architecture

**Data flow.** `data/items.json`, `data/rooms/<id>.json`, `data/map.json` and `client/public/gen/manifest.json` are loaded and validated (pydantic) by `server/app/catalog.py` at startup and served to the client via `GET /api/catalog`. The client builds its lookup structures in `client/src/catalog.ts`. Adding furniture = add a slice → `build` → `scaffold` → edit `data/items.json`. Tags are edited in the editor's items tab (`tools/preprocess/editor.py KNOWN_TAGS` is the single list of known tags + descriptions).

**Placement rules exist twice.** `server/app/placement.py` is authoritative (pure functions, no DB). `client/src/room/rules.ts` is a mirror used only to colour the placement ghost. Change both together. Layers: `wallpaper`, `wall`, `floor`, `furniture`, `surface_item`; items only collide within the same *collision layer* (`Item.collision_layer`: the layer, except `partition` → `furniture` and `rug`-tagged floor items → `rug`, so rugs lie over untagged floor patterns), `surface_item` must sit on an `is_surface` furniture, and furniture/floor items cannot go on a tile with `walk: false`. `wall` decor may also hang on a partition's *face* (`partition_face`: its columns × `Item.face_rows` = max(h, manifest `ch`) rows up from its feet) — the partition under its first cell becomes `parent_uid` (so `has_children` protects it) and z is `Z_OF_LAYER["hung"]`; the client sorts it with the partition's bottom row at `Z_HUNG`. Seeded items use `relaxed=True`; `seed.py` seeds partitions first, surface items last.

**Tiles and walking.** Slices can carry `step` (footstep sound kind) and `walk: false`; `build` copies them into manifest keys and the server exports them as `catalog.tiles` (`interior`/`map`). Rooms may have a per-cell `floor` grid (world editor "바닥 칠하기"), falling back to `tiles.floor`. Walking is client-only (`client/src/room/walk.ts`: BFS over a walk grid; the server just clamps `move`). Player-placed furniture blocks; `$seed` items, `ruined` junk and stairs do not.

**Viewport.** The canvas is the whole window (`Scale.RESIZE`); `scenes/CameraController.ts` follows the avatar with an integer zoom (2–4, `Room.zoom` as a hint) and handles pan/pinch/wheel. Pointer input goes through `input/Gestures.ts` (tap / long press / right click / two-finger pan+pinch); convert pointer positions with `cam.screenToWorld`, never `pointer.worldX`. WASD/arrows walk (`input/Keyboard.ts`), Esc/Enter drive placement. Desktop (`min-width: 900px` + mouse) docks panels as a right sidebar (`style.css`).

**Audio.** `audio/bgm.ts` (music) and `audio/sfx.ts` (effects, `SFX` name table) share one mute switch and the first-gesture unlock in `audio/unlock.ts`. Sounds come from `assets/sfx/**/<kind>_*.mp3` via `preprocess.py media` (`walking/` → `step_<kind>`).

**Item tags.** `ruined` items can be sold/removed but not bought; `fixed` items cannot be moved or deleted; `stairs` marks stair sprites; `bed` counts toward guests (no bed → no guests); `dog` satisfies the monthly dog-lover guest; `partition` makes a wall-layer sprite stand on floor rows (room dividers: `Item.on_wall` false, `collision_layer` furniture, blocks walking; wall decor can hang on its face) and `door` lets avatars walk through such a partition; `rug` marks a floor-layer item that lies over floor patterns (own collision layer `rug`, z above them); `guest_note` marks the sprite guests leave their notes on (else the cheapest surface `note` item); `note` items carry a short shared text (`items.note/note_by/note_ts`, `PUT /api/room/item/{uid}/note`, panel `ui/note.ts`); `board` items (the inn's seeded `med_018`) open the 📋 board on tap (`ui/board.ts`: tonight's guests, open reservations with `reservation.ready` + a shop link via `shop:open`, every room's restoration stages). The map shows an exclamation marker over rooms that still contain `ruined` items.

**Restoration, deliveries, activity log.** `data/rooms/<id>.json` may carry `restore: [stage]` (needs: `ruined_zero` / `placed` / `deliver` / `pool`; reward: `unlock {room|"map"|"dock"}`). `server/app/restore.py` is the pure rule module (evaluate, lock derivation, validation at catalog load); `server/app/progress.py` is the DB side: `advance_rooms()` runs inside every transaction that can change a need (place/move/remove/fish/deliver/sheet fetch) and stores only `room_meta stage:<id>` / `stage_ts:<id>`; `after_commit()` broadcasts ws `event` rows and a `progress` picture. A place is locked iff an incomplete stage unlocks it: place/move into it → 403 `room_locked`, ws `enter` → `{"type":"error","code":"room_locked"}`; the client mirrors this (`state.locked`, `unlockerOf()` for the toast, `icon_lock` on the map). Fish: `/api/fish/finish` still credits the pool and returns `seq` + `deliverable`; `POST /api/deliver {seq}` (routers/deliver.py, fish *and* mine ledger rows) within 120 s reverses the money (`ledger.kind='deliver'`) and adds a `deliveries` row counted by `deliver` needs (`kind: fish|mine`; `progress.deliveries_by_room` is keyed per kind). `events` (migration 008, backfilled from the ledger; `amount` = signed pool change) feed `GET /api/activity`, which serves only the newest 5 rows (`ui/log.ts`, 📜 button). `server/app/items.py` holds the shared item queries.

**Furniture sets, comfort and guests.** `build` derives a `set` slug per interior slice from its source (`preprocess.py set_of`, merged via `config.SET_ALIASES`) and writes it on the manifest key; `catalog.load` copies it into `Item.set` (never stored in `items.json`). `server/app/comfort.py` is the pure comfort/guest maths (price sum with duplicate decay, saturation by room size, set bonus, `bed` tag required), tuned by `data/guests.json` (`app.state.guests`). A guest *unit* is a room, or each of its `zones` (rectangles drawn in the world editor, `catalog.Zone`; an item belongs to the zone containing its anchor cell); unit keys are `room` / `room:zone`. `server/app/guests.py` is the DB side: `settle()` runs on boot and every minute (`main.settle_guests`), is idempotent per guest day (KST day ending at 09:00; `room_meta guest_day:<id>`), pays through `ledger.kind='guest'` + `events.kind='guest'`, handles `reservations` (migration 009: item requests paying 2×, missed → `no_guests_day`, the monthly `dog` guest), a paid night also leaves a `note` surface item owned by `config.GUEST_PLAYER` on a surface in the unit (`guests.leave_note`, text by comfort band; never scores/blocks/refunds, `SYSTEM_PLAYERS` covers seed+guest), and `room_view()` feeds `comfort` (`{unit key: view}`) in `/api/rooms` and `/api/activity`. Client: `state.comfort` keyed by unit, `state.zone` + `currentUnit()` (RoomScene tracks the avatar's zone via `zoneAt`), `applyComfort()`, the 🛏️ section of `ui/log.ts`, `☕` on the HUD room chip. Design notes: `docs/261009_comfort_design.md`. The inn cat (`server/app/cat.py`, router `routers/cat.py`, migration 013 `cat_taps`): `POST /api/cat/pet {taps}` records a batch of taps (≤50 per call; the client groups quick taps), `cat.affection()` = min(3, total taps from everyone // 100), never decays; a level-up writes `events.kind='cat'`, every call broadcasts ws `{"type":"cat"}`; `/api/activity` carries `cat {affection, taps}`. Affection is passed as `affection` into comfort for `inn` units only (`guests.unit_affection`); the sprite strip is `gen/cat/<variant>.png` + manifest `cat` (`build_cat`, `config.CAT_VARIANT`), served as `catalog.cat`, animated client-side in `npc/Cat.ts` (RoomScene spawns it in the inn; tap = meow + pet).

**Mine.** `data/rooms/mine.json` is an ordinary grid room with `kind: "mine"` (`catalog.RoomKind`; place/move → 403 `no_place`, no guests/comfort, shop hidden). `data/mine.json` (`server/app/mine.py`, optional: no file → `app.state.mine` is None and `/api/mine*` answers 404 `no_mine`) names that room, `per_day`, the ore kinds (`hits`, `value`, `weight`, icon crops `build` cuts to `gen/mine/<id>.png` + `pickaxe.png` via `copy_loot_icons`) and `reach`. `mine.spawn_day()` puts `per_day` nodes on free floor cells once per KST calendar day (`ore_nodes`, migration 014; `room_meta mine_day:<room>`), run at boot, on the minute tick (`main._tick_loop`, with guest settlement) and lazily by `/api/mine/nodes`; leftovers never carry over. `POST /api/mine/hit {seq}` needs the player's presence in the mine within `reach` cells (`mine.foot_cell` mirrors the client's foot cell), takes one hit, and the last hit writes `ledger.kind='mine'` + `events.kind='mine'` in that player's name and returns `ledger_seq` + `deliverable` for `/api/deliver`; ws `{"type":"mine"}` goes to the mine room only (`hub.broadcast_threadsafe(msg, room=)`), `mine_reset` after a new day's spawn. Client: `room/OreNodes.ts` (sprites, walk-grid blocking, target selection by tap → walk up, `mine:press`), HUD `#minebar` (`⛏ 채광`, Space key, pickaxe swing CSS), the loot overlay is shared with fishing (`bus loot:got {kind}`), `SFX.pick`.

**Seeding.** On startup the server seeds each room's `seed` list once, owned by `$seed` (shown as "???"). Tracked in `room_meta` (`seeded:<id>`, `seed_hash:<id>`). `server/app/reconcile.py` fixes up DB rows when the catalog changes. Schema changes go in a new numbered file in `server/migrations/` (applied via `PRAGMA user_version`).

**Currency.** `server/app/sheet.py` fetches the Apps Script (`tools/appsscript/Code.gs`) and caches/snapshots it; balance = `SUM(sheet_snapshot.earned) − SUM(ledger.amount)` (fish catches are ledger rows with `kind='fish'`). Money changes are broadcast to all clients.

**Realtime.** `server/app/presence.py` holds a `Hub`: every online player is in exactly one presence room (a grid room id, `"map"`, or `"dock"`). Join/leave/move go only to that room; room-version and money messages go to everyone. REST handlers run in a threadpool and must use `hub.broadcast_threadsafe`. Room GETs use ETag = room version.

**Client.** `main.ts` boots (recovery link `?t=TOKEN`, catalog, account, UI) and switches between Phaser scenes `RoomScene` / `MapScene` / `DockScene`. Phaser scenes and the DOM UI (`ui/*.ts`: HUD, shop, avatar editor, context menu, accounts) talk only through the typed event bus in `bus.ts`; shared mutable state is in `state.ts`. One WebSocket per account (`ws.ts`) survives scene changes. Depth sorting lives in `room/depth.ts`.

**Fishing.** Server generates a bite schedule (one real bite + decoys) in `server/app/fishing.py`, the client reports the press window, server judges and credits the shared pool. Tuned in `data/fishing.json`.

## Conventions and gotchas

- Player-facing strings (toasts, UI text) are Korean in 해요체. Code and identifiers are English.
- Do not use the word `sheet` in slice keys — a server test asserts it never appears in `/api/catalog` output (the sheet URL must never leak).
- `build` refuses to shrink character layers (would shift saved avatar indices); `--allow-shrink` overrides. Append new hair palette columns only at the end.
- Slices whose source pack is missing are "frozen": copied from the previous `gen/interiors.png` atlas.
- `client/public/gen/*.png`, `gen/chars/`, `gen/dock/`, media binaries, and `server/static/` are gitignored; they are built on the PC and uploaded to the VM.
- Deploy target: Oracle VM at `/opt/interior`, systemd unit `interior`, Caddy in front (`deploy/`). **No `git pull` on the VM** — it got too complicated; `deploy/push.sh` is not used. The user copies changed files manually via SFTP and runs `sudo systemctl restart interior`, so after a change list the changed files per folder plus whether a restart is needed. After editing a room's seed, the `seeded:<id>`/`seed_hash:<id>` rows must be deleted on the VM to reseed (see README); restoration stages reset by deleting `stage:<id>`/`stage_ts:<id>`.
