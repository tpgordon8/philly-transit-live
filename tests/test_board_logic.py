"""My stops board, logic (ARCHITECTURE.md 15.8): septa.board.v1 storage, walking time, the leave states, countdowns between feed
refreshes, feed outages, vehicles leaving the feed, and the "Pin to board" button on the stop card.

The state tables run against synthetic arrivals: the page's S.stops.boardRows is replaced by a stub that returns the buses the test
names, then S.board.refresh() captures them exactly as a feed refresh would. The feed tests use the real mock feed.
Each fast test runs its check again on a copy of the site with one line broken (`must_fail`) and must fail there."""
import json
import math

from harness import Session
from test_first_run import must_fail, seed
from test_stop_board import SID, SLAT, SLNG, SROUTE, buses, setup_moving, step

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_storage_is_read_defensively",
    "test_walk_minutes_automatic_override_and_no_place",
    "test_leave_states_table",
    "test_pins_caps_duplicates_and_updates",
    "test_pin_button_flow",
}

KEY = "septa.board.v1"
HASH = f"#stop={SID}&route={SROUTE}"
T0 = 1_000_000_000_000
PLACES = {"home": {"name": "Home", "lat": 39.9500, "lng": -75.1600}, "list": [{"id": "p1", "name": "Gym", "lat": 39.9600, "lng": -75.1700}]}


def pin(i=0, **kw):
    d = {"id": f"id{i}", "label": f"L{i}", "placeId": None, "route": "21", "stopId": str(100 + i), "stopName": f"Stop {i}",
         "lat": 39.95, "lng": -75.16, "walkMin": None}
    d.update(kw)
    return d


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()
    s.settle()


def js(s, code, arg=None):
    return s.page.evaluate(code, arg)


def ls(s, key):
    raw = js(s, "(k) => localStorage.getItem(k)", key)
    return None if raw is None else json.loads(raw)


def stored_raw(s, key):
    return js(s, "(k) => localStorage.getItem(k)", key)


# ---------------------------------------------------------------- storage
def check_storage(root):
    junk = [
        pin(0),  # fine
        pin(1, route="bad route"), pin(2, stopId="12x"), pin(3, lat="39.9"), pin(4, lng=None), pin(5, walkMin=0), pin(6, walkMin=61),
        pin(7, walkMin=1.5), pin(8, walkMin="5"), pin(9, id=""), pin(10, id="has space"), "text", None, 7, [],
        pin(11, id="id0", stopId="200"),  # repeated id
        pin(12, stopId="100"),  # repeated route + stop + place (same as pin 0)
        pin(13, label="x" * 80, stopName="y" * 90, walkMin=60),
        pin(14, placeId="home"), pin(15, stopId="101", placeId="home"),  # the same stop for another place is fine
    ]
    raw = json.dumps({"pins": junk, "bufferMin": 99, "bad": "yes"})
    with Session(root, init_scripts=[seed(KEY, raw)]) as s:
        boot(s)
        pins = js(s, "window.SEPTA.board.pins()")
        assert [p["id"] for p in pins] == ["id0", "id13", "id14", "id15"], [p["id"] for p in pins]
        p13 = pins[1]
        assert len(p13["label"]) <= 30 and len(p13["stopName"]) <= 60 and p13["walkMin"] == 60, p13
        assert pins[0]["walkMin"] is None and pins[0]["placeId"] is None and pins[2]["placeId"] == "home"
        assert js(s, "window.SEPTA.board.settings()") == {"bufferMin": 2, "bad": False}
        assert stored_raw(s, KEY + ".bak") == raw, "a load that drops something keeps the original text"
        assert js(s, "window.SEPTA.board.pins().length") == 4
    for text in ("not json {", "[1,2]", '"x"', "null", json.dumps({"pins": "no"})):
        with Session(root, init_scripts=[seed(KEY, text)]) as s:
            boot(s)
            assert js(s, "window.SEPTA.board.pins()") == [] and js(s, "window.SEPTA.board.settings()") == {"bufferMin": 2, "bad": False}, text
            if text != "null":
                assert stored_raw(s, KEY + ".bak") == text, text
    many = json.dumps({"pins": [pin(i) for i in range(12)], "bufferMin": 15, "bad": True})
    with Session(root, init_scripts=[seed(KEY, many)]) as s:
        boot(s)
        assert js(s, "window.SEPTA.board.pins().length") == 8
        assert js(s, "window.SEPTA.board.settings()") == {"bufferMin": 15, "bad": True}
        assert stored_raw(s, KEY + ".bak") == many
    good = json.dumps({"pins": [pin(0), pin(1, walkMin=7, placeId="home")], "bufferMin": 0, "bad": False})
    with Session(root, init_scripts=[seed(KEY, good)]) as s:
        boot(s)
        assert js(s, "window.SEPTA.board.pins().length") == 2 and js(s, "window.SEPTA.board.settings().bufferMin") == 0
        assert stored_raw(s, KEY + ".bak") is None, "a clean board is not backed up"
    with Session(root) as s:  # nothing saved: defaults, and nothing written until the rider pins something
        boot(s)
        assert js(s, "window.SEPTA.board.settings()") == {"bufferMin": 2, "bad": False} and stored_raw(s, KEY) is None
    quota = "Storage.prototype.setItem = function (k) { if (/^septa\\.board/.test(k)) throw new DOMException('full', 'QuotaExceededError'); };"
    with Session(root, init_scripts=[quota]) as s:  # a failed save raises the one "Can't save" toast and says so in the result
        boot(s)
        r = js(s, "window.SEPTA.board.addPin({route: '21', stopId: '14880', stopName: 'A', lat: 39.9, lng: -75.1})")
        assert r["ok"] and r["saved"] is False, r
        s.page.wait_for_selector("#toasts .toast")
        assert "Can't save on this device" in s.page.inner_text("#toasts"), s.page.inner_text("#toasts")


