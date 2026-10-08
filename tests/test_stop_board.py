"""Task 2.1: stop board with honest, measured ETAs."""
import json
import math
import re

from harness import FIX, Session

STOPS = json.loads((FIX / "Stops.json").read_text())
SID, SROUTE = "14880", "21"
STOP = next(x for x in STOPS[SROUTE] if x["stopid"] == SID)
SLAT, SLNG = float(STOP["lat"]), float(STOP["lng"])
HASH = f"#stop={SID}&route={SROUTE}"
HOOK = "window.__SEPTA_TEST__ = true"
MLAT = 111195.0


def mlng(lat):
    return MLAT * math.cos(math.radians(lat))


def offset(bearing_deg, meters):
    """A point `meters` from the stop along compass bearing `bearing_deg`."""
    return (SLAT + meters * math.cos(math.radians(bearing_deg)) / MLAT,
            SLNG + meters * math.sin(math.radians(bearing_deg)) / mlng(SLAT))


def dist_m(lat, lng):
    return math.hypot((lat - SLAT) * MLAT, (lng - SLNG) * mlng(SLAT))


def bearing_to_stop(lat, lng):
    return math.degrees(math.atan2((SLNG - lng) * mlng(SLAT), (SLAT - lat) * MLAT)) % 360


def buses(s):
    return s.worker.data["TransitView"]["bus"]


def bus(s, vid):
    return next(b for b in buses(s) if str(b["VehicleID"]) == vid)


def place(b, lat, lng, heading=None):
    b["lat"], b["lng"] = f"{lat:.6f}", f"{lng:.6f}"
    if heading is not None:
        b["heading"] = heading


def bump_all(s, secs):
    for b in buses(s):
        b["timestamp"] = int(b["timestamp"]) + secs


def step(s, vid, toward_m):
    """Advance the feed by 15 s and move bus `vid` `toward_m` meters toward the stop along the straight line."""
    b = bus(s, vid)
    lat, lng = float(b["lat"]), float(b["lng"])
    d = dist_m(lat, lng)
    f = min(1.0, toward_m / d)
    place(b, lat + (SLAT - lat) * f, lng + (SLNG - lng) * f)
    bump_all(s, 15)
    s.tick(15000)


def setup_moving(s, start_m=1500, bearing=200):
    lat, lng = offset(bearing, start_m)
    place(bus(s, "3678"), lat, lng, bearing_to_stop(lat, lng))


def board(s):
    return s.page.text_content("#stopBoard")


def eta_of(s, key="b3678"):
    t = s.page.inner_text(f'#stopBoard button[data-key="{key}"] .sbeta')
    m = re.search(r"(\d+) min", t)
    return int(m.group(1)) if m else None


def open_board(s, hash_=HASH):
    s.open(hash_=hash_)
    s.wait_live()
    s.page.wait_for_selector("#stopBoard")
    s.settle()


