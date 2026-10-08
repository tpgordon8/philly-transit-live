"""Schema-drift guard: every fixture record the app depends on has the keys and types the code reads.

If SEPTA changes a field and a fixture is refreshed from live data, this fails with the missing key names instead of a
vague UI failure. Offline, no browser. Keep in step with normBuses / normTrains / buildAlerts / renderAlerts /
openStop in index.html.
"""
from harness import load_fixtures

STR, NUM, NULLABLE_STR, NULLABLE_NUM = "str", "num", "str|null", "num|null"


def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    return type(v).__name__


def _numeric_string(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _check(name, records, spec, numeric_strings=()):
    assert isinstance(records, list) and records, f"{name}: expected a non-empty list"
    missing, wrong = {}, {}
    for i, r in enumerate(records):
        assert isinstance(r, dict), f"{name}[{i}] is not an object"
        for key, want in spec.items():
            if key not in r:
                missing.setdefault(key, []).append(i)
                continue
            allowed = set(want.split("|"))
            if _kind(r[key]) not in allowed:
                wrong.setdefault(key, []).append((i, _kind(r[key])))
            elif key in numeric_strings and r[key] is not None and not _numeric_string(r[key]):
                wrong.setdefault(key, []).append((i, "non-numeric string"))
    problems = []
    if missing:
        problems.append("missing keys: " + ", ".join(f"{k} ({len(v)} records, first #{v[0]})" for k, v in missing.items()))
    if wrong:
        problems.append("wrong types: " + ", ".join(f"{k} ({len(v)} records, first #{v[0][0]} is {v[0][1]}, want {spec[k]})" for k, v in wrong.items()))
    assert not problems, f"{name} fixture drifted from what index.html reads. " + " | ".join(problems)


def test_fixtures_all_parse(root):
    fx = load_fixtures()
    for n in ("TransitView", "TrainView", "Alerts", "Stops"):
        assert n in fx, f"fixture {n}.json missing"


def test_transitview_bus_schema(root):
    d = load_fixtures()["TransitView"]
    assert isinstance(d, dict) and "bus" in d, "TransitView: top-level key 'bus' missing"
    _check("TransitView.bus", d["bus"], {
        "lat": STR, "lng": STR, "VehicleID": STR, "label": STR, "route_id": STR, "timestamp": NUM,
        "heading": NULLABLE_NUM, "late": NUM, "next_stop_id": NULLABLE_STR, "Direction": STR,
        "destination": STR, "next_stop_name": NULLABLE_STR, "estimated_seat_availability": STR,
    }, numeric_strings=("lat", "lng"))


def test_trainview_schema(root):
    _check("TrainView", load_fixtures()["TrainView"], {
        "lat": STR, "lon": STR, "trainno": STR, "line": STR, "heading": "str|num|null", "dest": STR,
        "nextstop": STR, "currentstop": STR, "late": NUM, "TRACK": STR, "service": STR, "SOURCE": STR,
    }, numeric_strings=("lat", "lon"))


def test_alerts_schema(root):
    alerts = load_fixtures()["Alerts"]
    _check("Alerts", alerts, {
        "mode": STR, "route": STR, "route_name": STR, "description": STR, "alert": STR, "advisory": STR,
        "isalert": STR, "isadvisory": STR, "isdetour": STR, "detour": "list",
    })
    detours = [d for a in alerts for d in a["detour"]]
    assert detours, "Alerts: no fixture record carries a detour entry, so the detour path is untested"
    _check("Alerts.detour[]", detours, {"location_start": STR, "message": STR, "reason": STR, "start": STR, "end": STR})


def test_stops_schema(root):
    stops = load_fixtures()["Stops"]
    assert isinstance(stops, dict) and stops, "Stops: expected a route-id -> list mapping"
    for route, lst in stops.items():
        _check(f"Stops[{route}]", lst, {"lat": STR, "lng": STR, "stopid": STR, "stopname": STR}, numeric_strings=("lat", "lng"))
