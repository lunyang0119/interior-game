"""Tag floor-layer items that are rugs/mats/cushions with `rug` (by id/name); floor patterns stay untagged.

    python tools/preprocess/tag_rugs.py            # dry run: counts + the items that stay floor patterns
    python tools/preprocess/tag_rugs.py --apply    # write data/items.json

Idempotent (already-tagged items are skipped). Save your work in the editor *before* running it and reload the
editor page afterwards: the editor's "아이템 저장" writes its own copy of items.json and would undo the tags.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ITEMS = Path(__file__).resolve().parents[2] / "data" / "items.json"
RUG = re.compile(r"(rug|(^|_)mat(_|$)|bathmat|placemat|carpet|cushion|train_track|러그|매트|카펫|쿠션|방석|깔개)", re.I)


def main(argv: list[str]) -> None:
    apply = "--apply" in argv
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    tagged, patterns = [], []
    for it in data["items"]:
        if it["layer"] != "floor":
            continue
        tags = it.get("tags") or []
        if "rug" in tags:
            continue
        # tatami mats cover the whole floor: patterns, not rugs
        if "tatami" not in it["id"] and (RUG.search(it["id"]) or RUG.search(it.get("name", ""))):
            it["tags"] = sorted(set(tags + ["rug"]))
            tagged.append(it["id"])
        else:
            patterns.append(f'{it["id"]} ({it.get("name", "")})')
    print(f"rug: +{len(tagged)}  floor patterns (untagged): {len(patterns)}")
    if not apply:
        print("patterns:", ", ".join(patterns))
        print("(dry run — add --apply to write)")
        return
    ITEMS.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"written {ITEMS}")


if __name__ == "__main__":
    main(sys.argv[1:])
