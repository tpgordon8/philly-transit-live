"""Baseline regression suite: the gatekeeper checklist, automated. Every branch must keep these green."""
import json

from harness import FIX, Session

HOOK = ["window.__SEPTA_TEST__ = true"]  # exposes the app's pure functions (see index.html)
TV = json.loads((FIX / "TransitView.json").read_text())
TR = json.loads((FIX / "TrainView.json").read_text())


def test_boot_clean_and_live(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        s.shot("baseline_boot")
        assert not s.console_errors, f"console errors: {s.console_errors}"
        assert not s.septa_direct, f"page called SEPTA directly: {s.septa_direct}"
        assert not s.unexpected, f"unexpected external requests: {s.unexpected}"
        n = s.markers()
        assert 20 <= n <= 400, f"marker count not sane: {n}"
        assert not s.page.evaluate("document.querySelector('#banner').hidden === false"), "banner shown while live"


def test_every_marker_has_route_and_direction_badge(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        bad = s.page.evaluate("""() => [...document.querySelectorAll('.veh-wrap')].filter(w => {
            const rt = w.querySelector('.rt'), dr = w.querySelector('.dr');
            return !rt || !rt.textContent.trim() || !dr || !/^(N|NE|E|SE|S|SW|W|NW|\\?)$/.test(dr.textContent.trim());
        }).length""")
        assert bad == 0, f"{bad} markers lack a route badge or a valid direction badge"


def test_badges_paint_above_vehicle_drawing(root):
    # regression: Leaflet gives map-pane svgs z-index 200, which once hid the route badges
    with Session(root) as s:
        s.open()
        s.wait_live()
        res = s.page.evaluate("""() => { const w = document.querySelector('.veh-wrap');
            const z = e => parseInt(getComputedStyle(e).zIndex) || 0;
            return {svg: z(w.querySelector('.vb')), rt: z(w.querySelector('.rt')), dr: z(w.querySelector('.dr'))}; }""")
        assert res["rt"] > res["svg"] and res["dr"] > res["svg"], f"badges not above drawing: {res}"


def test_marker_count_matches_non_ghost_vehicles(root):
    with Session(root, init_scripts=HOOK) as s:
        s.open()
        s.wait_live()
        expected = s.page.evaluate("""([tv, tr]) => { const T = window.__SEPTA_TEST__, c = {lat: 39.9526, lng: -75.1652};
            const keys = new Set(); T.normBuses(tv).concat(T.normTrains(tr)).forEach(v => { if (T.distMi(c, v) <= 1.5) keys.add(v.key); });
            return keys.size; }""", [TV, TR])
        assert s.markers() == expected, f"markers {s.markers()} != expected non-ghost vehicles {expected}"


def test_ghost_filter_rules(root):
    with Session(root, init_scripts=HOOK) as s:
        s.open()
        r = s.page.evaluate("""(tv) => { const T = window.__SEPTA_TEST__; const kept = T.normBuses(tv);
            return {kept: kept.length, raw: tv.bus.length,
                    emptyId: kept.filter(v => !v.vid || v.vid === 'None').length,
                    late999: kept.filter(v => v.late === 999).length,
                    unknownLate: kept.filter(v => v.late === null).length}; }""", TV)
        assert r["kept"] < r["raw"], "no ghosts were dropped from a fixture that contains ghosts"
        assert r["emptyId"] == 0, f"{r['emptyId']} kept vehicles have no real vehicle ID"
        assert r["late999"] == 0 and r["unknownLate"] > 0, f"late:999 must become unknown (null): {r}"


def test_late_999_shows_unavailable_never_999(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        seen = s.page.evaluate("""() => { let found = false, leaked = false;
            for (const w of document.querySelectorAll('.veh-wrap')) { w.click();
                const t = document.querySelector('#detail').textContent;
                if (/Delay data unavailable/.test(t)) found = true;
                if (/999/.test(t)) leaked = true; }
            return {found, leaked}; }""")
        assert seen["found"], "no marker showed 'Delay data unavailable' (fixture has late:999 vehicles)"
        assert not seen["leaked"], "'999' leaked into a detail card"


def test_refresh_moves_markers_in_place_without_touching_view(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        s.page.mouse.move(900, 400); s.page.mouse.down(); s.page.mouse.move(780, 340, steps=6); s.page.mouse.up()
        s.page.wait_for_timeout(1500)  # let Leaflet's pan inertia finish before measuring the view
        s.page.evaluate("document.querySelectorAll('.veh-wrap').forEach((e,i)=>{e.dataset.mark=i})")
        view = """() => ({pane: document.querySelector('.leaflet-map-pane').style.transform,
            zoom: [...new Set([...document.querySelectorAll('.leaflet-tile')].map(t => (t.src.match(/openstreetmap\\.org\\/(\\d+)\\//) || [])[1]))].join()})"""
        before_view = s.page.evaluate(view)
        before = s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].map(e => e.dataset.mark + '|' + e.style.transform)")
        for b in s.worker.data["TransitView"]["bus"]:
            b["lat"] = str(float(b["lat"]) + 0.0006)
        s.tick(15000)
        after_view = s.page.evaluate(view)
        after = s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].filter(e => e.dataset.mark).map(e => e.dataset.mark + '|' + e.style.transform)")
        assert before_view == after_view, f"view changed on refresh: {before_view} -> {after_view}"
        assert len(after) >= 0.95 * len(before), f"markers were remounted: kept {len(after)} of {len(before)}"
        moved = len(set(after) - set(before))
        assert moved >= 0.5 * len(before), f"markers did not move in place: only {moved} of {len(before)} changed"
        dur = s.page.evaluate("getComputedStyle(document.querySelector('.veh-wrap')).transitionDuration")
        assert dur not in ("0s", ""), f"markers have no glide transition: {dur}"


def test_failure_at_boot_shows_honest_unavailable_state(root):
    with Session(root) as s:
        s.worker.mode = "abort"
        s.open()
        s.tick(3000)  # first attempt + the single retry
        banner = s.page.evaluate("document.querySelector('#banner').hidden ? '' : document.querySelector('#banner').textContent")
        assert "Live data unavailable" in banner, f"banner: {banner!r}"
        assert s.markers() == 0, "markers shown while no live data exists"
        counts = s.page.evaluate("[...document.querySelectorAll('[data-n]')].map(n => n.textContent)")
        assert all(c in ("0", "") for c in counts), f"counters not zero/empty: {counts}"


def test_failure_after_success_dims_then_clears_and_says_unavailable(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        s.worker.mode = "abort"
        s.tick(17000)
        s.tick(2000)
        stale = s.page.evaluate("document.querySelectorAll('.veh-wrap.stale').length")
        assert stale > 0, "markers not dimmed after a failed refresh"
        s.tick(125000)
        assert s.markers() == 0, "markers still shown 2+ minutes after the last good update"
        banner = s.page.evaluate("document.querySelector('#banner').hidden ? '' : document.querySelector('#banner').textContent")
        assert "unavailable" in banner.lower(), f"banner should say live data is unavailable once markers clear: {banner!r}"


def test_alerts_render_as_plain_text(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        s.page.click("#scopeAll")
        n = s.page.evaluate("document.querySelectorAll('#alerts li.alert').length")
        assert n > 0, "no alerts rendered"
        html_leak = s.page.evaluate("[...document.querySelectorAll('#alerts li.alert p')].filter(p => /<[a-z]+[^>]*>/i.test(p.textContent)).length")
        assert html_leak == 0, "raw HTML tags leaked into alert text"


def test_mobile_viewport_has_no_horizontal_scroll(root):
    with Session(root, viewport=(390, 844)) as s:
        s.open()
        s.wait_live()
        s.shot("baseline_mobile")
        over = s.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert over <= 0, f"page scrolls horizontally by {over}px at 390px width"
        vis = s.page.evaluate("({map: !!document.querySelector('#map').offsetHeight, panel: !!document.querySelector('#panel').offsetHeight})")
        assert vis["map"] and vis["panel"], f"map or panel not visible on mobile: {vis}"
