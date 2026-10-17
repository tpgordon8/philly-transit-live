"""Map level of detail (js/maplod.js, ARCHITECTURE.md 4.1): compact markers zoomed out, labels that never overlap, count badges for piles,
full markers from zoom 16, and the vehicles a rider cares about kept prominent. Hermetic, like the other browser tests."""
import json
import math
import time

from harness import FIX, Session
from test_first_run import must_fail

FAST = {
    "test_zoomed_out_folds_piles_into_badges_and_labels_never_overlap",
    "test_cared_for_vehicles_stay_prominent_and_the_rest_dim",
}

TV = json.loads((FIX / "TransitView.json").read_text())
TS = max(int(b["timestamp"]) for b in TV["bus"])
CENTER = (39.9526, -75.1652)

# What each marker looks like right now: label shown, folded, prominent, dimmed, tab order, label box.
STATE_JS = """() => [...document.querySelectorAll('.veh-wrap')].map(e => { const rt = e.querySelector('.rt'), r = rt.getBoundingClientRect();
    return {key: e.getAttribute('aria-label'), route: rt.textContent.trim(), inclu: e.classList.contains('inclu'), hot: e.classList.contains('hot'),
            dim: e.classList.contains('dim'), sel: e.classList.contains('sel'), tab: e.tabIndex, hidden: e.getAttribute('aria-hidden'),
            shown: getComputedStyle(rt).display !== 'none' && getComputedStyle(rt).visibility !== 'hidden',
            box: {l: r.left, t: r.top, r: r.right, b: r.bottom}}; })"""
BADGES_JS = """() => [...document.querySelectorAll('.veh-clu')].map(e => { const r = e.querySelector('.cn').getBoundingClientRect();
    return {n: parseInt(e.textContent, 10), label: e.getAttribute('aria-label'), role: e.getAttribute('role'), tab: e.tabIndex,
            box: {l: r.left, t: r.top, r: r.right, b: r.bottom}}; })"""


def overlap(a, b):
    return a["l"] < b["r"] - 0.5 and b["l"] < a["r"] - 0.5 and a["t"] < b["b"] - 0.5 and b["t"] < a["b"] - 0.5


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()
    s.page.wait_for_timeout(300)


def zoom(s, z):
    s.page.evaluate(f"window.SEPTA.map.map.setZoom({z}, {{animate: false}})")
    s.page.wait_for_timeout(150)


def stars(routes):
    return "localStorage.setItem('septa.routes.v1', JSON.stringify({stars: %s, onlyMine: false}))" % json.dumps(routes)


def check_folding(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s)
        assert s.page.evaluate("window.SEPTA.map.map.getZoom()") <= 14
        assert s.page.evaluate("document.querySelector('#map').classList.contains('lod-far')")
        marks, badges = s.page.evaluate(STATE_JS), s.page.evaluate(BADGES_JS)
        assert len(marks) >= 60, len(marks)
        folded = [m for m in marks if m["inclu"]]
        assert badges and folded, "the fixture's Center City pile folds into badges"
        # every vehicle keeps its marker; a badge counts exactly the markers it stands in for
        assert sum(b["n"] for b in badges) == len(folded), (sum(b["n"] for b in badges), len(folded))
        assert all(b["n"] >= 3 for b in badges), badges
        # folded markers leave the tab order and the accessibility tree; badges are named buttons in it
        assert all(m["tab"] == -1 and m["hidden"] == "true" and not m["shown"] for m in folded)
        assert all(m["tab"] == 0 and m["hidden"] is None for m in marks if not m["inclu"])
        for b in badges:
            assert b["role"] == "button" and b["tab"] == 0, b
            assert b["label"].startswith(f"{b['n']} vehicles close together, route") and b["label"].endswith("Zoom in to see them"), b
        # labels never stack: no two shown labels overlap, and none sits on a badge
        shown = [m["box"] for m in marks if m["shown"]]
        assert len(shown) >= 10, len(shown)
        for i, a in enumerate(shown):
            for b in shown[i + 1:]:
                assert not overlap(a, b), ("labels overlap", a, b)
        for b in badges:
            for a in shown:
                assert not overlap(a, b["box"]), ("a label sits on a badge", a, b)
        # badges never stack on each other either
        for i, a in enumerate(badges):
            for b in badges[i + 1:]:
                assert not overlap(a["box"], b["box"]), ("badges overlap", a, b)
        assert not s.console_errors, s.console_errors


