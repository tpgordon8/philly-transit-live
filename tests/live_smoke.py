"""Live smoke test against the DEPLOYED Worker. Needs network; NOT part of tests/run.py.

    python3 tests/live_smoke.py [--worker URL]

Prints one PASS/FAIL line per check and exits 1 if any check failed. Stdlib only. Run it after pasting a new
worker/worker.js into the Cloudflare dashboard, and whenever SEPTA's feeds look wrong.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

WORKER = "https://septa-proxy.tpgordon8.workers.dev"
ORIGIN = "https://tpgordon8.github.io"

BUS_KEYS = ["lat", "lng", "VehicleID", "label", "route_id", "timestamp", "heading", "late", "next_stop_id",
            "Direction", "destination", "next_stop_name", "estimated_seat_availability"]
TRAIN_KEYS = ["lat", "lon", "trainno", "line", "heading", "dest", "nextstop", "currentstop", "late", "TRACK", "service", "SOURCE"]
STOP_KEYS = ["stopid", "stopname", "lat", "lng"]


def get(base, path, origin=ORIGIN):
    """Return (status, headers, body_text). HTTP errors are returned, not raised."""
    req = urllib.request.Request(base + path, headers={"User-Agent": "philly-transit-live-smoke/1", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def missing(records, keys, sample=5):
    return sorted({k for r in records[:sample] for k in keys if k not in r})


def run(base):
    results = []

    def check(name, fn):
        try:
            fn()
            results.append((True, name, ""))
        except AssertionError as e:
            results.append((False, name, str(e)))
        except Exception as e:  # noqa: BLE001  (network errors, bad JSON)
            results.append((False, name, f"{e.__class__.__name__}: {e}"))

    def transitview():
        st, h, body = get(base, "/TransitView")
        assert st == 200, f"HTTP {st}"
        d = json.loads(body)
        assert isinstance(d, dict) and isinstance(d.get("bus"), list) and d["bus"], "no non-empty 'bus' list"
        m = missing(d["bus"], BUS_KEYS)
        assert not m, f"first records lack keys: {m}"
        assert "access-control-allow-origin" in {k.lower() for k in h.keys()}, "no CORS header"

    def trainview():
        st, _, body = get(base, "/TrainView")
        assert st == 200, f"HTTP {st}"
        d = json.loads(body)
        assert isinstance(d, list) and d, "expected a non-empty list"
        m = missing(d, TRAIN_KEYS)
        assert not m, f"first records lack keys: {m}"

    def alerts():
        st, _, body = get(base, "/Alerts")
        assert st == 200, f"HTTP {st}"
        assert isinstance(json.loads(body), list), "expected a list"

    def stops():
        st, _, body = get(base, "/Stops?route=21")
        assert st == 200, f"HTTP {st}"
        d = json.loads(body)
        assert isinstance(d, list) and d, "expected a non-empty list"
        m = missing(d, STOP_KEYS)
        assert not m, f"first records lack keys: {m}"

    def arrivals():
        st, _, body = get(base, "/Arrivals?station=Suburban%20Station")
        assert st == 200, f"HTTP {st}"
        assert isinstance(json.loads(body), (dict, list)), "expected JSON"

    def cors():
        st, h, _ = get(base, "/Alerts")
        assert st == 200, f"HTTP {st}"
        assert h.get("Access-Control-Allow-Origin") == ORIGIN, f"got {h.get('Access-Control-Allow-Origin')!r}"

    def foreign():
        st, _, _ = get(base, "/Alerts", origin="https://evil.example")
        assert st == 403, f"HTTP {st}, want 403"

    def bad_params():
        for p in ("/Stops", "/Stops?route=../x", "/Arrivals?station=a"):
            st, _, _ = get(base, p)
            assert st == 400, f"{p} gave HTTP {st}, want 400"

    def route():
        for prof in ("foot", "bike", "car"):
            st, h, body = get(base, f"/route/{prof}?from=39.9526,-75.1652&to=39.9496,-75.1503")
            assert st == 200, f"{prof}: HTTP {st}"
            d = json.loads(body)
            assert d.get("code") == "Ok" and d["routes"], f"{prof}: no route"
            r = d["routes"][0]
            assert r["distance"] > 0 and r["duration"] > 0, f"{prof}: distance/duration"
            assert len(r["geometry"]["coordinates"]) >= 2, f"{prof}: geometry"

    def route_bad():
        for p in ("/route/foot", "/route/foot?from=0,0&to=39.95,-75.16", "/route/foot?from=NaN,-75.16&to=39.95,-75.16",
                  "/route/foot?from=48.85,2.35&to=39.95,-75.16"):
            st, _, _ = get(base, p)
            assert st == 400, f"{p} gave HTTP {st}, want 400"
        st, _, _ = get(base, "/route/boat?from=39.95,-75.16&to=39.96,-75.15")
        assert st == 404, f"/route/boat gave HTTP {st}, want 404"

    def indego():
        st, _, body = get(base, "/indego/information")
        assert st == 200, f"information: HTTP {st}"
        info = json.loads(body)["data"]["stations"]
        assert info and {"station_id", "name", "lat", "lon"} <= set(info[0]), "information keys"
        st, _, body = get(base, "/indego/status")
        assert st == 200, f"status: HTTP {st}"
        stat = json.loads(body)["data"]["stations"]
        assert stat and {"station_id", "num_bikes_available", "num_docks_available", "is_renting", "is_returning"} <= set(stat[0]), "status keys"

    def null_origin():
        for o in ("null", ""):
            # The Cloudflare edge drops an empty Origin header, so an empty one reaches the Worker as "no Origin". On /Alerts that is
            # allowed (curl); on /indego it is refused either way, so test the empty value there.
            path = "/Alerts" if o == "null" else "/indego/status"
            req = urllib.request.Request(base + path, headers={"User-Agent": "philly-transit-live-smoke/1", "Origin": o})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            assert code == 403, f"Origin {o!r} gave HTTP {code}, want 403"

    def localhost_origin():
        st, h, _ = get(base, "/Alerts", origin="http://localhost:8765")
        assert st == 200 and h.get("Access-Control-Allow-Origin") == "http://localhost:8765", f"HTTP {st}, ACAO {h.get('Access-Control-Allow-Origin')!r}"

    def no_origin_refused():
        # /route and /indego spend a third party's capacity: a request without an allowed Origin (curl, a script) is refused
        for p in ("/route/foot?from=39.9526,-75.1652&to=39.9496,-75.1503", "/indego/status", "/indego/information"):
            st, _, _ = get(base, p, origin=None)
            assert st == 403, f"{p} without an Origin gave HTTP {st}, want 403"
            st, _, _ = get(base, p, origin="https://evil.example")
            assert st == 403, f"{p} with a foreign Origin gave HTTP {st}, want 403"

    def unknown():
        st, _, _ = get(base, "/nope")
        assert st == 404, f"HTTP {st}, want 404"

    check("TransitView: JSON with non-empty bus list and the keys the app reads", transitview)
    check("TrainView: list with the keys the app reads", trainview)
    check("Alerts: list", alerts)
    check("Stops?route=21: non-empty list with stopid/stopname/lat/lng", stops)
    check("Arrivals?station=Suburban Station: JSON", arrivals)
    check(f"CORS: Access-Control-Allow-Origin is {ORIGIN}", cors)
    check("Foreign Origin gets 403", foreign)
    check("Bad parameters get 400", bad_params)
    check("Unknown path gets 404", unknown)
    check("/route/<foot|bike|car>: OSRM route with distance, duration, geometry", route)
    check("/route: bad input gets 400, unknown profile 404", route_bad)
    check("/indego/information and /indego/status: GBFS station lists", indego)
    check("/route and /indego without an allowed Origin get 403", no_origin_refused)
    check("Origin 'null' and empty Origin get 403", null_origin)
    check("localhost origin on any port is allowed", localhost_origin)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", default=WORKER)
    args = ap.parse_args()
    results = run(args.worker.rstrip("/"))
    for ok, name, why in results:
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  -- {why}"))
    bad = sum(1 for r in results if not r[0])
    print(f"\n{len(results) - bad} passed, {bad} failed  ({args.worker})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
