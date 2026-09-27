"""Phase 3: the overworld map is validated at startup like rooms."""
import importlib
import json
import sys


def _reload_catalog():
    importlib.reload(sys.modules["app.catalog"])
    from app import catalog as cm
    return cm


def test_map_loads(catalog):
    m = catalog.map
    assert m is not None and m.cols == 8 and m.places[0].doors == [[3, 2]] and m.places[1].room == "dock"
    assert m.layers["ground"][0][0] == "g"


def test_map_rejects_bad_data(env):
    p = env["data"] / "map.json"
    base = json.loads(p.read_text(encoding="utf-8"))
    for mutate, needle in [
        (lambda m: m["places"][0].update(room="nowhere"), "unknown room"),
        (lambda m: m["places"][0].update(sprite="nope"), "not in the map atlas"),
        (lambda m: m["layers"]["ground"][0].__setitem__(0, "lava"), "tile 'lava'"),
        (lambda m: m["places"][0]["doors"].append([99, 0]), "door outside"),
        (lambda m: m["decos"].append({"sprite": "ghost", "x": 0, "y": 0}), "deco sprite"),
    ]:
        m = json.loads(json.dumps(base))
        mutate(m)
        p.write_text(json.dumps(m), encoding="utf-8")
        try:
            _reload_catalog().load()
            assert False, needle
        except ValueError as e:
            assert needle in str(e), (needle, str(e))
    p.unlink()
    assert _reload_catalog().load().map is None  # optional file
    p.write_text(json.dumps(base), encoding="utf-8")
    _reload_catalog()