def test_storage_is_read_defensively(root):
    check_storage(root)
    must_fail(check_storage, root, ("js/board.js", "dups[pinKey(p.route, p.stopId, p.placeId)]) return;", "false) return;"))


# ---------------------------------------------------------------- pins
ADD = "(o) => window.SEPTA.board.addPin(o)"


def check_pins(root):
    seed_places = seed("septa.places.v1", PLACES)
    with Session(root, init_scripts=[seed_places]) as s:
        boot(s)
        base = {"route": "21", "stopId": "14880", "stopName": "Market St & 15th", "lat": 39.95, "lng": -75.16}
        for bad in ({"route": "no way"}, {"stopId": "abc"}, {"lat": float("nan")}, {"lng": None}, {"walkMin": 0}, {"walkMin": 61}, {"walkMin": 2.5},
                    {"placeId": "ghost"}, {"placeId": 5}):
            if "lat" in bad and bad["lat"] != bad["lat"]:
                r = js(s, "(o) => { o.lat = NaN; return window.SEPTA.board.addPin(o); }", dict(base))
            else:
                r = js(s, ADD, dict(base, **bad))
            assert r == {"ok": False, "reason": "invalid"}, (bad, r)
        r = js(s, ADD, dict(base, label="  A very long label that goes on and on forever  ", placeId="home", walkMin=7))
        assert r["ok"] and r["pin"]["walkMin"] == 7 and len(r["pin"]["label"]) <= 30 and r["pin"]["placeId"] == "home", r
        first = r["pin"]["id"]
        assert js(s, ADD, dict(base, placeId="home")) == {"ok": False, "reason": "duplicate"}
        r2 = js(s, ADD, dict(base, placeId="p1"))
        assert r2["ok"], r2  # same stop for another place
        assert js(s, ADD, dict(base, placeId=None))["ok"] and js(s, ADD, dict(base, placeId=None)) == {"ok": False, "reason": "duplicate"}
        assert ls(s, KEY)["pins"][0]["id"] == first and len(ls(s, KEY)["pins"]) == 3, "saved to localStorage"
        # full at 8
        for i in range(5):
            assert js(s, ADD, dict(base, stopId=str(300 + i), placeId="home"))["ok"], i
        assert js(s, "window.SEPTA.board.pins().length") == 8
        assert js(s, ADD, dict(base, stopId="999")) == {"ok": False, "reason": "full"}
        assert js(s, ADD, dict(base, placeId="home")) == {"ok": False, "reason": "duplicate"}, "a duplicate on a full board is reported as a duplicate"
        # update
        B = "window.SEPTA.board"
        assert js(s, f"({B}.updatePin('{first}', {{walkMin: 61}}))") is False
        assert js(s, f"({B}.updatePin('{first}', {{walkMin: 0}}))") is False
        assert js(s, f"({B}.updatePin('{first}', {{placeId: 'ghost'}}))") is False
        assert js(s, f"({B}.updatePin('{first}', {{placeId: 'p1'}}))") is False, "moving onto an existing pin would duplicate it"
        assert js(s, f"({B}.updatePin('nope', {{walkMin: 3}}))") is False
        assert js(s, f"({B}.updatePin('{first}', {{walkMin: 9, label: 'Bus to work'}}))") is True
        got = next(p for p in js(s, B + ".pins()") if p["id"] == first)
        assert got["walkMin"] == 9 and got["label"] == "Bus to work"
        assert js(s, f"({B}.updatePin('{first}', {{walkMin: null}}))") is True
        assert next(p for p in ls(s, KEY)["pins"] if p["id"] == first)["walkMin"] is None
        # pins() returns copies
        js(s, f"{B}.pins()[0].label = 'hacked'")
        assert js(s, B + ".pins()[0].label") != "hacked"
        # settings
        assert js(s, f"{B}.setSettings({{bufferMin: 16}})") is False and js(s, f"{B}.setSettings({{bufferMin: -1}})") is False
        assert js(s, f"{B}.setSettings({{bufferMin: 1.5}})") is False and js(s, f"{B}.setSettings({{bad: 'true'}})") is False
        assert js(s, f"{B}.setSettings({{bufferMin: 5, bad: true}})") is True
        assert js(s, B + ".settings()") == {"bufferMin": 5, "bad": True}
        assert ls(s, KEY)["bufferMin"] == 5 and ls(s, KEY)["bad"] is True
        assert js(s, f"{B}.setSettings({{bufferMin: 4, bad: 'x'}})") is False and js(s, B + ".settings().bufferMin") == 5, "a bad patch changes nothing"
        # change callbacks: pins, settings, and every feed apply
        js(s, f"window.__n = 0; {B}.onChange(() => window.__n++)")
        js(s, f"{B}.setSettings({{bad: false}})")
        assert js(s, "window.__n") == 1
        assert js(s, f"{B}.removePin('{first}')") is True and js(s, f"{B}.removePin('{first}')") is False
        assert js(s, "window.__n") == 2 and len(ls(s, KEY)["pins"]) == 7
        s.tick(16000)
        assert js(s, "window.__n") >= 3, "fires after a feed apply"