def test_zoomed_out_folds_piles_into_badges_and_labels_never_overlap(root):
    check_folding(root)
    # the labels really are collision-avoided (without it they stack) and the pile really folds (without it no badge)
    must_fail(check_folding, root, ("js/maplod.js", "if (it.rank > 0 && hits(b)) it.lbl = false;", ""))
    must_fail(check_folding, root, ("js/maplod.js", "if (g.members.length < L0.min) return false;", "return false;"))


def test_zoom_16_shows_every_marker_full_and_labelled(root):
    with Session(root) as s:
        boot(s)
        zoom(s, 16)
        cls = s.page.evaluate("document.querySelector('#map').className")
        assert "lod-far" not in cls and "lod-mid" not in cls, cls
        marks = s.page.evaluate(STATE_JS)
        assert marks and all(m["shown"] and not m["inclu"] and not m["dim"] for m in marks)
        assert s.page.evaluate("document.querySelectorAll('.veh-clu').length") == 0
        # the drawing is full size again (40 px box, a bus is 36 px long)
        h = s.page.evaluate("Math.max(...[...document.querySelectorAll('.veh-wrap.k-bus .bd')].slice(0, 5).map(b => { const r = b.getBoundingClientRect(); return Math.max(r.width, r.height); }))")
        assert h >= 34, h
        zoom(s, 15)
        assert "lod-mid" in s.page.evaluate("document.querySelector('#map').className")
        zoom(s, 13)
        assert "lod-far" in s.page.evaluate("document.querySelector('#map').className")
        h2 = s.page.evaluate("Math.max(...[...document.querySelectorAll('.veh-wrap.k-bus:not(.inclu):not(.hot) .bd')].slice(0, 5).map(b => { const r = b.getBoundingClientRect(); return Math.max(r.width, r.height); }))")
        assert h2 <= 24, ("compact when zoomed out", h2)


def test_badge_tap_and_keyboard_expand(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s)
        z0 = s.page.evaluate("window.SEPTA.map.map.getZoom()")
        n0 = s.page.evaluate("document.querySelectorAll('.veh-clu').length")
        assert n0 > 0
        s.page.evaluate("document.querySelector('.veh-clu').click()")
        s.page.wait_for_timeout(300)
        z1 = s.page.evaluate("window.SEPTA.map.map.getZoom()")
        assert z1 > z0, (z0, z1)
        # keyboard: focus a badge, Enter zooms in again (or, with none left, the markers are all unfolded)
        zoom(s, z0)
        s.page.focus(".veh-clu")
        s.page.keyboard.press("Enter")
        s.page.wait_for_timeout(300)
        assert s.page.evaluate("window.SEPTA.map.map.getZoom()") > z0
        assert not s.console_errors, s.console_errors


def test_selected_vehicle_leaves_its_pile(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s)
        i = s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].findIndex(e => e.classList.contains('inclu'))")
        assert i >= 0
        s.page.evaluate(f"document.querySelectorAll('.veh-wrap')[{i}].click()")
        s.page.wait_for_selector("#detail:not([hidden])")
        e = s.page.evaluate(f"""(() => {{ const e = document.querySelectorAll('.veh-wrap')[{i}], rt = e.querySelector('.rt');
            return {{sel: e.classList.contains('sel'), inclu: e.classList.contains('inclu'), shown: getComputedStyle(rt).display !== 'none', z: parseInt(e.style.zIndex)}}; }})()""")
        assert e["sel"] and not e["inclu"] and e["shown"], e
        s.page.click("#detailClose")
        assert s.page.evaluate(f"document.querySelectorAll('.veh-wrap')[{i}].classList.contains('inclu')"), "closing the card folds it back"


