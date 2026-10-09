"""Restoration stages: pure rules, no DB (like placement.py).

A room's `restore` list (data/rooms/<id>.json) is a sequence of stages. Each stage has needs that are
evaluated against the live state (items in the room, deliveries made for that stage, the shared pool) and
rewards that unlock other places once the stage is complete. Only the number of completed stages per room
is stored (room_meta 'stage:<id>'); everything else is derived. Stages are monotonic: once complete, spending
the pool again never re-locks anything.

Lock rule: a place (room id, "map" or "dock") is locked iff some room's stage rewards `unlock` for it and that
stage is not complete yet. Places no stage mentions are always open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, model_validator

from . import config

if TYPE_CHECKING:  # catalog imports this module, so only type-check against it
    from .catalog import Catalog, Room
    from .placement import ItemRow

NeedType = Literal["ruined_zero", "placed", "deliver", "pool"]
# key of the deliveries dict that counts every delivery regardless of loot id
ANY = "*"
TAG_RUINED = "ruined"  # mirrors catalog.TAG_RUINED (no runtime import)


class Need(BaseModel):
    type: NeedType
    count: int = Field(default=1, ge=1)  # placed / deliver
    layer: str | None = None  # placed: filter by item layer
    tag: str | None = None  # placed: filter by item tag
    item_id: str | None = None  # placed: one exact item
    kind: Literal["fish"] = "fish"  # deliver
    id: str | None = None  # deliver: one loot id (None = any)
    amount: int | None = Field(default=None, ge=1)  # pool
    label: str = ""  # optional text for the checklist

    @model_validator(mode="after")
    def _rules(self) -> "Need":
        if self.type == "pool" and self.amount is None:
            raise ValueError("pool need requires amount")
        if self.type == "placed" and sum(x is not None for x in (self.layer, self.tag, self.item_id)) > 1:
            raise ValueError("placed need takes at most one of layer / tag / item_id")
        return self


class Reward(BaseModel):
    type: Literal["unlock"]
    room: str  # room id, "map" or "dock"


class Stage(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    need: list[Need] = Field(min_length=1)
    reward: list[Reward] = []


@dataclass(frozen=True)
class NeedProgress:
    type: str
    label: str
    have: int
    want: int
    done: bool

    def public(self) -> dict:
        return {"type": self.type, "label": self.label, "have": self.have, "want": self.want, "done": self.done}


@dataclass(frozen=True)
class StageProgress:
    index: int
    stage: Stage
    needs: list[NeedProgress]

    @property
    def done(self) -> bool:
        return all(n.done for n in self.needs)

    def public(self) -> dict:
        return {"id": self.stage.id, "name": self.stage.name, "done": self.done,
                "unlocks": [r.room for r in self.stage.reward], "needs": [n.public() for n in self.needs]}


def _placed_matches(cat: Catalog, need: Need, row: ItemRow) -> bool:
    if row.placed_by in config.SYSTEM_PLAYERS:
        return False
    it = cat.items.get(row.item_id)
    if it is None:
        return False
    if need.item_id is not None:
        return it.id == need.item_id
    if need.layer is not None:
        return it.layer == need.layer
    if need.tag is not None:
        return it.has_tag(need.tag)
    return True


def evaluate(cat: Catalog, stage: Stage, index: int, items: list[ItemRow], deliveries: dict[str, int],
             balance: int) -> StageProgress:
    """Progress of one stage. `deliveries` counts rows for this room+stage keyed by loot id, plus ANY for the total."""
    out: list[NeedProgress] = []
    for n in stage.need:
        if n.type == "ruined_zero":
            have = sum(1 for r in items if cat.items[r.item_id].has_tag(TAG_RUINED))
            out.append(NeedProgress("ruined_zero", n.label, have, 0, have == 0))
        elif n.type == "placed":
            have = sum(1 for r in items if _placed_matches(cat, n, r))
            out.append(NeedProgress("placed", n.label, min(have, n.count), n.count, have >= n.count))
        elif n.type == "deliver":
            have = deliveries.get(n.id if n.id is not None else ANY, 0)
            out.append(NeedProgress("deliver", n.label, min(have, n.count), n.count, have >= n.count))
        else:  # pool
            want = n.amount or 0
            out.append(NeedProgress("pool", n.label, max(0, min(balance, want)), want, balance >= want))
    return StageProgress(index, stage, out)


def unlock_map(rooms: dict[str, Room]) -> dict[str, tuple[str, int]]:
    """target place -> (room that unlocks it, stage index)."""
    out: dict[str, tuple[str, int]] = {}
    for room in rooms.values():
        for i, st in enumerate(room.restore):
            for r in st.reward:
                out[r.room] = (room.id, i)
    return out


def locked_rooms(rooms: dict[str, Room], stages_done: dict[str, int]) -> set[str]:
    """Places whose unlocking stage is not complete yet (stages_done = completed count per room, missing = 0)."""
    return {target for target, (rid, idx) in unlock_map(rooms).items() if stages_done.get(rid, 0) <= idx}


def validate_restore(rooms: dict[str, Room], scene_rooms: tuple[str, ...] = config.SCENE_ROOMS, base: str = "inn") -> None:
    """Raises ValueError for unlock targets that cannot work: unknown, the base room, self, double unlockers, cycles."""
    seen: dict[str, str] = {}
    for room in rooms.values():
        for st in room.restore:
            for r in st.reward:
                if r.room not in rooms and r.room not in scene_rooms:
                    raise ValueError(f"room {room.id}: stage '{st.id}' unlocks unknown place '{r.room}'")
                if r.room == base:
                    raise ValueError(f"room {room.id}: stage '{st.id}' must not lock the base room")
                if r.room == room.id:
                    raise ValueError(f"room {room.id}: stage '{st.id}' unlocks its own room")
                if r.room in seen:
                    raise ValueError(f"place '{r.room}' is unlocked by both {seen[r.room]} and {room.id}")
                seen[r.room] = room.id
    # a locked room whose unlocker is itself locked, and so on back to itself, can never open
    unlockers = unlock_map(rooms)
    for target in unlockers:
        cur, hops = target, 0
        while cur in unlockers and hops <= len(unlockers):
            cur = unlockers[cur][0]
            hops += 1
            if cur == target:
                raise ValueError(f"place '{target}' can never be unlocked (cycle)")
