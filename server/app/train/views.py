"""Role projections of a train game (pure functions; the tests call them directly).

Hunters and spectators only ever see what the engine's public_view() and the public part of the report expose.
The fugitive (= admin) sees the true state. Hunter order *contents* are public among hunters, but the fugitive
only learns them through a ping (engine cast_ping): `hunters_full[*].order` is filled only while
`fugitive.ping_round == round_no`.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from . import engine as E
from . import settings

if TYPE_CHECKING:
    from .game import TrainGame

FUGITIVE, HUNTER, SPECTATOR = "fugitive", "hunter", "spectator"


def order_dict(o: E.HunterOrder | None) -> dict[str, Any] | None:
    return None if o is None else {"type": o.type, "target": o.target}


def forder_dict(o: E.FugitiveOrder | None) -> dict[str, Any] | None:
    return None if o is None else {"move": o.move, "hack": o.hack, "target": o.target}


def public_report(rep: dict[str, Any] | None) -> dict[str, Any] | None:
    """The round report minus the admin-only fugitive path."""
    if not rep:
        return None
    out = copy.deepcopy(rep)
    pb = out.get("playback")
    if isinstance(pb, dict):
        pb.pop("fugitive_path", None)
    return out


def hunter_orders(st: E.GameState) -> dict[str, dict[str, Any] | None]:
    return {uid: order_dict(h.order) for uid, h in st.hunters.items()}


def _base(game: "TrainGame", role: str, pid: str | None) -> dict[str, Any]:
    p = game.policy
    out: dict[str, Any] = {
        "status": game.status,
        "role": role,
        "hunter_count": p.hunter_count,
        "map_id": p.map_id,
        "lobby": list(p.lobby),
        "deadline_ts": p.deadline_ts,
        "grace_until": p.grace_until,
        "paused_remaining": p.paused_remaining,
        "vote_after_ts": game.vote_after_ts(),
        "votes": {k: list(v) for k, v in p.votes.items()},
        "need": game.votes_needed(),
        "you": None,
    }
    st = game.engine
    if st is None:
        out["round_no"] = 0
        out["view"] = None
        out["report"] = None
        out["orders"] = {}
        out["config"] = settings.public_config(game.config())
        return out
    view = asdict(E.public_view(st))
    out["round_no"] = st.round_no
    out["view"] = view
    out["report"] = public_report(st.last_report)
    out["orders"] = hunter_orders(st)
    out["config"] = settings.public_config(st.config)
    if pid is not None and pid in st.hunters:
        h = st.hunters[pid]
        out["you"] = {"id": pid, "room": h.room, "order": order_dict(h.order), "dazed": h.dazed_until >= st.round_no}
    return out


def hunter_payload(game: "TrainGame", pid: str | None, role: str = HUNTER) -> dict[str, Any]:
    return _base(game, role, pid)


def fugitive_payload(game: "TrainGame", pid: str) -> dict[str, Any]:
    out = _base(game, FUGITIVE, pid)
    p = game.policy
    out["config"] = dict(game.config())
    out["overrides"] = dict(p.overrides)
    out["policy"] = {"deadline_ts": p.deadline_ts, "grace_until": p.grace_until, "paused_remaining": p.paused_remaining,
                     "round_open_ts": p.round_open_ts, "votes": {k: list(v) for k, v in p.votes.items()},
                     "webhook_sent": p.webhook_sent}
    st = game.engine
    if st is None:
        out["fugitive"] = None
        return out
    f = st.fugitive
    gmap = st.game_map
    pinged = f.ping_round == st.round_no
    out["fugitive"] = {
        "room": f.room, "ram": f.ram, "trace": f.trace, "tier": st.trace_tier(), "hidden_until": f.hidden_until,
        "frozen": f.frozen, "hacks_disabled": f.hacks_disabled, "traced_at": f.traced_at, "ping_round": f.ping_round,
        "pinged": pinged, "order": forder_dict(f.order),
    }
    hacks: dict[str, Any] = {}
    for hk in E.HACKS:
        ok, why = E.hack_available(st, hk)
        hacks[hk] = {"ok": ok, "why": why, "cost": int(st.config[f"{hk}_cost"]), "trace": int(st.config[f"{hk}_trace"])}
    out["hacks"] = hacks
    speed = int(st.config.get("fugitive_speed", 1))
    out["reachable"] = sorted(r for r in gmap.rooms if 0 < gmap.distance(f.room, r) <= speed)
    out["lockable_edges"] = E.lockable_edges(st)
    out["hunters_full"] = {
        uid: {"name": h.name, "room": h.room, "submitted": h.order is not None, "dazed_until": h.dazed_until,
              "order": order_dict(h.order) if pinged else None}
        for uid, h in st.hunters.items()
    }
    out["orders"] = {uid: (order_dict(h.order) if pinged else None) for uid, h in st.hunters.items()}
    out["report"] = copy.deepcopy(st.last_report)
    out["log"] = copy.deepcopy(st.log)
    out["position_history"] = list(st.position_history)
    return out


def payload_for(game: "TrainGame", role: str, pid: str | None) -> dict[str, Any]:
    if role == FUGITIVE:
        return fugitive_payload(game, pid or "")
    return hunter_payload(game, pid, role)