def check_prominence(root):
    with Session(root, viewport=(390, 844), init_scripts=[stars(["21", "47"])]) as s:
        boot(s)
        marks = s.page.evaluate(STATE_JS)
        mine = [m for m in marks if m["route"] in ("21", "47")]
        rest = [m for m in marks if m["route"] not in ("21", "47")]
        assert mine and rest
        assert all(m["hot"] and not m["inclu"] and not m["dim"] for m in mine), [m for m in mine if not m["hot"] or m["inclu"]][:3]
        assert all(m["dim"] and not m["hot"] for m in rest if not m["inclu"])
        # a prominent vehicle's label is drawn first, so at most a clash with another prominent label hides it
        assert sum(1 for m in mine if m["shown"]) >= len(mine) * 0.6, mine
        z = s.page.evaluate("""() => { const e = [...document.querySelectorAll('.veh-wrap.hot')][0], o = [...document.querySelectorAll('.veh-wrap.dim')][0];
            return [parseInt(e.style.zIndex), parseInt(o.style.zIndex)]; }""")
        assert z[0] > z[1] + 300, z
        # the route pill is in the mode colour with readable text
        c = s.page.evaluate("(() => { const r = getComputedStyle(document.querySelector('.veh-wrap.hot.k-bus .rt')); return [r.backgroundColor, r.color]; })()")
        assert c[0] != "rgb(255, 255, 255)", c


def test_cared_for_vehicles_stay_prominent_and_the_rest_dim(root):
    check_prominence(root)
    must_fail(check_prominence, root, ("js/maplod.js", "if (isStarred(starKey(v))) return true;", ""))


def test_pinned_and_open_stop_routes_are_prominent_without_stars(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s)
        assert s.page.evaluate("document.querySelectorAll('.veh-wrap.hot, .veh-wrap.dim').length") == 0, "nothing dims when nothing is highlighted"
        r = s.page.evaluate("""() => window.SEPTA.board.addPin({route: '47', stopId: '1234', stopName: 'Test stop', lat: 39.95, lng: -75.16, placeId: null})""")
        assert r["ok"], r
        s.page.wait_for_timeout(100)
        marks = s.page.evaluate(STATE_JS)
        assert any(m["route"] == "47" for m in marks)
        assert all(m["hot"] for m in marks if m["route"] == "47")
        assert all(not m["hot"] for m in marks if m["route"] != "47")
    with Session(root, viewport=(390, 844)) as s:
        boot(s, "#stop=14880&route=21")
        s.page.wait_for_selector("#copyStop")
        s.page.wait_for_timeout(200)
        marks = s.page.evaluate(STATE_JS)
        assert all(m["hot"] for m in marks if m["route"] == "21"), "the open stop's route"
        s.page.click("#stopClose")
        assert s.page.evaluate("document.querySelectorAll('.veh-wrap.hot').length") == 0


def many_buses(n):
    out = []
    for i in range(n):
        a, r = i * 2.39996, 0.0007 * math.sqrt(i)
        out.append({"lat": f"{CENTER[0] + r * math.cos(a):.6f}", "lng": f"{CENTER[1] + r * math.sin(a) * 1.3:.6f}", "label": str(5000 + i),
                    "route_id": str(1 + i % 90), "trip": str(i), "VehicleID": str(5000 + i), "BlockID": "1", "Direction": "Northbound",
                    "destination": "X", "heading": 0, "late": 0, "next_stop_id": "1", "next_stop_name": "Y", "next_stop_sequence": 1,
                    "estimated_seat_availability": "EMPTY", "Offset": 0, "Offset_sec": "0", "timestamp": TS})
    return out


def test_450_vehicles_lay_out_fast_and_unchanged_layouts_touch_no_dom(root):
    with Session(root, viewport=(390, 844)) as s:
        s.worker.data["TransitView"] = {"bus": many_buses(450)}
        boot(s)
        assert s.markers() >= 440, s.markers()
        t0 = time.perf_counter()
        s.page.evaluate("for (let i = 0; i < 20; i++) window.SEPTA.maplod.layout()")
        per = (time.perf_counter() - t0) / 20
        assert per < 0.05, f"one layout of 450 markers took {per * 1000:.1f} ms"
        # a layout that changes nothing writes nothing (DOM work is diffed, not redone)
        n = s.page.evaluate("""() => { let c = 0; const mo = new MutationObserver(l => { c += l.length; });
            mo.observe(document.querySelector('.leaflet-marker-pane'), {attributes: true, childList: true, subtree: true});
            window.SEPTA.maplod.layout(); const r = mo.takeRecords().length; mo.disconnect(); return c + r; }""")
        assert n == 0, f"{n} DOM mutations for a layout with nothing to change"
        assert s.page.evaluate("document.querySelectorAll('.veh-clu').length") > 0
        assert not s.console_errors, s.console_errors
