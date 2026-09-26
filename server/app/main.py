import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import catalog as catalog_mod
from . import config, sheet
from .db import connect, ensure_room_meta, migrate, now, transaction
from .errors import ApiError
from .presence import hub
from .reconcile import reconcile_items
from .seed import seed_room
from .routers import auth, me, room, ws

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    migrate(conn)
    app.state.catalog = catalog_mod.load()
    with transaction(conn):
        ensure_room_meta(conn, list(app.state.catalog.rooms))
        reconcile_items(conn, app.state.catalog)
        for room in app.state.catalog.rooms.values():
            seed_room(conn, app.state.catalog, room)
    conn.close()
    app.state.sheet = sheet.from_config()
    hub.bind_loop()
    prune_task = asyncio.create_task(_prune_loop())
    yield
    prune_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="interior", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content={"error": exc.code})

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(room.router)
    app.include_router(ws.router)

    # Generated sprites are served from the same origin in production. In dev Vite serves them.
    if config.GEN_DIR.exists():
        app.mount("/gen", StaticFiles(directory=config.GEN_DIR), name="gen")
    if config.MEDIA_DIR.exists():
        app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")
    if config.STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
    return app


app = create_app()
