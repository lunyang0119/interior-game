import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import catalog as catalog_mod
from . import config, sheet
from .db import connect, migrate
from .errors import ApiError
from .presence import hub
from .routers import auth, me, room, ws

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    migrate(conn)
    conn.close()
    app.state.catalog = catalog_mod.load()
    app.state.sheet = sheet.from_config()
    hub.bind_loop()
    yield


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
    if config.STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
    return app


app = create_app()