def test_unit_speed_and_eta(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.worker.data["TransitView"] = {"bus": []}
        s.open()
        s.wait_live()
        out = s.page.evaluate("""([slat, slng]) => {
            const T = window.__SEPTA_TEST__, H = T.speedHist, r = {};
            const lat0 = 39.95, lng0 = -75.16, mlng = 111195 * Math.cos(lat0 * Math.PI / 180);
            const at = (t, mps) => ({ ts: 1000 + t, lat: lat0, lng: lng0 + mps * t / mlng });
            H.one = [at(0, 8)];
            r.one = T.speedMps('one');
            H.short = [at(0, 8), at(15, 8)];
            r.short = T.speedMps('short');
            H.three = [at(0, 8), at(15, 8), at(30, 8)];
            r.three = T.speedMps('three');
            H.still = [at(0, 0), at(15, 0), at(30, 0)];
            r.still = T.speedMps('still');
            H.slow = [at(0, 0.5), at(15, 0.5), at(30, 0.5)];
            r.slow = T.speedMps('slow');
            H.jump = [at(0, 0), { ts: 1020, lat: lat0, lng: lng0 + 500 / mlng }];
            r.jump = T.speedMps('jump');
            H.jump2 = [at(0, 0), at(15, 0), { ts: 1030, lat: lat0, lng: lng0 + 500 / mlng }];
            r.jump2 = T.speedMps('jump2');
            r.none = T.speedMps('nobody');
            // eta: bus 2000 m from the stop, measured 10 m/s
            const stop = { id: '14880', lat: slat, lng: slng };
            const v = { key: 'eta', nextId: '14880', lat: slat + 2000 / 111195, lng: slng };
            H.eta = [0, 15, 30].map(t => ({ ts: 1000 + t, lat: slat + (2000 + 10 * (30 - t)) / 111195, lng: slng }));
            r.speed = T.speedMps('eta');
            r.eta = T.etaFor(v, stop);
            r.other = T.etaFor(Object.assign({}, v, { nextId: '999' }), stop);
            r.nospeed = T.etaFor(Object.assign({}, v, { key: 'nobody' }), stop);
            r.notmoving = T.etaFor(Object.assign({}, v, { key: 'still' }), stop);
            return r;
        }""", [SLAT, SLNG])
        assert out["one"] is None and out["short"] is None and out["none"] is None
        assert abs(out["three"] - 8) / 8 < 0.1, out
        assert out["still"] == 0 and out["slow"] == 0
        assert out["jump"] is None and out["jump2"] is None
        assert abs(out["speed"] - 10) / 10 < 0.1
        # 2000 m * 1.15 / 10 m/s = 230 s -> 3.83 -> 4 min (the padding-sensitive case is the next test)
        assert out["eta"]["min"] == 4, out
        assert out["other"]["min"] is None and out["eta"]["rough"] is False
        assert out["nospeed"] == {"min": None, "note": "measuring speed", "rough": False}
        assert out["notmoving"] == {"min": None, "note": "not moving", "rough": False}


def test_unit_padding_changes_the_minute(root):
    """1000 m at 10 m/s: 100 s unpadded (2 min), 115 s padded (2 min); 1600 m: 160 s (3 min) vs 184 s (4 min)."""
    with Session(root, init_scripts=[HOOK]) as s:
        s.worker.data["TransitView"] = {"bus": []}
        s.open()
        s.wait_live()
        mins = s.page.evaluate("""([slat, slng]) => {
            const T = window.__SEPTA_TEST__;
            const stop = { id: '1', lat: slat, lng: slng };
            const v = { key: 'p', nextId: '1', lat: slat + 1600 / 111195, lng: slng };
            T.speedHist.p = [0, 15, 30].map(t => ({ ts: 1000 + t, lat: slat + (1600 + 10 * (30 - t)) / 111195, lng: slng }));
            return T.etaFor(v, stop).min }""", [SLAT, SLNG])
        assert mins == 4, mins


def test_board_measuring_then_numeric_and_decreasing(root):
    with Session(root) as s:
        setup_moving(s)
        open_board(s)
        assert "Arriving next" in board(s)
        row = s.page.locator('#stopBoard button[data-key="b3678"]')
        assert row.count() == 1
        txt = row.inner_text()
        assert "—" in txt and "measuring speed" in txt, txt
        assert "Estimates from distance and recent speed, not SEPTA predictions." in board(s)
        step(s, "3678", 120)
        assert eta_of(s) is None and "measuring speed" in row.inner_text()
        step(s, "3678", 120)  # 3 samples, 30 s span
        e = eta_of(s)
        assert e is not None, row.inner_text()
        d = dist_m(float(bus(s, "3678")["lat"]), float(bus(s, "3678")["lng"]))
        want = math.ceil(d * 1.15 / 8 / 60)
        assert abs(e - want) <= 1, (e, want)
        seen = [e]
        for _ in range(4):
            step(s, "3678", 120)
            seen.append(eta_of(s))
        assert all(x is not None for x in seen), seen
        assert seen[-1] < seen[0] and seen == sorted(seen, reverse=True), seen


def test_heading_toward_and_away_and_other_route(root):
    with Session(root) as s:
        # 3689 and 3050: not their next stop. One heads toward the stop, one away. 3678 stays the "next" bus.
        la, ln = offset(90, 800)
        place(bus(s, "3689"), la, ln, bearing_to_stop(la, ln) + 20)
        la, ln = offset(270, 800)
        place(bus(s, "3050"), la, ln, (bearing_to_stop(la, ln) + 180) % 360)
        # a far one (2 km, heading toward) must not be listed; an unknown-heading one must not be listed
        la, ln = offset(0, 3000)
        place(bus(s, "3391"), la, ln, bearing_to_stop(la, ln))
        la, ln = offset(180, 600)
        place(bus(s, "3393"), la, ln, None)
        bus(s, "3393")["heading"] = None
        # another route, right at the stop with the stop as its next stop, heading toward it
        other = next(b for b in buses(s) if b["route_id"] == "12" and b["VehicleID"])
        la, ln = offset(45, 150)
        place(other, la, ln, bearing_to_stop(la, ln))
        other["next_stop_id"] = SID
        open_board(s)
        keys = s.page.eval_on_selector_all("#stopBoard .sbrow", "e => e.map(x => x.dataset.key)")
        assert "b3689" in keys and "b3050" not in keys and "b3391" not in keys and "b3393" not in keys, keys
        assert f"b{other['VehicleID']}" not in keys
        assert keys.index("b3678") < keys.index("b3689"), "arriving-next rows come first"
        assert len(keys) <= 5
        heads = board(s)
        assert "Heading toward this stop" in heads
        r = s.page.locator('#stopBoard button[data-key="b3689"]')
        assert "—" in r.inner_text() and "measuring speed" in r.inner_text()
        assert re.search(r"0\.\d mi", r.inner_text()), r.inner_text()
        assert s.page.locator(f'#stopBoard .rbadge:text-is("12")').count() == 0


def test_click_row_selects_vehicle(root):
    with Session(root) as s:
        open_board(s)
        btn = s.page.locator('#stopBoard button[data-key="b3678"]')
        assert btn.evaluate("e => e.tagName") == "BUTTON"
        btn.focus()
        s.page.keyboard.press("Enter")
        s.page.wait_for_selector("#detail:not([hidden])")
        detail = s.page.text_content("#detail")
        assert "Route 21" in detail and "3678" in detail


def test_no_aria_live_on_rows(root):
    with Session(root) as s:
        open_board(s)
        assert s.page.evaluate("!document.querySelector('#stopBoard [aria-live], #stopBoard[aria-live]')")


def test_empty_state(root):
    with Session(root) as s:
        s.worker.data["TransitView"] = {"bus": []}
        open_board(s)
        assert "No buses on route 21 are heading to this stop right now." in board(s)
        assert "Live data unavailable" not in board(s)


def test_unavailable_after_drop_and_stale_note(root):
    with Session(root) as s:
        setup_moving(s)
        open_board(s)
        for _ in range(3):
            step(s, "3678", 120)
        assert eta_of(s) is not None
        s.worker.mode = "abort"
        s.tick(15000)
        s.tick(2000)  # the failed fetch retries once after 1.5 s
        assert "Positions may be out of date" in board(s)
        assert s.page.locator("#stopBoard .sbrow").count() >= 1
        for _ in range(9):
            s.tick(15000)
        assert "Live data unavailable. No arrival times are shown." in board(s)
        assert not re.search(r"\d+ min", board(s)), board(s)
        assert s.page.locator("#stopBoard .sbrow").count() == 0


def test_history_bounded_and_pruned(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_board(s)
        for _ in range(10):
            bump_all(s, 15)
            s.tick(15000)
        lens = s.page.evaluate("Object.values(window.__SEPTA_TEST__.speedHist).map(h => h.length)")
        assert lens and max(lens) <= 6 and max(lens) >= 5, lens
        total = s.page.evaluate("Object.keys(window.__SEPTA_TEST__.speedHist).length")
        assert total > 3, "history is kept for all buses, not only the visible ones"
        has = lambda: s.page.evaluate("'b3678' in window.__SEPTA_TEST__.speedHist")
        assert has()
        s.worker.data["TransitView"]["bus"] = [b for b in buses(s) if b["VehicleID"] != "3678"]
        bump_all(s, 15)
        s.tick(15000)
        assert not has()
        keys = s.page.evaluate("Object.keys(window.__SEPTA_TEST__.speedHist)")
        assert set(keys) <= {"b" + str(b["VehicleID"]) for b in buses(s)}


def test_mobile_board_visible_no_hscroll(root):
    with Session(root, viewport=(390, 844)) as s:
        setup_moving(s)
        open_board(s)
        assert s.page.locator("#stopBoard .sbrow").count() >= 1
        assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert s.page.evaluate("document.body.scrollWidth <= window.innerWidth")
        assert s.page.evaluate("document.querySelector('#stopCard').scrollWidth <= document.querySelector('#stopCard').clientWidth + 1")
        r = s.page.evaluate("(() => { const c = document.querySelector('#stopCard').getBoundingClientRect(), m = document.querySelector('#stage').getBoundingClientRect(); return [c.left, c.right, c.bottom, m.bottom] })()")
        assert r[0] >= 0 and r[1] <= 390 and r[2] <= r[3] + 1, r


def test_refresh_keeps_map_view(root):
    with Session(root) as s:
        setup_moving(s)
        open_board(s)
        state = lambda: s.page.evaluate("[document.querySelector('.leaflet-map-pane').style.transform, document.querySelector('#map').innerHTML.includes('leaflet-zoom-anim') ? 1 : 0, document.querySelector('.leaflet-tile-pane').style.transform]")
        before = state()
        step(s, "3678", 120)
        step(s, "3678", 120)
        assert state() == before
        assert not s.console_errors, s.console_errors


def test_no_new_storage_keys(root):
    with Session(root) as s:
        setup_moving(s)
        open_board(s)
        before = s.page.evaluate("Object.keys(localStorage).sort()")
        step(s, "3678", 120)
        assert s.page.evaluate("Object.keys(localStorage).sort()") == before


def test_rough_eta_for_heading_toward_bus(root):
    with Session(root) as s:
        # 3689 (next stop is some other stop) 1200 m out, heading straight at the stop; 3050 heads 50 degrees off
        la, ln = offset(90, 1200)
        place(bus(s, "3689"), la, ln, bearing_to_stop(la, ln))
        la, ln = offset(270, 1200)
        place(bus(s, "3050"), la, ln, (bearing_to_stop(la, ln) + 50) % 360)
        la, ln = offset(0, 1200)  # moving toward, but heading known; speed stays unknown because it never moves
        place(bus(s, "3391"), la, ln, bearing_to_stop(la, ln))
        open_board(s)
        r = s.page.locator('#stopBoard button[data-key="b3689"]')
        assert "~" not in r.inner_text() and "measuring speed" in r.inner_text()
        for _ in range(3):
            step(s, "3689", 120)
            step_others = None
        # 3050 and 3391 never move: 3050 is 50 deg off so plain note; 3391 is "not moving"
        e = s.page.locator('#stopBoard button[data-key="b3689"] .sbeta')
        txt = e.inner_text()
        assert "rough: not its next stop yet" in txt, txt
        m = re.search(r"~(\d+) min", txt)
        assert m, txt
        b = bus(s, "3689")
        want = math.ceil(dist_m(float(b["lat"]), float(b["lng"])) * 1.15 / 8 / 60)
        assert abs(int(m.group(1)) - want) <= 1, (m.group(1), want)
        assert s.page.locator('#stopBoard button[data-key="b3689"] .sbeta b.rough').count() == 1
        assert s.page.evaluate("getComputedStyle(document.querySelector('#stopBoard .sbeta b.rough')).fontStyle") == "italic"
        far = s.page.locator('#stopBoard button[data-key="b3050"]')
        if far.count():
            assert "~" not in far.inner_text() and "not its next stop yet" in far.inner_text()
        still = s.page.locator('#stopBoard button[data-key="b3391"]')
        assert still.count() == 1 and "not moving" in still.inner_text() and "~" not in still.inner_text()
        # the plain (a) estimate for 3678 is unchanged: no tilde
        assert "~" not in s.page.inner_text('#stopBoard button[data-key="b3678"] .sbeta')


def test_rough_eta_fifty_degrees_off_has_no_number(root):
    with Session(root) as s:
        la, ln = offset(90, 1200)
        place(bus(s, "3689"), la, ln, (bearing_to_stop(la, ln) + 50) % 360)
        open_board(s)
        for _ in range(3):
            step(s, "3689", 120)
        r = s.page.locator('#stopBoard button[data-key="b3689"]')
        assert r.count() == 1, "45-60 degree rows stay listed"
        assert "~" not in r.inner_text() and "\u2014" in r.inner_text() and "not its next stop yet" in r.inner_text()
