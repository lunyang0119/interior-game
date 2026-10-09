"""Comfort score and guest maths (comfort.py): pure rules only — the daily settlement is not built yet."""
from pathlib import Path

import pytest

from app.comfort import ComfortConfig, GuestRules, comfort, guest_count, load_config, nightly_pay, pay_per_guest

CFG = ComfortConfig(k_per_cell=0.5, dup_decay=0.5, set_bonus_max=0.5, set_min_items=4, ruined_penalty=5, affection_bonus=3)
RULES = GuestRules(min_comfort=10, band=34, max_guests=3, pay_base=4, pay_per_comfort=0.36)
K = 8 * 6 * 0.5  # the test inn is 8×6 cells


def _row(uid, item_id, placed_by="lun", span=None):
    from app.placement import ItemRow
    return ItemRow(uid=uid, item_id=item_id, x=1, y=1, z=1, parent_uid=None, placed_by=placed_by, ts=0, span=span, room_id="inn")


def _score(catalog, items, affection=0):
    return comfort(catalog, catalog.rooms["inn"].cells, items, CFG, affection)


def test_empty_room_scores_nothing(catalog):
    c = _score(catalog, [])
    assert (c.score, c.beds, c.raw, c.mult, c.set) == (0, 0, 0, 1.0, None)
    assert c.public() == {"score": 0, "beds": 0, "raw": 0, "base": 0, "mult": 1.0, "set": None, "set_share": 0,
                          "ruined": 0, "affection": 0}


def test_seeded_items_do_not_score_but_a_seeded_bed_is_a_bed(catalog):
    c = _score(catalog, [_row(1, "table", "$seed"), _row(2, "bed", "$seed")])
    assert c.raw == 0 and c.score == 0 and c.beds == 1


def test_price_sum_saturates_by_room_size_and_duplicates_decay(catalog):
    c = _score(catalog, [_row(1, "chair"), _row(2, "chair"), _row(3, "chair")])
    assert c.raw == 50 + 25 + 12.5
    assert c.base == pytest.approx(100 * c.raw / (c.raw + K))
    assert c.score == round(c.base) and c.mult == 1.0  # chairs belong to no set
    # raw == K is the 50-point mark; wallpaper is priced per column like in the shop
    c = _score(catalog, [_row(1, "paper", span=2)])  # 15 × 2 = 30 > K=24
    assert c.raw == 30 and c.base == pytest.approx(100 * 30 / 54)


def test_set_bonus_needs_a_majority_of_at_least_four_items(catalog):
    oak = [_row(1, "table"), _row(2, "bed"), _row(3, "tray"), _row(4, "tray")]  # 100 + 60 + 10 + 5 = 175 oak
    c = _score(catalog, [*oak, _row(5, "cup")])  # + 10 pine → share 175/185
    assert c.set == "oak" and c.set_share == pytest.approx(175 / 185)
    assert c.mult == pytest.approx(1 + 0.5 * ((175 / 185 - 0.5) / 0.5))
    assert c.score == min(100, round(c.base * c.mult))
    # only three oak items → no bonus even though they dominate
    c = _score(catalog, [_row(1, "table"), _row(2, "bed"), _row(3, "tray"), _row(5, "cup")])
    assert c.set is None and c.mult == 1.0
    # four oak items that are a minority of the furniture value → no bonus either
    c = _score(catalog, [_row(1, "tray"), _row(2, "tray"), _row(3, "tray"), _row(4, "tray"), _row(5, "chair")])
    assert c.set is None and c.mult == 1.0 and c.set_share == pytest.approx(18.75 / 68.75)
    # rugs and wallpaper never enter the share
    c = _score(catalog, [*oak, _row(5, "rug"), _row(6, "paper", span=4)])
    assert c.set == "oak" and c.set_share == 1.0 and c.mult == 1.5


def test_ruined_penalty_affection_bonus_and_caps(catalog):
    c = _score(catalog, [_row(1, "cup"), _row(2, "junk"), _row(3, "junk")])  # base ≈ 29.4 − 10
    assert c.ruined == 2 and c.score == round(c.base) - 10
    assert _score(catalog, [_row(1, "junk")] * 5).score == 0  # never below 0
    c = _score(catalog, [_row(1, "cup")], affection=3)
    assert c.affection == 3 and c.score == round(c.base) + 9
    many = [_row(i, "table") for i in range(1, 6)] + [_row(10, "bed"), _row(11, "tray"), _row(12, "tray")]
    assert _score(catalog, many, affection=3).score == 100  # never above 100


def test_guest_count_and_pay_bands():
    assert guest_count(90, 0, RULES) == 0  # no bed, no guests
    assert guest_count(9, 2, RULES) == 0  # too shabby
    assert [guest_count(s, 5, RULES) for s in (10, 33, 34, 67, 68, 100)] == [1, 1, 2, 2, 3, 3]
    assert guest_count(100, 2, RULES) == 2  # beds cap the count
    assert [pay_per_guest(s, RULES) for s in (20, 50, 85)] == [11, 22, 35]
    assert nightly_pay(50, 2, RULES) == (2, 44)
    assert nightly_pay(50, 0, RULES) == (0, 0)


def test_shipped_guests_json_validates():
    cfg = load_config(Path(__file__).resolve().parents[2] / "data" / "guests.json")
    assert cfg.guests.max_guests == 3 and cfg.reservation.lead_days == (2, 4) and cfg.dog.tag == "dog"
