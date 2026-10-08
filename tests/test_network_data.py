"""Integrity guard for data/bus-network.json (ARCHITECTURE.md section 12.2), produced by tools/build_network.py.

Pure Python, offline. Fails with the offending pattern/stop ids when the generated file drifts from the schema.
"""
import json
import pathlib

MAX_BYTES = 2_500_000
LAT, LNG = (39.6, 40.4), (-75.8, -74.7)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def test_network_data(root):
    root = pathlib.Path(root)
    path = root / "data" / "bus-network.json"
    assert path.exists(), "data/bus-network.json is missing; run tools/build_network.py"
    assert path.stat().st_size < MAX_BYTES, f"bus-network.json is {path.stat().st_size} bytes, budget {MAX_BYTES}"
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d.get("v") == 1, "version must be 1"
    assert isinstance(d.get("generated"), str) and len(d["generated"]) == 10, "generated must be YYYY-MM-DD"
    feed = d.get("feed")
    assert isinstance(feed, dict), "feed must be an object"
    for k in ("start", "end", "sampleDate"):
        assert isinstance(feed.get(k), str) and len(feed[k]) == 8 and feed[k].isdigit(), f"feed.{k} must be YYYYMMDD"
    assert feed["start"] <= feed["sampleDate"] <= feed["end"], "sampleDate outside the feed window"

    stops, pats = d.get("stops"), d.get("patterns")
    assert isinstance(stops, dict) and stops, "stops must be a non-empty object"
    assert isinstance(pats, list) and pats, "patterns must be a non-empty list"
    bad = [s for s, v in stops.items()
           if not (isinstance(v, list) and len(v) == 3 and _num(v[0]) and _num(v[1]) and isinstance(v[2], str))]
    assert not bad, f"malformed stops: {bad[:5]}"
    out = [s for s, v in stops.items() if not (LAT[0] <= v[0] <= LAT[1] and LNG[0] <= v[1] <= LNG[1])]
    # a few suburban routes (e.g. 135 toward Coatesville) legitimately run past the box; tolerate under 1% of stops
    assert len(out) <= 0.01 * len(stops), f"{len(out)} stops outside the Philadelphia region box: {out[:5]}"

    seen, problems = set(), []
    for p in pats:
        pid = p.get("id")
        if pid in seen:
            problems.append(f"duplicate pattern id {pid}")
        seen.add(pid)
        if not (isinstance(pid, str) and isinstance(p.get("route"), str) and p["route"]):
            problems.append(f"{pid}: id/route must be strings")
        if p.get("kind") not in ("bus", "trolley"):
            problems.append(f"{pid}: bad kind {p.get('kind')!r}")
        if p.get("dir") not in (0, 1):
            problems.append(f"{pid}: bad dir {p.get('dir')!r}")
        if not isinstance(p.get("head"), str):
            problems.append(f"{pid}: head must be a string")
        if not (isinstance(p.get("trips"), int) and p["trips"] >= 1):
            problems.append(f"{pid}: trips must be a positive int")
        if not (p.get("hw") is None or (isinstance(p["hw"], int) and p["hw"] >= 1)):
            problems.append(f"{pid}: hw must be null or a positive int")
        ss, mm = p.get("stops"), p.get("mins")
        if not (isinstance(ss, list) and isinstance(mm, list) and len(ss) >= 2):
            problems.append(f"{pid}: stops/mins must be lists with at least 2 stops")
            continue
        missing = [s for s in ss if s not in stops]
        if missing:
            problems.append(f"{pid}: stop ids not in stops: {missing[:3]}")
        if len(ss) != len(mm):
            problems.append(f"{pid}: mins length {len(mm)} != stops length {len(ss)}")
        elif not all(_num(m) for m in mm) or mm[0] != 0 or any(b < a for a, b in zip(mm, mm[1:])):
            problems.append(f"{pid}: mins must be numbers, start at 0 and be non-decreasing")
        elif any(m * 2 != int(m * 2) for m in mm):
            problems.append(f"{pid}: mins must be in 0.5 steps")
    assert not problems, "; ".join(problems[:8]) + (f" (+{len(problems) - 8} more)" if len(problems) > 8 else "")

    routes = {p["route"] for p in pats}
    assert len(routes) >= 100, f"only {len(routes)} distinct routes"
    for r in ("47", "45"):
        assert any(p["route"] == r for p in pats), f"route {r} has no pattern"

    fx = json.loads((root / "tests" / "fixtures" / "TransitView.json").read_text(encoding="utf-8"))
    ids = {str(b["route_id"]) for b in fx["bus"] if str(b.get("route_id", "")).isdigit()}
    assert ids, "fixture has no numeric route ids"
    cov = len(ids & routes) / len(ids)
    assert cov >= 0.9, f"only {cov:.0%} of fixture numeric route ids exist in the network: {sorted(ids - routes)}"
