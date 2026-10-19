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

from . import bot_player as B
from . import engine as E
from . import settings

if TYPE_CHECKING:
    from .game import TrainGame

FUGITIVE, HUNTER, SPECTATOR = "fugitive", "hunter", "spectator"
REPLAY_ROUNDS = 8   # how many recent public reports every payload carries (`reports`)
FINISHED = ("CAPTURED", "ESCAPED")   # the chase is over (caught / the fugitive got away at the freeze)


def label_of(pid: str) -> str:
    """Display name of a hunter id: engine names stay uids; AI hunters ("bot:N") read as "제미나이-N"."""
    if B.is_bot(pid):
        return f"제미나이-{pid[len(B.BOT_PREFIX):]}"
    return pid


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
        "game_id": game.row_id,
        "status": game.status,
        "role": role,
        "hunter_count": p.hunter_count,
        "fugitive_ai": p.fugitive_ai,
        "map_id": game.current_map_id(),
        "scaled_for": game.scale_n(),          # the hunter count the balance/map is scaled for (boarding count)
        "override_keys": sorted(p.overrides),  # which tunables the admin overrode (names only, never values)
        "lobby": list(p.lobby),
        "deadline_ts": p.deadline_ts,
        "grace_until": p.grace_until,
        "paused_remaining": p.paused_remaining,
        "vote_after_ts": game.vote_after_ts(),
        "votes": {k: list(v) for k, v in p.votes.items()},
        "need": game.votes_needed(),
        "vote_need": game.vote_needs(),
        # always identifies the caller; room/order only once they are a hunter in a running game
        "you": {"id": pid, "room": None, "order": None, "dazed": False} if pid is not None else None,
        "avatars": {pid: look for pid, look in game.avatars.items() if pid in p.lobby or (st_h := game.engine) and pid in st_h.hunters},
    }
    st = game.engine
    ids = list(st.hunters) if st is not None else list(p.lobby)
    out["labels"] = {uid: label_of(uid) for uid in ids}
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
    # the last few rounds' public reports: a client that was away (or whose playback stalled) replays every round it
    # has not seen, in order, instead of only the newest one
    out["reports"] = [public_report(e["report"]) for e in st.log[-REPLAY_ROUNDS:]]
    out["orders"] = hunter_orders(st)
    out["fugitive_submitted"] = st.fugitive.order is not None   # a flag only; the order itself stays fugitive-only
    out["config"] = settings.public_config(st.config)
    if pid is not None and pid in st.hunters:
        h = st.hunters[pid]
        out["you"] = {"id": pid, "room": h.room, "order": order_dict(h.order), "dazed": h.dazed_until >= st.round_no}
    # the fugitive's route is public only once the chase is over AND the admin switched the reveal on
    if game.status in FINISHED and p.reveal_path:
        out["route"] = [{"round": e["round"], "path": list(e.get("fugitive_path") or [])} for e in st.log]
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
    out["bot_reasons"] = list(st.bot_reasons[-60:])
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
