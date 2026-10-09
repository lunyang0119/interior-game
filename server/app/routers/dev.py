"""Developer tools, mounted only when DEV_TOOLS=1 (never on the VM).

POST /api/dev/settle  — run the guest settlement as if `days` days had passed (the shared pool, events, toasts
                        and the 📜 panel all react like on a real morning). Options: chance (force reservation
                        odds), dog (re-roll this month's dog lover), reset (forget settlement state first).
"""

import random

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import guests, progress
from ..auth import Player, current_player
from ..db import get_db, now, transaction

router = APIRouter(prefix="/api/dev")


class SettleIn(BaseModel):
    days: int = Field(default=1, ge=0, le=30)
    chance: float | None = Field(default=None, ge=0, le=1)  # reservation odds for this run (1 = always)
    dog: bool = False  # forget this month's dog decision so a booking can happen now
    reset: bool = False  # drop guest_day / no_guests_day / dog_month + reservations before settling
    seed: int | None = None  # deterministic RNG


@router.post("/settle")
def settle(body: SettleIn, request: Request, me: Player = Depends(current_player), conn=Depends(get_db)):
    app = request.app
    cfg = app.state.guests.model_copy(deep=True)
    if body.chance is not None:
        cfg.reservation.chance = body.chance
    events: list[dict] = []
    changed: set[str] = set()
    with transaction(conn):
        if body.reset:
            conn.execute("DELETE FROM room_meta WHERE k LIKE 'guest_day:%' OR k LIKE 'no_guests_day:%' OR k = 'dog_month'")
            conn.execute("DELETE FROM reservations")
            guests.settle(conn, app.state.catalog, cfg, now())  # marks today as the starting point
        if body.dog:
            conn.execute("DELETE FROM room_meta WHERE k = 'dog_month'")
        ts = now() + body.days * 86400
        paid = guests.settle(conn, app.state.catalog, cfg, ts, random.Random(body.seed) if body.seed is not None else None,
                             events, changed)
        completed = progress.advance_rooms(conn, app.state.catalog, events) if paid else []
    guests.after_settle(conn, events, paid, changed)
    if completed:
        progress.after_commit(conn, app.state.catalog, [], completed)
    return {"paid": paid, "events": events, "views": guests.all_views(conn, app.state.catalog, app.state.guests, ts)}
