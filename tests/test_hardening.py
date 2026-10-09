"""Hardening pass: corrupt storage, ghost filter, honest banner, speed ceiling, subway/trolley kinds, request budget,
directions-link wording."""
import json

from harness import FIX, Session, app_source

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_bogus_future_record_does_not_empty_map",
    "test_chips_counts_markers_and_toggles",
    "test_corrupt_prefs_null",
    "test_dead_code_removed",
    "test_null_elements_do_not_throw",
    "test_places_validated_capped_and_truncated",
    "test_unit_kinds",
}

HOOK = "window.__SEPTA_TEST__ = true"
TV = json.loads((FIX / "TransitView.json").read_text())
HIDDEN = """(function () {
  window.__hidden = false;
  Object.defineProperty(document, 'hidden', { configurable: true, get: function () { return window.__hidden; } });
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: function () { return window.__hidden ? 'hidden' : 'visible'; } });
})();"""


def seed(key, raw):
    return f"try {{ localStorage.setItem({json.dumps(key)}, {json.dumps(raw)}); }} catch (e) {{}}"


def hits(s, name):
    return sum(1 for h in s.worker.hits if h == name)


def banner(s):
    return s.page.evaluate("document.querySelector('#banner').hidden ? '' : document.querySelector('#banner').textContent")


# ---------------------------------------------------------------- 1. corrupt storage

def boot_with(root, scripts):
    with Session(root, init_scripts=scripts) as s:
        s.open()
        s.wait_live()
        assert s.markers() > 0, "no markers after boot with corrupt storage"
        assert not s.console_errors, f"console errors: {s.console_errors}"
        return s.page.evaluate("[localStorage.getItem('septa.prefs.v1'), localStorage.getItem('septa.places.v1')]")


def test_corrupt_prefs_null(root):
    raw = boot_with(root, [seed("septa.prefs.v1", "null")])
    assert raw[0] == "null", "storage must not be rewritten on load"


def test_corrupt_prefs_partial_center(root):
    boot_with(root, [seed("septa.prefs.v1", '{"center":{"lat":40}}')])


def test_corrupt_prefs_junk_types(root):
    boot_with(root, [seed("septa.prefs.v1", '{"center":{"lat":null,"lng":null},"radius":"9","filters":{"bus":"no","train":false}}')])
    with Session(root, init_scripts=[seed("septa.prefs.v1", '{"radius":99,"filters":{"bus":"x","train":false}}')]) as s:
        s.open()
        s.wait_live()
        st = s.page.evaluate("({r: document.querySelector('#radius').value, bus: document.querySelector('[data-mode=bus]').checked, train: document.querySelector('[data-mode=train]').checked, subway: document.querySelector('[data-mode=subway]').checked})")
        assert st["bus"] is True and st["train"] is False and st["subway"] is False, st  # missing/invalid fields fall back to the new defaults
        assert float(st["r"]) == 0.5, st


def test_corrupt_places_home_without_coords(root):
    raw = boot_with(root, [seed("septa.places.v1", '{"home":{"name":"x"},"list":[]}')])
    assert raw[1] == '{"home":{"name":"x"},"list":[]}'


def test_corrupt_places_null_item(root):
    boot_with(root, [seed("septa.places.v1", '{"list":[null]}')])


def test_places_validated_capped_and_truncated(root):
    good = [{"id": f"p{i}", "name": "N" * 60, "lat": 39.95, "lng": -75.16} for i in range(60)]
    bad = [None, 5, "x", {"id": 1, "name": "a", "lat": 1, "lng": 1}, {"id": "q", "name": "a", "lat": "1", "lng": 1},
           {"id": "q", "name": "a", "lat": 1, "lng": None}, {"name": "a", "lat": 1, "lng": 1}]
    raw = json.dumps({"home": {"name": "H" * 60, "lat": 39.95, "lng": -75.17}, "list": bad + good})
    with Session(root, init_scripts=[seed("septa.places.v1", raw)]) as s:
        s.open()
        s.wait_live()
        n = s.page.evaluate("document.querySelectorAll('#places li').length")
        assert n == 51, f"expected home + 50 places, got {n}"
        names = s.page.evaluate("[...document.querySelectorAll('#places .nm')].map(e => e.textContent.length)")
        assert max(names) == 40, names
        assert not s.console_errors


# ---------------------------------------------------------------- 2. ghost filter

