import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import catalog as catalog_mod
from . import comfort, config, fishing, guests, mine, progress, sheet
from .db import connect, ensure_room_meta, migrate, now, transaction
from .errors import ApiError
from .presence import hub
from .reconcile import reconcile_items
from .seed import seed_room
from .routers import activity, auth, cat, chat, deliver, fish, me, room, ws
from .routers import mine as mine_router
from .train import game as train_game
from .train import router as train_router
from .train import ws as train_ws

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

ACCESS_LOG_KEEP_DAYS = 90
PRUNE_INTERVAL_S = 24 * 3600


def prune_access_log() -> int:
    """access_log grows with every action (and every bad-token hit); keep the last N days."""
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM access_log WHERE ts < ?", (now() - ACCESS_LOG_KEEP_DAYS * 86400,))
        return cur.rowcount
    finally:
        conn.close()


async def _prune_loop() -> None:
    while True:
        try:
            n = await asyncio.to_thread(prune_access_log)
            if n:
                log.info("pruned %d access_log rows", n)
        except Exception as e:  # noqa: BLE001
            log.warning("access_log prune failed: %s", e)
        await asyncio.sleep(PRUNE_INTERVAL_S)


GUEST_TICK_S = 60


def settle_guests(app: FastAPI) -> None:
    """One guest settlement pass (idempotent per guest day): on boot and every minute."""
    conn = connect()
    try:
        events: list[dict] = []
        changed: set[str] = set()
        with transaction(conn):
            paid = guests.settle(conn, app.state.catalog, app.state.guests, events=events, rooms_changed=changed)
            completed = progress.advance_rooms(conn, app.state.catalog, events) if paid else []
        if events:
            log.info("guests: %d💰 from %d event(s)", paid, len(events))
        guests.after_settle(conn, events, paid, changed)
        if completed:
            progress.after_commit(conn, app.state.catalog, [], completed)
    finally:
        conn.close()


def spawn_mine(app: FastAPI) -> None:
    """Generate today's first mine floor once per KST day (idempotent): on boot and every minute. Deeper floors
    are generated the first time someone asks for them. A new day tells every client (`mine_reset`): whoever is
    in the mine reloads their floor."""
    m = app.state.mine
    if m is None:
        return
    conn = connect()
    try:
        with transaction(conn):
            mine.ensure_floor(conn, app.state.catalog, m.cfg, 1)
        # the day is tracked in memory, not by who generated floor 1: a player's request after midnight may have
        # generated it already (GET /api/mine/floor/1), and everyone on the other floors still needs the reset
        today = mine.day_key(now())
        if m.last_day and today != m.last_day:
            log.info("mine: a new day's floors begin")
            hub.broadcast_threadsafe({"type": "mine_reset"})
        m.last_day = today
    finally:
        conn.close()


async def _tick_loop(app: FastAPI) -> None:
    """Minute tick: guest settlement + the daily ore spawn (each idempotent per day)."""
    while True:
        await asyncio.sleep(GUEST_TICK_S)
        try:
            await asyncio.to_thread(settle_guests, app)
        except Exception as e:  # noqa: BLE001
            log.warning("guest settlement failed: %s", e)
        try:
            await asyncio.to_thread(spawn_mine, app)
        except Exception as e:  # noqa: BLE001
            log.warning("mine spawn failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    migrate(conn)
    app.state.catalog = catalog_mod.load()
    app.state.guests = comfort.load_config()
    if app.state.guests.special_after not in (None, "map", "dock", *app.state.catalog.rooms):
        raise ValueError(f"guests.json: special_after '{app.state.guests.special_after}' is not a room, 'map' or 'dock'")
    with transaction(conn):
        ensure_room_meta(conn, list(app.state.catalog.rooms))
        reconcile_items(conn, app.state.catalog)
        for room in app.state.catalog.rooms.values():
            seed_room(conn, app.state.catalog, room)
        # stages whose needs are already met (e.g. a DB from before restoration existed) complete right away
        progress.advance_rooms(conn, app.state.catalog)
    conn.close()
    settle_guests(app)
    app.state.sheet = sheet.from_config()
    # `pool` needs can only be met by new income, which arrives through sheet fetches
    app.state.sheet.catalog = app.state.catalog
    app.state.sheet.on_snapshot = lambda c, ev: progress.advance_rooms(c, app.state.catalog, ev)
    app.state.fishing = fishing.Fishing(cfg=fishing.load_config())
    mine_cfg = mine.load_config()
    app.state.mine = mine.Mine(cfg=mine_cfg) if mine_cfg else None
    if mine_cfg:
        mine_room = app.state.catalog.room_of(mine_cfg.room)
        if mine_room is None or mine_room.kind != mine.ROOM_KIND:
            raise ValueError(f"mine.json: room '{mine_cfg.room}' is not a room with kind \"mine\"")
    loot_ids = {"fish": {lt.id for lt in app.state.fishing.cfg.loot}, "mine": {o.id for o in mine_cfg.ores} if mine_cfg else set()}
    for rm in app.state.catalog.rooms.values():
        for st in rm.restore:
            for n in st.need:
                if n.type == "deliver" and n.id is not None and n.id not in loot_ids[n.kind]:
                    raise ValueError(f"room {rm.id}: stage '{st.id}' needs unknown {n.kind} loot '{n.id}' (data/{'fishing' if n.kind == 'fish' else 'mine'}.json)")
    spawn_mine(app)
    hub.bind_loop()
    # train minigame: restore the stored game and re-arm its round timer from the stored deadline
    app.state.train = train_game.Manager()
    await app.state.train.start()
    prune_task = asyncio.create_task(_prune_loop())
    guest_task = asyncio.create_task(_tick_loop(app))
    yield
    prune_task.cancel()
    guest_task.cancel()
    await app.state.train.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="interior", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content={"error": exc.code})

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(room.router)
    app.include_router(fish.router)
    app.include_router(deliver.router)
    app.include_router(mine_router.router)
    app.include_router(activity.router)
    app.include_router(cat.router)
    app.include_router(chat.router)
    app.include_router(ws.router)
    app.include_router(train_router.router)
    app.include_router(train_ws.router)
    if config.DEV_TOOLS:  # imported lazily so a VM without routers/dev.py still boots
        from .routers import dev

        log.warning("DEV_TOOLS on: /api/dev/* is mounted")
        app.include_router(dev.router)

    # Generated sprites are served from the same origin in production. In dev Vite serves them.
    if config.GEN_DIR.exists():
        app.mount("/gen", StaticFiles(directory=config.GEN_DIR), name="gen")
    if config.MEDIA_DIR.exists():
        app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")
    if config.STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
    return app


app = create_app()
