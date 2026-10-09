"""Live check of the suggestion data source (Photon) and of the built-in places. Needs network; NOT part of tests/run.py.

    python3 tests/live_suggest.py                # Photon: CORS, response shape, 'city hall', '1234 market st', '10th and race'
    python3 tests/live_suggest.py --landmarks    # also check every built-in place in js/landmarks.js against Nominatim (about 1 minute)

Prints one PASS/FAIL line per check and exits 1 if any check failed. Stdlib only. Run it when suggestions look wrong, and after
editing js/landmarks.js. It makes about 5 Photon requests (one a second); --landmarks adds one Nominatim request per place at
1.1 s spacing, with a User-Agent that names this project.
"""
import argparse
import json
import math
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PHOTON = "https://photon.komoot.io/api/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
ORIGIN = "https://tpgordon8.github.io"
BOX = (-75.5, 39.7, -74.8, 40.2)  # west, south, east, north: the same box js/suggest.js sends and applies
BIAS = (39.95, -75.16)
UA = "philly-transit-live-live-check/1 (+https://tpgordon8.github.io/philly-transit-live/)"
LANDMARKS = pathlib.Path(__file__).resolve().parent.parent / "js" / "landmarks.js"


def get(url, origin=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Origin": origin} if origin else {})})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, r.headers, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:  # a shared network address can hit the services' rate limits: wait and retry
                raise
            time.sleep(10)


def photon(q):
    url = (f"{PHOTON}?q={urllib.parse.quote(q)}&lat={BIAS[0]:.2f}&lon={BIAS[1]:.2f}&limit=6"
           f"&bbox={','.join(str(x) for x in BOX)}&lang=en")
    time.sleep(1.1)  # the page makes at most one request a second; so does this script
    return get(url, ORIGIN)


def metres(a, b):
    p = math.pi / 180
    x = math.sin((b[0] - a[0]) * p / 2) ** 2 + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(x))


def latlng(f):
    c = f["geometry"]["coordinates"]
    return (c[1], c[0])


def inside(f):
    lat, lng = latlng(f)
    return BOX[1] <= lat <= BOX[3] and BOX[0] <= lng <= BOX[2]


def run(landmarks):
    results = []

    def check(name, fn):
        try:
            note = fn()
            results.append((True, name, note or ""))
        except AssertionError as e:
            results.append((False, name, str(e)))
        except Exception as e:  # noqa: BLE001  (network errors, bad JSON)
            results.append((False, name, f"{e.__class__.__name__}: {e}"))

    def shape_and_cors():
        st, h, d = photon("city hall")
        assert st == 200, f"HTTP {st}"
        assert h.get("Access-Control-Allow-Origin") in ("*", ORIGIN), f"CORS header: {h.get('Access-Control-Allow-Origin')!r}"
        assert d.get("type") == "FeatureCollection" and d["features"], "not a non-empty FeatureCollection"
        for f in d["features"]:
            assert f["geometry"]["type"] == "Point" and len(f["geometry"]["coordinates"]) == 2, f["geometry"]
            p = f["properties"]
            assert "osm_value" in p and ("name" in p or "street" in p), p
        assert len(d["features"]) <= 6, "limit=6 not honoured"
        return f"{len(d['features'])} features, CORS {h.get('Access-Control-Allow-Origin')}"

    def city_hall():
        _, _, d = photon("city hall")
        hits = [f for f in d["features"] if inside(f) and f["properties"].get("name") == "Philadelphia City Hall"]
        assert hits, [f["properties"].get("name") for f in d["features"]]
        p = hits[0]["properties"]
        assert p.get("housenumber") == "1" and p.get("street") == "Penn Square" and p.get("city") == "Philadelphia" and p.get("state") == "Pennsylvania", p
        assert metres(latlng(hits[0]), (39.95240, -75.16299)) < 150, latlng(hits[0])
        return "Philadelphia City Hall, 1 Penn Square, Philadelphia, Pennsylvania"

    def market_address():
        _, _, d = photon("1234 market st")
        hits = [f for f in d["features"] if inside(f) and f["properties"].get("housenumber") == "1234" and "Market" in (f["properties"].get("street") or "")]
        assert hits, [(f["properties"].get("housenumber"), f["properties"].get("street")) for f in d["features"]]
        p = hits[0]["properties"]
        assert p.get("city") == "Philadelphia", p
        return f"name {p.get('name')!r}, street {p.get('street')!r}, at {latlng(hits[0])}"

    def intersection_is_not_answered():
        _, _, d = photon("10th and race")
        names = [f["properties"].get("name") for f in d["features"]]
        assert not any(n and "10th" in n.lower() and "race" in n.lower() for n in names), f"Photon now answers intersections: {names}"
        return "no intersection result, as the page assumes (it sends these to Nominatim instead): " + ", ".join(str(n) for n in names[:3])

    check("Photon: CORS and response shape", shape_and_cors)
    check("Photon: 'city hall' offers Philadelphia City Hall with its address", city_hall)
    check("Photon: '1234 market st' offers the street address", market_address)
    check("Photon: '10th and race' is not answered as an intersection", intersection_is_not_answered)

    if landmarks:
        text = LANDMARKS.read_text()
        rows = re.findall(r"^\s+(['\"])(.+?)\1,?$", text, flags=re.M)
        for _, row in rows:
            name, _aliases, addr, lat, lng = row.split("|")
            city = addr.split(",")[-2].strip()  # "6901 Market St, Upper Darby, PA" -> Upper Darby

            def one(name=name, city=city, lat=float(lat), lng=float(lng)):
                time.sleep(1.5)
                q = re.sub(r"\s*\(.*\)", "", name)
                _, _, d = get(f"{NOMINATIM}?format=jsonv2&limit=3&viewbox=-75.5,40.2,-74.8,39.7&q={urllib.parse.quote(q + ' ' + city)}")
                dist = [round(metres((lat, lng), (float(x["lat"]), float(x["lon"])))) for x in d]
                assert dist and min(dist) <= 50, f"nearest of the top results is {min(dist) if dist else None} m away (limit 50 m): {dist}"
                return f"{min(dist)} m"

            check(f"Landmark {name}", one)

    for ok, name, note in results:
        print(("PASS" if ok else "FAIL"), name + (f": {note}" if note else ""))
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--landmarks", action="store_true", help="also verify js/landmarks.js against Nominatim")
    sys.exit(run(ap.parse_args().landmarks))
