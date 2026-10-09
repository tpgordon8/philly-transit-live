"""WP-B: the vehicle badge and icon follow the ROUTE's direction (ARCHITECTURE.md 15.1), not the bus's momentary heading."""
import json
import os
import pathlib

from harness import FIX, Session

FAST = {
    "test_northbound_bus_with_east_heading_shows_N_and_vertical_icon",
    "test_eastbound_bus_with_north_heading_shows_E_and_horizontal_icon",
    "test_vehsig_ignores_heading_jitter_and_tracks_direction",
    "test_accessible_names_use_route_direction",
}
HOOK = ["window.__SEPTA_TEST__ = true"]
TV = json.loads((FIX / "TransitView.json").read_text())
TR = json.loads((FIX / "TrainView.json").read_text())
CENTER = (39.9526, -75.1652)
TS = max(int(b["timestamp"]) for b in TV["bus"])
ANGLE = {"N": 0, "E": 90, "S": 180, "W": 270}
DIRWORD = {"N": "Northbound", "E": "Eastbound", "S": "Southbound", "W": "Westbound"}

MEASURE = """const measure = (w) => { const vb = w.querySelector('.vb'), m = new DOMMatrix(getComputedStyle(vb).transform),
    bd = w.querySelector('.bd').getBoundingClientRect(), rt = w.querySelector('.rt'), dr = w.querySelector('.dr');
    const rr = rt.getBoundingClientRect(), dd = dr.getBoundingClientRect(), mr = new DOMMatrix(getComputedStyle(rt).transform);
    return {angle: (Math.round(Math.atan2(m.b, m.a) * 180 / Math.PI) + 360) % 360, bw: bd.width, bh: bd.height,
            dr: dr.textContent.trim(), none: dr.classList.contains('none'), rt: rt.textContent.trim(),
            rtAngle: Math.round(Math.atan2(mr.b, mr.a) * 180 / Math.PI), drTransform: getComputedStyle(dr).transform,
            overlap: !(rr.right <= dd.left || dd.right <= rr.left || rr.bottom <= dd.top || dd.bottom <= rr.top),
            label: w.getAttribute('aria-label'), sig: w.dataset.sig}; };"""
ONE_JS = "(sel) => {" + MEASURE + " return measure(document.querySelector(sel)); }"
ALL_JS = "() => {" + MEASURE + " return [...document.querySelectorAll('.veh-wrap')].map(measure); }"


def bus(n, route, direction, heading, late=2, dlat=0.0, dlng=0.0):
    return {"lat": f"{CENTER[0] + dlat:.6f}", "lng": f"{CENTER[1] + dlng:.6f}", "label": str(9000 + n), "route_id": route,
            "trip": str(100 + n), "VehicleID": str(9000 + n), "BlockID": "1", "Direction": direction,
            "destination": "Somewhere", "heading": heading, "late": late, "next_stop_id": "14884", "next_stop_name": "Walnut St & 10th St",
            "next_stop_sequence": 3, "estimated_seat_availability": "EMPTY", "Offset": 0, "Offset_sec": "0", "timestamp": TS}


def train(n, heading, dlat=0.0, dlng=0.0):
    t = dict(TR[0])
    t.update(lat=f"{CENTER[0] + dlat:.6f}", lon=f"{CENTER[1] + dlng:.6f}", trainno=str(7000 + n), heading=str(heading))
    return t