def test_pins_caps_duplicates_and_updates(root):
    check_pins(root)
    must_fail(check_pins, root, ("js/board.js", "if (hasPin(route, stopId, placeId)) return", "if (false) return"))


# ---------------------------------------------------------------- walking time
def metres(lat1, lng1, lat2, lng2):
    """The same flat-earth distance js/util.js uses (miles x metres per mile) is within a few percent of this; tests stay off the rounding edges."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def check_walk(root):
    home, gym = PLACES["home"], PLACES["list"][0]
    with Session(root, init_scripts=[seed("septa.places.v1", PLACES)]) as s:
        boot(s)
        # a stop about 1000 m north of home and one 40 m away
        far = (home["lat"] + 1000 / 111195.0, home["lng"])
        near = (home["lat"] + 40 / 111195.0, home["lng"])
        mk = lambda lat, lng, **kw: dict(route="21", stopId="500", stopName="S", lat=lat, lng=lng, **kw)
        out = js(s, """([far, near, gymStop]) => { const B = window.SEPTA.board, r = {};
            r.auto = B.walkMin(B.addPin(far).pin);
            r.near = B.walkMin(B.addPin(near).pin);
            r.over = B.walkMin(B.addPin(Object.assign({}, far, {stopId: '501', walkMin: 3})).pin);
            r.gym = B.walkMin(B.addPin(gymStop).pin);
            r.none = B.walkMin(B.addPin(Object.assign({}, far, {stopId: '502', placeId: null})).pin);
            const p = B.pins().find(x => x.stopId === '501'); r.place = B.placeFor(p);
            const q = B.pins().find(x => x.stopId === '502'); r.noplace = B.placeFor(q);
            // delete the saved place: the pin keeps its id, loses its place, and falls back to 5 minutes
            window.SEPTA.util.state.places.list.length = 0;
            r.gone = B.walkMin(B.pins().find(x => x.placeId === 'p1'));
            r.gonePlace = B.placeFor(B.pins().find(x => x.placeId === 'p1'));
            window.SEPTA.util.state.places.home = null;
            r.nohome = B.walkMin(B.pins().find(x => x.stopId === '500' && x.placeId === 'home' && x.lat > 39.95005));
            return r; }""", [
            dict(mk(*far), placeId="home"), dict(mk(*near), stopId="499", placeId="home"),
            dict(mk(gym["lat"] + 800 / 111195.0, gym["lng"]), stopId="503", placeId="p1"),
        ])
        d_far = metres(home["lat"], home["lng"], *far)
        want_far = math.ceil(d_far * 1.3 / 1.25 / 60)
        assert abs(out["auto"] - want_far) <= 1 and 17 <= out["auto"] <= 18, (out, want_far)  # 1000 m x 1.3 / 1.25 / 60 = 17.3 -> 18
        assert out["near"] == 1, out  # at least one minute
        assert out["over"] == 3, out  # an override beats the place
        assert 14 <= out["gym"] <= 15, out  # 800 m -> 13.9 -> 14
        assert out["none"] == 5 and out["noplace"] is None, out
        assert out["place"] == {"name": "Home", **{k: home[k] for k in ("lat", "lng")}}, out
        assert out["gone"] == 5 and out["gonePlace"] is None, out
        assert out["nohome"] == 5, out


def test_walk_minutes_automatic_override_and_no_place(root):
    check_walk(root)
    must_fail(check_walk, root, ("js/board.js", "(distM(pl, pin) * DETOUR)", "(distM(pl, pin) * 1)"))
    must_fail(check_walk, root, ("js/board.js", "if (pin.walkMin != null) return pin.walkMin;", ""))


# ---------------------------------------------------------------- leave states
SETUP = """(cfg) => {
  const S = window.SEPTA, B = S.board;
  window.__arr = cfg.arrivals;                     // [{key, min, rough}] the stubbed boardRows reports
  S.stops.boardRows = () => ({ a: window.__arr.map(x => ({ v: { key: x.key }, d: 0.1, eta: { min: x.min, rough: !!x.rough } })), b: [] });
  S.util.state.src.bus.ok = cfg.t0; S.util.state.src.bus.stale = false;
  S.feed.collect = () => [];
  B.setSettings({ bufferMin: cfg.buffer, bad: cfg.bad });
  B.pins().forEach(p => B.removePin(p.id));
  const r = B.addPin({ route: '21', stopId: '14880', stopName: 'Market', lat: 39.95, lng: -75.16, walkMin: cfg.walk });
  B.refresh();
  return r.pin.id;
}"""

# (arrivals as minutes, walk, buffer, bad) -> (state, inMin, forKey index) ; None leave when no arrivals
TABLE = [
    ([20], 5, 2, False, ("later", 13, 0)),
    ([10], 5, 2, False, ("soon", 3, 0)),     # leaveIn 3 is soon, not later
    ([11], 5, 2, False, ("later", 4, 0)),
    ([9], 5, 2, False, ("soon", 2, 0)),
    ([8], 5, 2, False, ("soon", 1, 0)),
    ([7], 5, 2, False, ("now", 0, 0)),        # leaveIn 0
    ([5], 5, 2, False, ("now", 0, 0)),        # leaveIn -2, but arriving as the walk ends: still makeable
    ([4], 5, 2, False, ("missed", 0, 0)),     # bus comes before you could get there
    ([4, 15], 5, 2, False, ("later", 8, 1)),  # first is missed, the next one counts and is named
    ([4, 6], 5, 2, False, ("now", 0, 1)),
    ([3, 4], 5, 2, False, ("missed", 0, 0)),
    ([10], 5, 2, True, ("now", 0, 0)),        # bad weather adds 4: leaveIn -1
    ([12], 5, 2, True, ("soon", 1, 0)),       # 12 - 5 - 6 = 1
    ([13], 5, 2, True, ("soon", 2, 0)),
    ([20], 5, 2, True, ("later", 9, 0)),
    ([10], 5, 0, False, ("later", 5, 0)),
    ([10], 5, 15, False, ("now", 0, 0)),
    ([8], 1, 0, True, ("soon", 3, 0)),        # 8 - 1 - 4 = 3
    ([9], 1, 0, True, ("later", 4, 0)),
    ([30], 60, 2, False, ("missed", 0, 0)),
]


def check_table(root):
    with Session(root, init_scripts=[seed("septa.places.v1", PLACES)]) as s:
        boot(s)
        for mins, walk, buf, bad, (state, in_min, idx) in TABLE:
            arrivals = [{"key": f"k{i}", "min": m} for i, m in enumerate(mins)]
            pid = js(s, SETUP, {"arrivals": arrivals, "t0": T0, "walk": walk, "buffer": buf, "bad": bad})
            row = js(s, "(t) => window.SEPTA.board.rows(t)", T0)[0]
            case = (mins, walk, buf, bad, row["leave"])
            assert row["pin"]["id"] == pid and row["walkMin"] == walk and row["source"] == "live", case
            assert row["leave"] is not None, case
            assert row["leave"]["state"] == state and row["leave"]["inMin"] == in_min and row["leave"]["forKey"] == f"k{idx}", case
            assert [a["key"] for a in row["arrivals"]] == [f"k{i}" for i in range(len(mins))] and len(row["arrivals"]) <= 2, case
        # nothing measurable: no leave advice
        js(s, SETUP, {"arrivals": [], "t0": T0, "walk": 5, "buffer": 2, "bad": False})
        row = js(s, "(t) => window.SEPTA.board.rows(t)", T0)[0]
        assert row["arrivals"] == [] and row["leave"] is None and row["source"] == "live", row
        # at most two arrivals, soonest first, from any number of buses
        js(s, SETUP, {"arrivals": [{"key": "c", "min": 12}, {"key": "a", "min": 3}, {"key": "b", "min": 7}], "t0": T0, "walk": 2, "buffer": 2, "bad": False})
        row = js(s, "(t) => window.SEPTA.board.rows(t)", T0)[0]
        assert [a["key"] for a in row["arrivals"]] == ["a", "b"] and row["leave"]["forKey"] == "a", row
        # a rough estimate keeps its flag
        js(s, SETUP, {"arrivals": [{"key": "r", "min": 9, "rough": True}], "t0": T0, "walk": 2, "buffer": 2, "bad": False})
        assert js(s, "(t) => window.SEPTA.board.rows(t)", T0)[0]["arrivals"][0]["rough"] is True


def test_leave_states_table(root):
    check_table(root)
    must_fail(check_table, root, ("js/board.js", "Math.ceil(pick.etaMin - walk - extra)", "Math.ceil(pick.etaMin + walk - extra)"))
    must_fail(check_table, root, ("js/board.js", "state: leaveState(pick.etaMin - walk - extra)", "state: leaveState(pick.etaMin + walk - extra)"))
    must_fail(check_table, root, ("js/board.js", "(board.bad ? BAD_EXTRA_MIN : 0)", "0"))
    must_fail(check_table, root, ("js/board.js", "} else if (arrivals.length) leave = { inMin: 0, state: 'missed', forKey: arrivals[0].key };", "}"))


def test_countdown_ticks_between_refreshes_and_drops_old_data(root):
    with Session(root, init_scripts=[seed("septa.places.v1", PLACES)]) as s:
        boot(s)
        R = "(t) => window.SEPTA.board.rows(t)"
        js(s, SETUP, {"arrivals": [{"key": "a", "min": 6}, {"key": "b", "min": 25}], "t0": T0, "walk": 3, "buffer": 2, "bad": False})
        hits = len(s.worker.hits)
        r0, r1, r2 = (js(s, R, T0 + ms)[0] for ms in (0, 30_000, 90_000))
        assert abs(r0["arrivals"][0]["etaMin"] - 6) < 1e-6 and abs(r1["arrivals"][0]["etaMin"] - 5.5) < 1e-6, (r0, r1)
        assert abs(r2["arrivals"][0]["etaMin"] - 4.5) < 1e-6 and abs(r2["arrivals"][1]["etaMin"] - 23.5) < 1e-6, r2
        got = [(r["leave"]["state"], r["leave"]["inMin"]) for r in (r0, r1, r2)]
        assert got == [("soon", 1), ("soon", 1), ("now", 0)], got  # 1.0, 0.5 and -0.5 minutes to leave
        assert js(s, R, T0 - 60_000)[0]["arrivals"][0]["etaMin"] == 6, "an earlier time than the capture never adds minutes"
        # a bus that is due and past is dropped; the next one is named
        js(s, SETUP, {"arrivals": [{"key": "a", "min": 1}, {"key": "b", "min": 9}], "t0": T0, "walk": 1, "buffer": 0, "bad": False})
        r = js(s, R, T0 + 30_000)[0]
        assert [x["key"] for x in r["arrivals"]] == ["a", "b"] and r["leave"]["forKey"] == "b", r  # a is 0.5 min away and the walk is 1
        r = js(s, R, T0 + 61_000)[0]
        assert [x["key"] for x in r["arrivals"]] == ["b"] and r["leave"]["forKey"] == "b", r
        assert len(s.worker.hits) == hits, "rows() never fetches"
        # the readings themselves age out: no good feed for 120 s means 'down' and nothing is shown
        js(s, SETUP, {"arrivals": [{"key": "a", "min": 40}], "t0": T0, "walk": 3, "buffer": 2, "bad": False})
        r5 = js(s, R, T0 + 121_000)[0]
        assert r5["source"] == "down" and r5["arrivals"] == [] and r5["leave"] is None, r5
        assert js(s, R, T0 + 120_000)[0]["source"] == "live"
        js(s, "window.SEPTA.util.state.src.bus.stale = true")
        r6 = js(s, R, T0 + 30_000)[0]
        assert r6["source"] == "stale" and len(r6["arrivals"]) == 1, r6
        js(s, "window.SEPTA.util.state.src.bus.ok = 0")
        assert js(s, R, T0)[0]["source"] == "down", "never loaded"


# ---------------------------------------------------------------- the real mock feed
def arrivals_now(s, pid=None):
    return js(s, "(() => { const r = window.SEPTA.board.rows(Date.now())[0]; return r ? {source: r.source, arrivals: r.arrivals, leave: r.leave} : null; })()")


def measured_board(s):
    """Open the app, pin the fixture stop (no place), and let the moving bus 3678 become measurable."""
    setup_moving(s)
    boot(s)
    r = js(s, ADD, {"route": SROUTE, "stopId": SID, "stopName": "Fixture stop", "lat": SLAT, "lng": SLNG, "walkMin": 4})
    assert r["ok"], r
    for _ in range(3):
        step(s, "3678", 120)
    return r["pin"]["id"]


def test_feed_live_stale_down_and_vehicle_leaving(root):
    with Session(root) as s:
        measured_board(s)
        st = arrivals_now(s)
        assert st["source"] == "live" and st["arrivals"], st
        a = next(x for x in st["arrivals"] if x["key"] == "b3678")
        assert a["etaMin"] > 0 and st["leave"] is not None, st
        # a refresh with the bus gone from the feed drops it at once
        buses(s)[:] = [b for b in buses(s) if b["VehicleID"] != "3678"]
        s.tick(16000)
        st = arrivals_now(s)
        assert all(x["key"] != "b3678" for x in st["arrivals"]), st
    with Session(root) as s:
        measured_board(s)
        s.worker.mode = "http502"
        s.tick(20000, cap_ms=3000)
        s.tick(2000, cap_ms=3000)
        st = arrivals_now(s)
        assert st["source"] == "stale" and st["arrivals"], st  # last known estimate, labelled stale
        s.tick(130000, cap_ms=3000)  # past the 120 s drop
        st = arrivals_now(s)
        assert st["source"] == "down" and st["arrivals"] == [] and st["leave"] is None, st
        s.worker.mode = "ok"
        for _ in range(8):
            s.tick(15000)
            if arrivals_now(s)["source"] == "live":
                break
        assert arrivals_now(s)["source"] == "live"


# ---------------------------------------------------------------- Pin to board on the stop card
def check_pin_button(root):
    # no saved places: one tap pins with no place
    with Session(root) as s:
        boot(s, HASH)
        s.page.wait_for_selector("#pinBoard")
        btn = s.page.locator("#pinBoard")
        assert btn.inner_text() == "Pin to board" and btn.get_attribute("aria-disabled") is None
        assert btn.bounding_box()["height"] >= 44 and btn.bounding_box()["width"] >= 44
        btn.click()
        assert s.page.inner_text("#stopLive") == "Pinned to board."
        assert btn.inner_text() == "On board" and btn.get_attribute("aria-disabled") == "true"
        pins = js(s, "window.SEPTA.board.pins()")
        assert len(pins) == 1 and pins[0]["placeId"] is None and pins[0]["route"] == SROUTE and pins[0]["stopId"] == SID, pins
        assert pins[0]["lat"] == SLAT and pins[0]["lng"] == SLNG and pins[0]["stopName"], pins
        assert s.page.evaluate("document.activeElement.id") == "pinBoard", "focusable, not disabled"
        btn.click(force=True)  # aria-disabled, not disabled: Playwright would wait for "enabled"
        assert s.page.inner_text("#stopLive") == "Already on the board."
        assert len(js(s, "window.SEPTA.board.pins()")) == 1
        js(s, "window.SEPTA.board.removePin(window.SEPTA.board.pins()[0].id)")  # removed elsewhere: the button follows
        assert btn.inner_text() == "Pin to board" and btn.get_attribute("aria-disabled") is None
    # with places: a chooser
    with Session(root, init_scripts=[seed("septa.places.v1", PLACES)]) as s:
        boot(s, HASH)
        s.page.wait_for_selector("#pinBoard")
        btn = s.page.locator("#pinBoard")
        assert not s.page.locator("#pinChoose").is_visible()
        btn.click()
        opts = s.page.locator("#pinChoose button")
        assert [opts.nth(i).inner_text() for i in range(opts.count())] == ["Home", "Gym", "No place"]
        assert all(opts.nth(i).bounding_box()["height"] >= 44 for i in range(3))
        assert s.page.evaluate("document.activeElement.textContent") == "Home" and btn.get_attribute("aria-expanded") == "true"
        s.page.keyboard.press("Escape")
        assert not s.page.locator("#pinChoose").is_visible() and s.page.evaluate("document.activeElement.id") == "pinBoard"
        assert s.page.locator("#stopCard").is_visible(), "Escape closed only the chooser"
        btn.click()
        opts.nth(1).click()  # Gym
        assert s.page.inner_text("#stopLive") == "Pinned to board." and btn.inner_text() == "Pin to board"
        assert [p["placeId"] for p in js(s, "window.SEPTA.board.pins()")] == ["p1"]
        btn.click()
        opts.nth(1).click()  # Gym again
        assert s.page.inner_text("#stopLive") == "Already on the board."
        btn.click()
        opts.nth(0).click()  # Home: every place now has it
        assert btn.inner_text() == "On board" and btn.get_attribute("aria-disabled") == "true"
        assert sorted(str(p["placeId"]) for p in js(s, "window.SEPTA.board.pins()")) == ["home", "p1"]
        btn.click(force=True)  # on board: no chooser, just the message
        assert s.page.inner_text("#stopLive") == "Already on the board." and not s.page.locator("#pinChoose").is_visible()
    # a full board
    eight = json.dumps({"pins": [pin(i) for i in range(8)], "bufferMin": 2, "bad": False})
    with Session(root, init_scripts=[seed(KEY, eight)]) as s:
        boot(s, HASH)
        s.page.wait_for_selector("#pinBoard")
        s.page.locator("#pinBoard").click()
        assert s.page.inner_text("#stopLive") == "Board is full (8 pins)."
        assert s.page.locator("#pinBoard").inner_text() == "Pin to board" and len(js(s, "window.SEPTA.board.pins()")) == 8
        assert not s.console_errors, s.console_errors


def test_pin_button_flow(root):
    check_pin_button(root)
    must_fail(check_pin_button, root, ("js/stops.js", "if (live) live.textContent = r.msg;", ""))
