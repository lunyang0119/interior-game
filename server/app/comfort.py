"""Comfort score and guest maths: pure rules, no DB (like restore.py). Design: docs/261009_comfort_design.md.

A room's comfort (0–100) is what the decorating is worth to a guest:

    raw    = Σ price × dup_decay^(copies of the same item before this one)     (player-placed, not ruined)
    base   = 100 × raw / (raw + K),  K = cells × k_per_cell                       (saturates per unit size)
    mult   = 1 + set_bonus_max × clamp((share − 0.5) / 0.5, 0, 1)                (share = biggest furniture set)
    score  = clamp(round(base × mult − ruined × ruined_penalty + affection × affection_bonus), 0, 100)

The unit is a whole room or one of its zones (`cells` = its area; `items` = the rows that belong to it).
Seeded ("???") items never score but a seeded bed still counts as a bed. Guests need a bed: guests/day =
min(beds, ceil(score / band)) capped at max_guests, each paying pay_base + pay_per_comfort × score.
Everything is tuned in data/guests.json (GuestConfig).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from . import config

if TYPE_CHECKING:
    from .catalog import Catalog
    from .placement import ItemRow

TAG_BED = "bed"
TAG_RUINED = "ruined"  # mirrors catalog.TAG_RUINED (no runtime import)
SET_LAYERS = ("furniture", "surface_item")  # tiles never share a set with furniture, so they stay out of the share


class ComfortConfig(BaseModel):
    k_per_cell: float = Field(gt=0)
    dup_decay: float = Field(ge=0, le=1)
    set_bonus_max: float = Field(ge=0)
    set_min_items: int = Field(ge=1)
    ruined_penalty: int = Field(ge=0)
    affection_bonus: int = Field(ge=0)


class GuestRules(BaseModel):
    min_comfort: int = Field(ge=0, le=100)
    band: int = Field(ge=1)
    max_guests: int = Field(ge=1)
    pay_base: float = Field(ge=0)
    pay_per_comfort: float = Field(ge=0)


class ReservationRules(BaseModel):
    chance: float = Field(ge=0, le=1)
    lead_days: tuple[int, int] = (2, 4)
    min_price: int = Field(ge=0)
    pay_mult: float = Field(ge=1)
    dominant_set_pct: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _lead_days_ordered(self):
        lo, hi = self.lead_days
        if not 1 <= lo <= hi:
            raise ValueError(f"lead_days must be [lo, hi] with 1 <= lo <= hi, got {self.lead_days}")
        return self


class DogRules(BaseModel):
    tag: str = "dog"
    comfort_fallback: int = Field(ge=0, le=100)
    pay_mult: float = Field(ge=1)


class GuestConfig(BaseModel):
    checkout_hour_kst: int = Field(ge=0, le=23)
    max_catchup_days: int = Field(ge=1)
    comfort: ComfortConfig
    guests: GuestRules
    reservation: ReservationRules
    dog: DogRules
    # Reservations and the dog lover only start once this place (room id, "map" or "dock") is unlocked.
    # None = from the start. Ordinary guests are not gated.
    special_after: str | None = None


def load_config(path: Path | None = None) -> GuestConfig:
    p = path or (config.DATA_DIR / "guests.json")
    return GuestConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))


@dataclass
class Comfort:
    score: int  # 0..100
    beds: int
    raw: float  # price sum after duplicate decay
    base: float  # saturated 0..100 before the set multiplier
    mult: float  # set bonus multiplier (1.0 = none)
    set: str | None  # the dominant furniture set, when it earns a bonus
    set_share: float  # 0..1, price share of the dominant set among furniture/surface items
    ruined: int
    affection: int

    def public(self) -> dict:
        return {"score": self.score, "beds": self.beds, "raw": round(self.raw), "base": round(self.base),
                "mult": round(self.mult, 2), "set": self.set, "set_share": round(self.set_share, 2),
                "ruined": self.ruined, "affection": self.affection}


def _price(cat: Catalog, row: ItemRow) -> int:
    from .placement import price_of  # placement imports catalog; keep this module import-light

    return price_of(cat.items[row.item_id], row.span)


def comfort(cat: Catalog, cells: int, items: list[ItemRow], cfg: ComfortConfig, affection: int = 0) -> Comfort:
    """Score a unit of `cells` cells from its live item rows (see the module docstring for the formula)."""
    beds = ruined = 0
    raw = 0.0
    seen: Counter[str] = Counter()
    set_sums: Counter[str] = Counter()
    set_items: Counter[str] = Counter()
    furn_sum = 0.0
    for row in items:
        it = cat.items[row.item_id]
        if it.has_tag(TAG_RUINED):
            ruined += 1
            continue
        if it.has_tag(TAG_BED):
            beds += 1
        if row.placed_by in config.SYSTEM_PLAYERS:
            continue
        price = _price(cat, row) * (cfg.dup_decay ** seen[row.item_id])
        seen[row.item_id] += 1
        raw += price
        if it.layer in SET_LAYERS:
            furn_sum += price
            if it.set:
                set_sums[it.set] += price
                set_items[it.set] += 1

    k = cells * cfg.k_per_cell
    base = 100.0 * raw / (raw + k) if raw > 0 else 0.0

    best, share, mult = None, 0.0, 1.0
    if set_sums and furn_sum > 0:
        top, top_sum = set_sums.most_common(1)[0]
        share = top_sum / furn_sum
        if set_items[top] >= cfg.set_min_items and share > 0.5:
            best = top
            mult = 1.0 + cfg.set_bonus_max * min(1.0, (share - 0.5) / 0.5)

    score = round(base * mult - ruined * cfg.ruined_penalty + affection * cfg.affection_bonus)
    return Comfort(score=max(0, min(100, score)), beds=beds, raw=raw, base=base, mult=mult, set=best,
                   set_share=share, ruined=ruined, affection=affection)


def guest_count(score: int, beds: int, rules: GuestRules) -> int:
    """How many ordinary guests stay tonight: none without a bed or below min_comfort, else by comfort band."""
    if beds <= 0 or score < rules.min_comfort:
        return 0
    return min(beds, rules.max_guests, score // rules.band + 1)  # 10–33 → 1, 34–67 → 2, 68+ → 3


def pay_per_guest(score: int, rules: GuestRules) -> int:
    return round(rules.pay_base + rules.pay_per_comfort * score)


def nightly_pay(score: int, beds: int, rules: GuestRules) -> tuple[int, int]:
    """(guests, total pay) for an ordinary night."""
    n = guest_count(score, beds, rules)
    return n, n * pay_per_guest(score, rules)