def grid(i):
    """Marker i sits on a 0.004 degree grid around the centre, far enough apart to never overlap on screen."""
    return {"dlat": 0.004 * (i // 4 - 1), "dlng": 0.005 * (i % 4 - 1.5)}


def open_with(s, buses, trains=()):
    s.worker.data["TransitView"] = {"bus": buses}
    s.worker.data["TrainView"] = list(trains)
    s.open()
    s.wait_live()
    s.page.wait_for_timeout(300)


def info(s, sel):
    return s.page.evaluate(ONE_JS, sel)


def pick(s, route):
    """Mark the one marker whose route pill reads `route` with class .pick and return its measurements."""
    s.page.evaluate("(r) => document.querySelectorAll('.veh-wrap').forEach(w => w.classList.toggle('pick', w.querySelector('.rt').textContent.trim() === r))", route)
    return info(s, ".veh-wrap.pick")


def test_northbound_bus_with_east_heading_shows_N_and_vertical_icon(root):
    with Session(root) as s:
        open_with(s, [bus(1, "57", "Northbound", 90)])
        r = info(s, ".veh-wrap")
        assert r["dr"] == "N" and not r["none"], r
        assert r["angle"] == 0, r  # facing north, not rotated to the 90 degree heading
        assert r["bh"] > r["bw"] * 1.5, f"north-facing bus icon should be tall and narrow: {r}"


def test_eastbound_bus_with_north_heading_shows_E_and_horizontal_icon(root):
    with Session(root) as s:
        open_with(s, [bus(1, "21", "Eastbound", 0)])
        r = info(s, ".veh-wrap")
        assert r["dr"] == "E" and not r["none"], r
        assert r["angle"] == 90, r
        assert r["bw"] > r["bh"] * 1.5, f"east-facing bus icon should be wide and short: {r}"


def test_all_four_route_directions_map_to_letter_and_rotation(root):
    with Session(root) as s:
        buses = [bus(i, str(10 + i), DIRWORD[d], 123 + 40 * i, **grid(i)) for i, d in enumerate("NESW")]
        open_with(s, buses)
        for i, d in enumerate("NESW"):
            r = pick(s, str(10 + i))
            assert r["dr"] == d and r["angle"] == ANGLE[d], (d, r)
            vertical = d in "NS"
            assert (r["bh"] > r["bw"]) == vertical, (d, r)


def test_loop_and_missing_direction_fall_back_to_snapped_heading(root):
    cases = [("Loop", 100, "E"), ("Loop", 350, "N"), ("Loop", 200, "S"), ("", 268, "W"), ("Loop", 44, "N"), ("Loop", 46, "E"), ("Loop", None, "N")]
    with Session(root) as s:
        buses = [bus(i, str(20 + i), d, h, **grid(i)) for i, (d, h, _) in enumerate(cases)]
        open_with(s, buses)
        for i, (d, h, face) in enumerate(cases):
            r = pick(s, str(20 + i))
            assert r["angle"] == ANGLE[face], (d, h, face, r)
            assert r["none"] and r["dr"] == "?", f"loop/unknown shows no direction letter: {r}"
            assert not any(w in r["label"].lower() for w in ("northbound", "southbound", "eastbound", "westbound", "heading")), r["label"]


def test_trains_keep_heading_based_letter_and_wording(root):
    with Session(root) as s:
        open_with(s, [], [train(1, 45, **grid(0)), train(2, 200, **grid(1)), train(3, 268, **grid(2))])
        res = s.page.evaluate("""() => [...document.querySelectorAll('.veh-wrap.k-train')].map(w => [w.querySelector('.dr').textContent.trim(), w.getAttribute('aria-label'),
            new DOMMatrix(getComputedStyle(w.querySelector('.vb')).transform).b])""")
        assert len(res) == 3
        letters = sorted(r[0] for r in res)
        assert letters == sorted(["NE", "S", "W"]), res  # the 8-point heading letter, as before
        for letter, label, _ in res:
            assert f" heading {letter}," in label and "bound" not in label, label
        # the train drawing faces the heading snapped to N/E/S/W: 45 -> E (90), 200 -> S (180), 268 -> W (270)
        angles = s.page.evaluate("""() => [...document.querySelectorAll('.veh-wrap.k-train')].map(w => { const m = new DOMMatrix(getComputedStyle(w.querySelector('.vb')).transform);
            return [w.querySelector('.dr').textContent.trim(), (Math.round(Math.atan2(m.b, m.a) * 180 / Math.PI) + 360) % 360]; })""")
        assert dict(angles) == {"NE": 90, "S": 180, "W": 270}, angles
        s.page.locator(".veh-wrap.k-train").first.dispatch_event("click")
        txt = s.page.inner_text("#detail")
        assert "no route direction" in txt and "Heading" in txt, txt


def test_vehsig_ignores_heading_jitter_and_tracks_direction(root):
    with Session(root, init_scripts=HOOK) as s:
        s.open()
        r = s.page.evaluate("""() => { const T = window.__SEPTA_TEST__, base = {kind: 'bus', badge: '57', route: '57', dir: 'N', direction: 'Northbound', heading: 0, late: 1};
            const sigs = new Set(); for (let h = 0; h < 360; h += 7) sigs.add(T.vehSig(Object.assign({}, base, {heading: h})));
            sigs.add(T.vehSig(Object.assign({}, base, {heading: null})));
            const other = T.vehSig(Object.assign({}, base, {dir: 'E', direction: 'Eastbound'}));
            const loop = new Set(); for (const h of [10, 40, 50, 100]) loop.add(T.vehSig(Object.assign({}, base, {dir: '', direction: 'Loop', heading: h})));
            const train = new Set(); for (const h of [1, 20, 40, 100]) train.add(T.vehSig({kind: 'train', badge: '221', dir: '', heading: h}));
            return {jitter: sigs.size, northSig: [...sigs][0], eastSig: other, loop: loop.size, train: train.size}; }""")
        assert r["jitter"] == 1, r  # a detour or GPS jitter never changes the signature of a bus on a Northbound route
        assert r["northSig"] != r["eastSig"], r  # a route direction change does
        assert r["loop"] == 2, r  # loop: signature follows the snapped facing (N for 10 and 40, E for 50 and 100)
        assert r["train"] >= 2, r


def test_markers_not_rebuilt_on_jitter_but_update_on_direction_change(root):
    with Session(root) as s:
        b = bus(1, "57", "Northbound", 0)
        open_with(s, [b])
        s.page.evaluate("() => { const w = document.querySelector('.veh-wrap'); window.__svg = w.querySelector('.vb'); window.__sig = w.dataset.sig; }")
        b["heading"] = 91  # a detour: still Northbound
        s.tick(15000)
        same = s.page.evaluate("() => { const w = document.querySelector('.veh-wrap'); return w.querySelector('.vb') === window.__svg && w.dataset.sig === window.__sig; }")
        assert same, "the marker DOM was rebuilt for a heading change on an unchanged route direction"
        b["Direction"] = "Southbound"  # the bus finished its trip and now runs the other way
        s.tick(15000)
        r = info(s, ".veh-wrap")
        assert r["dr"] == "S" and r["angle"] == 180 and "southbound" in r["label"], r
        assert s.page.evaluate("document.querySelector('.veh-wrap .vb') !== window.__svg"), "marker did not update when direction changed"


def test_accessible_names_use_route_direction(root):
    with Session(root) as s:
        buses = [bus(1, "57", "Northbound", 90, late=2, **grid(0)), bus(2, "12", "Westbound", 10, late=0, **grid(1)),
                 bus(3, "G1", "Southbound", 10, late=5, **grid(2)), bus(4, "B1", "Eastbound", 10, late=0, **grid(3)),
                 bus(5, "33", "Loop", 90, late=1, **grid(4)), bus(6, "42", "", 90, late=1, **grid(5))]
        open_with(s, buses, [train(1, 45, **grid(6))])
        labels = s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].map(w => w.getAttribute('aria-label'))")
        assert "Route 57 bus, N, northbound, 2 min late" in labels, labels
        assert any(l.startswith("Route 12 bus, W, westbound, ") for l in labels), labels
        assert any(l.startswith("Route G1 trolley, S, southbound, ") for l in labels), labels
        assert any(l.startswith("Route B1 subway, E, eastbound, ") for l in labels), labels
        assert "Route 33 bus, 1 min late" in labels and "Route 42 bus, 1 min late" in labels, labels
        assert not any("heading" in l for l in labels if l.startswith("Route")), labels
        assert any(l.startswith("Regional Rail train 7001") and " heading NE, " in l for l in labels), labels


def test_vehicle_card_shows_route_direction_first_and_heading_as_detail(root):
    with Session(root) as s:
        buses = [bus(1, "57", "Northbound", 92, **grid(0)), bus(2, "21", "Eastbound", 88, **grid(1)),
                 bus(3, "33", "Loop", 270, **grid(2)), bus(4, "42", "", None, **grid(3))]
        open_with(s, buses)

        def card(route):
            s.page.evaluate("(r) => { document.querySelectorAll('.veh-wrap').forEach(w => { if (w.querySelector('.rt').textContent.trim() === r) w.click(); }); }", route)
            s.page.wait_for_selector("#detail:not([hidden])")
            return s.page.evaluate("""() => { const dt = [...document.querySelectorAll('#detail dt')].find(d => d.textContent === 'Direction');
                const dd = dt.nextElementSibling; const sub = dd.querySelector('.dsub'); return {main: dd.firstChild.firstChild.textContent, sub: sub ? sub.textContent : null}; }""")
        assert card("57") == {"main": "Northbound", "sub": "Currently driving E (92°)"}
        assert card("21") == {"main": "Eastbound", "sub": None}  # heading 88 agrees with the route: nothing extra
        assert card("33") == {"main": "Loop", "sub": "Currently driving W (270°)"}
        assert card("42") == {"main": "Direction not reported", "sub": "Heading unavailable"}


def test_badge_never_overlaps_route_number_and_stays_upright(root):
    with Session(root) as s:
        routes = ["1", "57", "G1", "L1", "BSL", "9999", "LUCY"]
        buses = [bus(i, r, DIRWORD[("N", "E", "S", "W")[i % 4]], 0, **grid(i)) for i, r in enumerate(routes)]
        open_with(s, buses, [train(1, 90, **grid(7)), train(2, 0, **grid(8)), train(3, 180, **grid(9)), train(4, 270, **grid(10))])
        res = s.page.evaluate(ALL_JS)
        assert len(res) == len(routes) + 4
        for r in res:
            assert not r["overlap"], r
            assert r["rtAngle"] == 0 and r["drTransform"] == "none", r  # only the drawing rotates
        assert {r["angle"] for r in res} == {0, 90, 180, 270}, "all four facings should be exercised"


def test_fixture_buses_badge_matches_feed_direction(root):
    with Session(root, init_scripts=HOOK) as s:
        s.open()
        s.wait_live()
        r = s.page.evaluate("""([tv]) => { const T = window.__SEPTA_TEST__, c = {lat: 39.9526, lng: -75.1652};
            const want = {N: 0, E: 0, S: 0, W: 0, none: 0};
            const byKey = new Map(); T.normBuses(tv).forEach(v => { if (T.distMi(c, v) <= 1.5) byKey.set(v.key, v); });
            byKey.forEach(v => want[v.dir || 'none']++);
            const got = {N: 0, E: 0, S: 0, W: 0, none: 0};
            document.querySelectorAll('.veh-wrap.k-bus, .veh-wrap.k-trolley, .veh-wrap.k-subway').forEach(w => { const d = w.querySelector('.dr'); got[d.classList.contains('none') ? 'none' : d.textContent.trim()]++; });
            return {want, got}; }""", [TV])
        assert r["want"] == r["got"] and r["want"]["N"] > 0 and r["want"]["W"] > 0, r


def test_keyboard_and_marker_semantics_unchanged(root):
    with Session(root) as s:
        open_with(s, [bus(1, "57", "Northbound", 90)])
        w = s.page.locator(".veh-wrap").first
        assert w.get_attribute("role") == "button" and w.get_attribute("tabindex") == "0"
        w.focus()
        s.page.keyboard.press("Enter")
        assert s.page.evaluate("document.querySelector('.veh-wrap').classList.contains('sel')")
        assert "Northbound" in s.page.inner_text("#detail")
        assert "northbound" in s.page.inner_text("#detailLive")


def test_light_dark_and_selected_render(root):
    for scheme in ("light", "dark"):
        with Session(root, viewport=(900, 640)) as s:
            s.page.emulate_media(color_scheme=scheme)
            kinds = [("57", "Northbound"), ("21", "Eastbound"), ("33", "Southbound"), ("12", "Westbound"), ("T5", "Northbound"), ("B1", "Eastbound"), ("G1", "Loop"), ("44", "")]
            buses = [bus(i, r, d, 135, **grid(i)) for i, (r, d) in enumerate(kinds)]
            open_with(s, buses, [train(1, 0, **grid(8)), train(2, 180, **grid(9)), train(3, 90, **grid(10)), train(4, 300, **grid(11))])
            for _ in range(3):
                s.page.click(".leaflet-control-zoom-in")
                s.page.wait_for_timeout(250)
            s.settle()
            s.page.evaluate("document.querySelector('.veh-wrap.k-bus').classList.add('stale')")
            s.shot(f"direction_{scheme}")
            s.page.locator(".veh-wrap.k-subway").first.dispatch_event("click")
            s.page.wait_for_timeout(200)
            s.shot(f"direction_{scheme}_selected")
            fill = s.page.evaluate("getComputedStyle(document.querySelector('.veh-wrap.k-bus .bd')).fill")
            assert fill not in ("", "none", "rgb(0, 0, 0)"), fill
            assert s.page.evaluate("document.querySelector('.veh-wrap.sel .vb') && getComputedStyle(document.querySelector('.veh-wrap.sel .vb')).filter.includes('drop-shadow')")
            assert s.page.evaluate("document.querySelectorAll('.veh-wrap.stale').length") == 1
            assert not s.console_errors, s.console_errors


SHEET_JS = """([kinds, faces, theme]) => {
  const T = window.__SEPTA_TEST__, host = document.createElement('div');
  host.id = 'sheet'; host.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:' + (theme === 'dark' ? '#1b2430' : '#e9edf1') + ';padding:16px;display:grid;grid-template-columns:90px repeat(4, 110px);gap:12px;font:12px sans-serif;color:' + (theme === 'dark' ? '#fff' : '#111');
  host.appendChild(document.createElement('div'));
  faces.forEach(f => { const h = document.createElement('div'); h.textContent = 'facing ' + f; host.appendChild(h); });
  kinds.forEach(k => {
    const l = document.createElement('div'); l.textContent = k; host.appendChild(l);
    faces.forEach(f => { const cell = document.createElement('div'); cell.style.cssText = 'position:relative;height:70px';
      const w = document.createElement('div'); w.className = 'veh-wrap k-' + k; w.style.cssText = 'position:absolute;left:30px;top:14px;transition:none';
      const dir = {N: 'Northbound', E: 'Eastbound', S: 'Southbound', W: 'Westbound'}[f];
      w.innerHTML = T.vehInner({kind: k, badge: k === 'train' ? '9234' : k === 'subway' ? 'L1' : k === 'trolley' ? 'T5' : '57', dir: f, heading: 0, direction: dir});
      if (k === 'train') w.querySelector('.dr').textContent = f;
      cell.appendChild(w); host.appendChild(cell); }); });
  document.body.appendChild(host);
}"""


def test_contact_sheet_all_kinds_all_facings(root):
    out = pathlib.Path(os.environ.get("SEPTA_TEST_OUT") or pathlib.Path(__file__).resolve().parent / "out")
    out.mkdir(parents=True, exist_ok=True)
    for scheme in ("light", "dark"):
        with Session(root, viewport=(640, 420), init_scripts=HOOK) as s:
            s.page.emulate_media(color_scheme=scheme)
            s.open()
            s.wait_live()
            s.page.evaluate(SHEET_JS, [["bus", "trolley", "subway", "train"], ["N", "E", "S", "W"], scheme])
            s.page.locator("#sheet").screenshot(path=str(out / f"direction_contact_{scheme}.png"))
            assert s.page.evaluate("document.querySelectorAll('#sheet .vb').length") == 16
            # the same sheet at 2x device pixels (retina): the drawing is vector, so it stays crisp
            ctx = s.browser.new_context(viewport={"width": 640, "height": 420}, device_scale_factor=2, color_scheme=scheme)
            page = ctx.new_page()
            page.route("**/*", s._route)
            for js in s.init_scripts:
                page.add_init_script(js)
            page.goto(f"{s.base}/index.html")
            page.wait_for_function("document.querySelector('#statusText') && /Live/.test(document.querySelector('#statusText').textContent)")
            page.evaluate(SHEET_JS, [["bus", "trolley", "subway", "train"], ["N", "E", "S", "W"], scheme])
            page.locator("#sheet").screenshot(path=str(out / f"direction_contact_{scheme}_retina.png"))
            ctx.close()
