"""Freshness and size guard for data/bus-network.json, complementing the schema checks in test_network_data.py.

Pure Python, offline. Counts are compared with tests/data_baseline.json (10 percent tolerance); the file must stay
under 1.5 MB; the feed end date must still be in the future, so a stale snapshot turns CI red before users see it.
"""
import datetime
import json
import pathlib

FAST = {"test_data_sanity"}
TOLERANCE = 0.10
HERE = pathlib.Path(__file__).resolve().parent


def test_data_sanity(root):
    path = pathlib.Path(root) / "data" / "bus-network.json"
    base = json.loads((HERE / "data_baseline.json").read_text(encoding="utf-8"))
    size = path.stat().st_size
    assert size < base["max_bytes"], f"bus-network.json is {size} bytes, limit {base['max_bytes']}"
    d = json.loads(path.read_text(encoding="utf-8"))
    actual = {"routes": len({p["route"] for p in d["patterns"]}), "stops": len(d["stops"]), "patterns": len(d["patterns"])}
    off = []
    for k, n in actual.items():
        lo, hi = base[k] * (1 - TOLERANCE), base[k] * (1 + TOLERANCE)
        if not lo <= n <= hi:
            off.append(f"{k}={n} (expected {base[k]} +/-10%)")
    assert not off, "network size drifted from tests/data_baseline.json: " + ", ".join(off)
    end = datetime.datetime.strptime(d["feed"]["end"], "%Y%m%d").date()
    today = datetime.date.today()
    assert end > today, f"schedule feed ended {end}; regenerate with tools/build_network.py (today is {today})"