def test_bogus_future_record_does_not_empty_map(root):
    base = len(TV["bus"])
    ref = dict(TV["bus"][0])
    newest = max(int(b["timestamp"]) for b in TV["bus"])
    bogus = [dict(ref, VehicleID="None", label="None", timestamp=newest + 36000),
             dict(ref, VehicleID="", label="", timestamp=newest + 36000),
             dict(ref, VehicleID="ZZ1", label="ZZ1", lat="0", lng="0", timestamp=newest + 36000),
             dict(ref, VehicleID="ZZ2", label="ZZ2", late=998, timestamp=newest + 36000)]
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        r = s.page.evaluate("""([tv, extra]) => { const T = window.__SEPTA_TEST__;
            return [T.normBuses(tv).length, T.normBuses({bus: tv.bus.concat(extra)}).length]; }""", [TV, bogus])
        assert r[0] > 20 and r[0] == r[1], f"bogus future records changed the kept count: {r}"


def test_null_elements_do_not_throw(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        r = s.page.evaluate("""([tv]) => { const T = window.__SEPTA_TEST__;
            const a = T.normBuses({bus: [null, 5, 'x'].concat(tv.bus)}).length;
            const t = T.normTrains([null, 7, {lat: '40', lon: '-75', trainno: '1'}]).length;
            return [a, T.normBuses(tv).length, t]; }""", [TV])
        assert r[0] == r[1] and r[2] == 1, r


# ---------------------------------------------------------------- 3. banner honesty

def test_banner_reflects_each_sources_state(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        del s.worker.data["TransitView"]  # bus source fails (502), rail stays healthy
        s.tick(15000)
        s.tick(2000)
        b = banner(s)
        assert "last known positions" in b and "unavailable" not in b, f"stale-but-shown wording wrong: {b!r}"
        for _ in range(9):
            s.tick(15000)
        b = banner(s)
        assert "Bus and trolley positions are unavailable" in b, b
        assert "last known positions" not in b, b
        assert s.markers() > 0, "rail markers should still be drawn"


def test_dead_code_removed(root):
    src = app_source(root)
    assert "okAny&&false" not in src and "var API=" not in src


def s_root(root):
    import pathlib
    return pathlib.Path(root)


# ---------------------------------------------------------------- 4. speed ceiling

def test_highway_speed_gets_a_speed_but_gps_jump_is_rejected(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        r = s.page.evaluate("""() => { const T = window.__SEPTA_TEST__, H = T.speedHist;
            const lat0 = 39.95, lng0 = -75.16, mlng = 111195 * Math.cos(lat0 * Math.PI / 180);
            const at = (t, mps) => ({ ts: 1000 + t, lat: lat0, lng: lng0 + mps * t / mlng });
            H.fast = [at(0, 24), at(15, 24), at(30, 24)];
            H.jump = [at(0, 0), { ts: 1030, lat: lat0, lng: lng0 + 1000 / mlng }];
            H.toofast = [at(0, 40), at(15, 40), at(30, 40)];
            return { fast: T.speedMps('fast'), jump: T.speedMps('jump'), toofast: T.speedMps('toofast') }; }""")
        assert abs(r["fast"] - 24) < 1.5, r
        assert r["jump"] is None and r["toofast"] is None, r


# ---------------------------------------------------------------- 5. subway / trolley classification

def test_unit_kinds(root):
    # most B1/B3/L1 records in the fixture are schedule-only ghosts (VehicleID "None"), so live ones are synthesized
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        k = s.page.evaluate("""(tv) => { const T = window.__SEPTA_TEST__, m = {};
            T.normBuses(tv).forEach(v => { m[v.route] = v.kind; }); return m; }""", TV)
        assert k["B2"] == "subway" and k["T1"] == "trolley" and k["G1"] == "trolley" and k["21"] == "bus" and k["LUCYGO"] == "bus", k
        routes = ["B1", "B3", "L1", "M1", "T2", "T3", "T4", "T5", "D1", "D2", "10", "101", "102", "11", "13", "15", "34", "36",
                  "LUCYGO", "LUCYGR", "42"]
        out = s.page.evaluate("""([ref, routes]) => { const T = window.__SEPTA_TEST__;
            const mk = (r, i) => Object.assign({}, ref, {route_id: r, VehicleID: 'K' + i, label: 'K' + i});
            const m = {}; T.normBuses({bus: routes.map(mk)}).forEach(v => { m[v.route] = v.kind; }); return m; }""", [TV["bus"][0], routes])
        want = {r: "subway" for r in ("B1", "B3", "L1", "M1")}
        want.update({r: "trolley" for r in ("T2", "T3", "T4", "T5", "D1", "D2", "10", "101", "102", "11", "13", "15", "34", "36")})
        want.update({r: "bus" for r in ("LUCYGO", "LUCYGR", "42")})
        assert out == want, out


def center_on_fixture(s):
    pass


def test_chips_counts_markers_and_toggles(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        counts = s.page.evaluate("Object.fromEntries([...document.querySelectorAll('[data-n]')].map(n => [n.dataset.n, n.textContent]))")
        assert int(counts["trolley"]) > 0 and int(counts["subway"]) > 0, counts
        labels = s.page.evaluate("[...document.querySelectorAll('#modes .chip')].map(c => c.textContent.replace(/[0-9]+/, '').trim())")
        assert "Subway" in labels, labels
        n = lambda k: s.page.evaluate(f"document.querySelectorAll('.veh-wrap.k-{k}').length")
        assert n("subway") == int(counts["subway"]) and n("trolley") == int(counts["trolley"]) and n("bus") > 0
        s.page.click(".chip.k-subway")
        assert n("subway") == 0 and n("trolley") > 0
        assert s.page.evaluate("JSON.parse(localStorage.getItem('septa.prefs.v1')).filters.subway") is False
        s.page.click(".chip.k-subway")
        assert n("subway") == int(counts["subway"])
        s.page.click(".chip.k-trolley")
        assert n("trolley") == 0 and n("subway") > 0
        s.page.click(".chip.k-trolley")
        assert n("trolley") == int(counts["trolley"])
        # subway markers use the train drawing but their own color token
        col = s.page.evaluate("""() => { const cs = e => getComputedStyle(e).getPropertyValue('--c').trim();
            const sub = document.querySelector('.veh-wrap.k-subway'), tr = document.querySelector('.veh-wrap.k-trolley');
            return {sub: cs(sub), tr: cs(tr), drawn: !!sub.querySelector('.ln'), tok: getComputedStyle(document.documentElement).getPropertyValue('--subway').trim()}; }""")
        assert col["drawn"] and col["tok"] and col["sub"] and col["sub"] != col["tr"], col


def test_subway_detail_card_has_no_stop_features(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        s.page.locator(".veh-wrap.k-trolley").first.dispatch_event("click")
        s.page.wait_for_selector("#detail:not([hidden])")
        assert "Trolley" in s.page.inner_text("#detail")
        s.page.locator(".veh-wrap.k-subway").first.dispatch_event("click")
        s.page.wait_for_selector("#detail:not([hidden])")
        txt = s.page.inner_text("#detail")
        assert "Subway" in txt, txt
        assert s.page.locator("#viewStop").count() == 0, "subway card must not offer View stop"
        s.page.click("#starBtn")
        stars = s.page.evaluate("JSON.parse(localStorage.getItem('septa.routes.v1')).stars")
        assert len(stars) == 1 and stars[0].startswith("subway:"), stars


def test_old_saved_prefs_without_subway_still_load(root):
    with Session(root, init_scripts=[seed("septa.prefs.v1", '{"radius":1.5,"filters":{"bus":true,"trolley":false,"train":true}}')]) as s:
        s.open()
        s.wait_live()
        st = s.page.evaluate("Object.fromEntries([...document.querySelectorAll('[data-mode]')].map(i => [i.dataset.mode, i.checked]))")
        assert st == {"bus": True, "trolley": False, "subway": False, "train": True}, st  # a missing key takes the new default (off)


# ---------------------------------------------------------------- 6. request budget

def test_rail_chip_off_stops_trainview_and_resumes(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        assert int(s.page.inner_text("[data-n=train]") or 0) > 0
        s.page.click(".chip.k-train")
        s.tick(15000)  # one tick to settle
        before = hits(s, "TrainView")
        for _ in range(4):
            s.tick(15000)
        assert hits(s, "TrainView") == before, "TrainView still requested while the chip is off"
        assert hits(s, "TransitView") >= 5
        assert s.page.inner_text("[data-n=train]") == "", "stale train count shown for a skipped source"
        assert s.page.evaluate("document.querySelectorAll('.veh-wrap.k-train').length") == 0
        s.page.click(".chip.k-train")
        s.page.wait_for_timeout(600)
        assert hits(s, "TrainView") > before, "no immediate refetch when the chip was turned back on"
        assert int(s.page.inner_text("[data-n=train]") or 0) > 0
        mid = hits(s, "TrainView")
        s.tick(15000)
        assert hits(s, "TrainView") > mid, "requests did not resume on the normal cadence"


def test_all_vehicle_chips_off_skips_transitview_unless_stop_open(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        for k in ("bus", "trolley", "subway"):
            s.page.click(f".chip.k-{k}")
        s.tick(15000)
        before = hits(s, "TransitView")
        for _ in range(3):
            s.tick(15000)
        assert hits(s, "TransitView") == before, "TransitView requested with every bus-feed chip off"
        assert s.page.inner_text("[data-n=bus]") == ""
        s.page.click(".chip.k-bus")
        s.page.wait_for_timeout(600)
        assert hits(s, "TransitView") > before, "no immediate refetch when a bus-feed chip came back"
    # an open stop keeps the feed alive even with the chips off
    with Session(root) as s:
        s.open(hash_="#stop=14880&route=21")
        s.wait_live()
        s.page.wait_for_selector("#stopCard:not([hidden])")
        for k in ("bus", "trolley", "subway"):
            s.page.click(f".chip.k-{k}")
        s.tick(15000)
        before = hits(s, "TransitView")
        s.tick(15000)
        s.tick(15000)
        assert hits(s, "TransitView") >= before + 2


RULE = json.dumps({"rules": [{"id": "r1", "route": "21", "stopId": "14880", "stopName": "Stop", "lat": 39.95, "lng": -75.17,
                              "minutes": 5, "enabled": True, "last": None}]})


def test_hidden_tab_cadence_with_rule(root):
    with Session(root, init_scripts=[HIDDEN, seed("septa.rules.v1", RULE)]) as s:
        s.open()
        s.wait_live()
        s.page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
        t0 = hits(s, "TransitView")
        for _ in range(4):
            s.tick(15000)
        assert hits(s, "TransitView") - t0 == 1, f"hidden tab with a rule: {hits(s, 'TransitView') - t0} requests in 60 s"
        for _ in range(4):
            s.tick(15000)
        assert hits(s, "TransitView") - t0 == 2
        s.page.evaluate("window.__hidden = false; document.dispatchEvent(new Event('visibilitychange'))")
        t1 = hits(s, "TransitView")
        for _ in range(4):
            s.tick(15000)
        assert hits(s, "TransitView") - t1 >= 4, "visible tab must refresh every 15 s"


def test_hidden_tab_without_rule_makes_no_requests(root):
    with Session(root, init_scripts=[HIDDEN]) as s:
        s.open()
        s.wait_live()
        s.page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
        t0 = len(s.worker.hits)
        for _ in range(4):
            s.tick(15000)
        assert len(s.worker.hits) == t0


def test_failure_backoff_spacing_and_reset(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        saved = s.worker.data.pop("TransitView")
        attempts, train, retry_due = [], 0, 0
        for i in range(1, 25):  # 15 s ticks, 360 s
            h0, r0 = hits(s, "TransitView"), hits(s, "TrainView")
            s.tick(15000)
            new = hits(s, "TransitView") - h0
            # the single in-call retry fires 1.5 s after its attempt, i.e. inside the next tick window
            if new - retry_due > 0:
                attempts.append(i * 15)
            retry_due = 1 if new - retry_due > 0 else 0
            train += hits(s, "TrainView") - r0
        gaps = [b - a for a, b in zip(attempts, attempts[1:])]
        assert attempts[:2] == [15, 45] and gaps[:3] == [30, 60, 120], f"attempts {attempts}"
        assert all(g == 120 for g in gaps[3:]), gaps
        assert 23 <= train <= 25, "the healthy source must not be slowed down by the failing one"
        s.worker.data["TransitView"] = saved
        for _ in range(9):  # next scheduled attempt arrives within 120 s
            s.tick(15000)
        h0 = hits(s, "TransitView")
        for _ in range(3):
            s.tick(15000)
        assert 3 <= hits(s, "TransitView") - h0 <= 4, "cadence did not reset after a successful refresh"


# ---------------------------------------------------------------- 7. directions wording

def test_directions_link_has_privacy_note(root):
    with Session(root, geolocation={"latitude": 39.95, "longitude": -75.17}) as s:
        s.open()
        s.wait_live()
        s.page.evaluate("""() => { localStorage.setItem('septa.places.v1', JSON.stringify({home: {name: 'Home', lat: 39.93, lng: -75.19}, list: []})); }""")
        s.page.reload()
        s.wait_live()
        s.page.click("#btnHome")
        s.page.wait_for_selector("#gmh a")
        txt = s.page.inner_text("#gmh header")
        assert "Open transit directions" in txt and "Opens Google Maps with your start and Home locations." in txt, txt
        assert s.page.get_attribute("#gmh a", "href").startswith("https://www.google.com/maps/dir/")
