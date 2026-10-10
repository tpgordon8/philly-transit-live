"""Indego bike stations on the map (ARCHITECTURE.md 15.5): the mode chip, markers by availability, zoom rules, the station card,
Walk here into the trip planner, polling rules, failure behaviour, phone layout and badge contrast. Hermetic: the harness mocks the
Worker's /indego/* endpoints and the direct fallback."""
import json
import time

from harness import Session
import test_responsive as R

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_chip_is_off_by_default_persists_and_asks_for_nothing_while_off",
    "test_markers_follow_zoom_and_are_capped",
    "test_card_directions_escape_and_keyboard",
}

HOOK = "window.__SEPTA_TEST__ = true"
ON = """(() => { try { localStorage.setItem('septa.prefs.v1', JSON.stringify({radius: 0.5,
  filters: {bus: true, trolley: false, subway: false, train: false, indego: true}})); } catch (e) {} })();"""
CC = (39.9526, -75.1652)
MIN = 60000


def start(root, on=True, vp=(1280, 800), zoom=15, center=CC, **kw):
    s = Session(root, viewport=vp, init_scripts=[HOOK] + ([ON] if on else []), **kw)
    return s


def boot(s, zoom=15, center=CC, wait_markers=True):
    s.open()
    s.wait_live()
    view(s, zoom, center)
    if wait_markers:
        s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0", timeout=8000)
        s.page.wait_for_timeout(100)


def view(s, zoom, center=CC):
    s.page.evaluate("([z, c]) => window.__SEPTA_TEST__.tripMap.setView(c, z, {animate: false})", [zoom, list(center)])
    s.page.wait_for_timeout(120)


def status_hits(s):
    return s.mocks.worker_indego_hits.count("status")


def info_hits(s):
    return s.mocks.worker_indego_hits.count("information")


def n_markers(s):
    return s.page.evaluate("document.querySelectorAll('.ind-wrap').length")


def in_bounds(s):
    """Stations of the mock feed inside the current map bounds."""
    st = [(x["lat"], x["lon"]) for x in s.mocks.stations()]
    return s.page.evaluate("""(st) => { const b = window.__SEPTA_TEST__.tripMap.getBounds().pad(0.05);
        return st.filter(p => b.contains(p)).length; }""", st)


def station_el(s, sid_name):
    return s.page.locator(f'.ind-wrap[aria-label^="Indego station {sid_name},"]')


def set_hidden(s, hidden):
    s.page.evaluate("""(h) => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => h});
        Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => h ? 'hidden' : 'visible'});
        document.dispatchEvent(new Event('visibilitychange')); }""", hidden)


# ---------------------------------------------------------------- chip, persistence, no requests while off

def test_chip_is_off_by_default_persists_and_asks_for_nothing_while_off(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        s.wait_live()
        view(s, 16)
        chip = s.page.locator('#modes input[data-mode="indego"]')
        assert chip.count() == 1 and not chip.is_checked()
        assert s.page.inner_text('label.k-indego').strip().startswith("Indego")
        s.tick(3 * MIN)
        assert s.mocks.worker_indego_hits == [] and s.mocks.direct_indego_hits == [], "no Indego request while the chip is off"
        assert n_markers(s) == 0 and s.page.is_hidden("#indegoHint")
        s.page.click("label.k-indego")
        s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0", timeout=8000)
        assert json.loads(s.page.evaluate("localStorage.getItem('septa.prefs.v1')"))["filters"]["indego"] is True
        s.page.reload()
        s.wait_live()
        assert s.page.locator('#modes input[data-mode="indego"]').is_checked(), "the choice survives a reload"
        assert "on" in s.page.get_attribute("label.k-indego", "class").split()
        s.page.click("label.k-indego")
        s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length === 0")
        assert json.loads(s.page.evaluate("localStorage.getItem('septa.prefs.v1')"))["filters"]["indego"] is False
        assert not s.console_errors, s.console_errors


def test_saved_prefs_without_the_indego_key_are_kept_and_mean_off(root):
    old = {"radius": 2, "filters": {"bus": True, "trolley": True, "subway": False, "train": True}}
    pre = "localStorage.setItem('septa.prefs.v1', %s); localStorage.setItem('septa.defaults.v2', '1');" % json.dumps(json.dumps(old))
    with Session(root, legacy_defaults=False, init_scripts=[HOOK, "(() => { try { if (!localStorage.getItem('septa.prefs.v1')) { " + pre + " } } catch (e) {} })();"]) as s:
        s.open()
        s.wait_live()
        assert json.loads(s.page.evaluate("localStorage.getItem('septa.prefs.v1')")) == old, "loading must not rewrite saved prefs"
        assert not s.page.locator('#modes input[data-mode="indego"]').is_checked()
        assert s.page.input_value("#radius") == "2"
        for m in ("trolley", "train"):
            assert s.page.locator(f'#modes input[data-mode="{m}"]').is_checked(), m
        s.page.click("label.k-indego")
        f = json.loads(s.page.evaluate("localStorage.getItem('septa.prefs.v1')"))["filters"]
        assert f == {"bus": True, "trolley": True, "subway": False, "train": True, "indego": True}, f


# ---------------------------------------------------------------- markers: zoom rules, cap, badge classes, names

def test_markers_follow_zoom_and_are_capped(root):
    with start(root, vp=(1600, 1100)) as s:
        boot(s, 15)
        assert s.page.is_hidden("#indegoHint")
        n15 = n_markers(s)
        assert 0 < n15 <= 150 and n15 == min(150, in_bounds(s)), (n15, in_bounds(s))
        assert s.page.inner_text("#indegoN") == str(in_bounds(s)), "the chip counts the stations in view"
        # zoom 14: a wide view holds more than 150 stations, so the cap applies; the nearest to the centre stay
        view(s, 14)
        assert in_bounds(s) > 150, in_bounds(s)
        # 150 to 170 are drawn: the nearest 150 always, plus markers kept from zoom 15 that still rank inside 170
        assert 150 <= n_markers(s) <= 170, n_markers(s)
        left_out = s.page.evaluate("""(st) => { const m = window.__SEPTA_TEST__.tripMap, c = m.getCenter(), k = Math.cos(c.lat * Math.PI / 180), b = m.getBounds().pad(0.05);
          const shown = new Set(); document.querySelectorAll('.ind-wrap').forEach(e => shown.add(e.getAttribute('title')));
          const near = st.filter(s => b.contains([s.lat, s.lon])).sort((a, z) => ((a.lon - c.lng) * k) ** 2 + (a.lat - c.lat) ** 2 - (((z.lon - c.lng) * k) ** 2 + (z.lat - c.lat) ** 2));
          return near.slice(0, 150).filter(s => !shown.has(s.name)).length; }""",
                                  [{"lat": x["lat"], "lon": x["lon"], "name": x["name"]} for x in s.mocks.stations()])
        assert left_out == 0, ("a station among the nearest 150 was left out", left_out)
        # zoom 16 and closer: every station in the bounds
        view(s, 16)
        assert n_markers(s) == in_bounds(s) and n_markers(s) > 0
        # below 14: no markers, a hint pill, no count
        view(s, 13)
        assert n_markers(s) == 0
        assert s.page.is_visible("#indegoHint") and s.page.inner_text("#indegoHint") == "Zoom in to see Indego stations"
        assert s.page.inner_text("#indegoN") == ""
        view(s, 14)
        assert n_markers(s) > 0
        # more stations in view than drawn: the chip counts the view and the pill says how to see the rest
        assert int(s.page.inner_text("#indegoN")) > n_markers(s)
        assert s.page.inner_text("#indegoHint") == "Zoom in to see all Indego stations"
        view(s, 16)
        assert s.page.is_hidden("#indegoHint")
        assert not s.console_errors, s.console_errors


def test_hint_pill_is_clear_of_controls_and_cards(root):
    for vp in ((390, 844), (1280, 800)):
        with R.session(root, vp, init_scripts=[HOOK, ON]) as s:
            s.open()
            s.wait_live()
            view(s, 12)
            s.page.wait_for_selector("#indegoHint:not([hidden])")
            h = R.rect(s, "#indegoHint")
            z = R.rect(s, ".leaflet-control-zoom")
            m = R.rect(s, "#map")
            assert not R.overlap(h, z), (vp, h, z)
            assert h["l"] >= m["l"] and h["r"] <= m["r"] and h["t"] >= m["t"], (vp, h, m)
            assert s.page.evaluate("getComputedStyle(document.querySelector('#indegoHint')).pointerEvents") == "none"
            assert s.page.evaluate("document.querySelector('#indegoHint').getAttribute('role')") == "status"
            # the banner owns the top of the map: the hint steps aside
            s.page.evaluate("document.querySelector('#banner').hidden = false; document.querySelector('#banner').textContent = 'Test banner'")
            assert s.page.is_hidden("#indegoHint")


def test_badge_class_by_availability_names_and_zero_cue(root):
    with start(root) as s:
        near = sorted(s.mocks.stations(), key=lambda x: (x["lat"] - CC[0]) ** 2 + ((x["lon"] - CC[1]) * 0.77) ** 2)[:4]
        ids = [x["station_id"] for x in near]
        names = {x["station_id"]: x["name"] for x in near}
        for sid, b in zip(ids, (0, 1, 2, 3)):
            s.mocks.set_station(sid, bikes=b, docks=7)
        boot(s, 16)
        want = {0: "av-none", 1: "av-low", 2: "av-low", 3: "av-ok"}
        for sid, b in zip(ids, (0, 1, 2, 3)):
            nm = names[sid]
            row = s.page.evaluate("""(nm) => { const e = [...document.querySelectorAll('.ind-wrap')].find(x => x.getAttribute('title') === nm);
              if (!e) return null; const t = e.querySelector('.ind-b'); const slash = e.querySelector('.ind-slash');
              return {cls: t.className, num: e.querySelector('.ind-n').textContent, label: e.getAttribute('aria-label'), role: e.getAttribute('role'),
                tab: e.getAttribute('tabindex'), slash: getComputedStyle(slash).display, w: e.getBoundingClientRect().width, h: e.getBoundingClientRect().height}; }""", nm)
            assert row, nm
            assert want[b] in row["cls"].split(), (nm, b, row)
            assert row["num"] == str(b), row
            assert row["label"] == f"Indego station {nm}, {b} bike{'' if b == 1 else 's'}, 7 open docks", row["label"]
            assert row["role"] == "button" and row["tab"] == "0" and row["w"] >= 44 and row["h"] >= 44, row
            assert (row["slash"] != "none") == (b == 0), ("only the empty station is crossed out", row)
        # a station that is not renting counts as no bikes; one out of service says so
        s.mocks.set_station(ids[3], bikes=6, docks=2, renting=False)
        s.mocks.set_station(ids[2], installed=False, bikes=0, docks=0)
        s.tick(MIN)
        s.page.wait_for_timeout(300)
        lab = s.page.evaluate("""(nms) => nms.map(nm => { const e = [...document.querySelectorAll('.ind-wrap')].find(x => x.getAttribute('title') === nm); return e && e.getAttribute('aria-label'); })""",
                              [names[ids[3]], names[ids[2]]])
        assert lab[0] == f"Indego station {names[ids[3]]}, 0 bikes, 2 open docks", lab
        assert lab[1].endswith(", out of service"), lab


# ---------------------------------------------------------------- card, directions, keyboard

def open_first(s, how="click"):
    nm = s.page.evaluate("""() => { const m = document.querySelector('#map').getBoundingClientRect();
        const e = [...document.querySelectorAll('.ind-wrap')].find(e => { const r = e.getBoundingClientRect();
          return r.left > m.left + 20 && r.right < m.right - 90 && r.top > m.top + 90 && r.bottom < m.bottom - 200; });
        e.dataset.pick = '1'; return e.getAttribute('title'); }""")
    e = s.page.locator('.ind-wrap[data-pick="1"]')
    if how == "click":
        e.evaluate("e => e.click()")
    else:
        e.focus()
        s.page.keyboard.press(how)
    s.page.wait_for_selector("#indegoCard:not([hidden])")
    s.page.wait_for_timeout(300)
    return nm


def test_card_directions_escape_and_keyboard(root):
    with start(root) as s:
        stn = s.mocks.stations()
        # a status time 40 s old
        s.mocks.indego_status["last_updated"] = int(time.time()) - 40
        boot(s, 15)
        nm = open_first(s)
        s_id = next(x for x in stn if x["name"] == nm)
        st = s.mocks._status(s_id["station_id"])
        card = s.page.inner_text("#indegoCard")
        b, d = st["num_bikes_available"], st["num_docks_available"]
        assert f"{b} bike{'' if b == 1 else 's'}, {d} open dock{'' if d == 1 else 's'}" in card, card
        t = st["num_bikes_available_types"]
        if t["electric"] + t["classic"] + t["smart"] == b and b:
            want = [f"{t[k]} {k}" for k in ("electric", "classic", "smart") if t[k]]
            assert ", ".join(want) in card, (want, card)
        import re
        age = re.search(r"Updated (\d+) s ago", card)
        assert age and 35 <= int(age.group(1)) <= 60, card
        assert s.page.text_content("#indegoHead") == nm
        assert s.page.get_attribute("#indegoCard", "role") == "region"
        assert "Station details opened" in s.page.inner_text("#indegoLive")
        assert s.page.evaluate("document.querySelector('.ind-wrap.sel') !== null")
        # the age moves with the clock
        s.tick(20000)
        assert int(re.search(r"Updated (\d+) s ago", s.page.inner_text("#indegoCard")).group(1)) >= int(age.group(1)) + 15
        # Walk here fills the To field with this station and opens the planner
        s.page.click("#indegoDir")
        assert s.page.input_value("#tripTo") == nm[:40]
        assert s.page.is_hidden("#indegoCard")
        assert s.page.evaluate("document.activeElement.id") in ("tripFrom", "tripGo")
        # plan from the typed place: the end point is the station's coordinates, not a geocode of the name
        s.page.fill("#tripFrom", "city hall")
        s.page.locator(".sug-opt", has_text="Philadelphia City Hall").first.click()
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripResults .tp-card", timeout=15000)
        ends = [h["to"] for h in s.mocks.worker_route_hits if h.get("to")]
        assert any(abs(e[0] - s_id["lat"]) < 0.0005 and abs(e[1] - s_id["lon"]) < 0.0005 for e in ends), (ends, s_id)
        # keyboard: Enter and Space open the card, Escape closes it and puts focus back on the marker
        view(s, 15)
        s.page.wait_for_timeout(200)
        for key in ("Enter", " "):
            nm2 = open_first(s, key)
            assert s.page.evaluate("document.activeElement.id") == "indegoHead", key
            s.page.keyboard.press("Escape")
            assert s.page.is_hidden("#indegoCard")
            assert s.page.evaluate("document.activeElement.getAttribute('title')") == nm2 and s.page.evaluate("document.activeElement.classList.contains('ind-wrap')")
            s.page.evaluate("document.querySelectorAll('.ind-wrap').forEach(e => delete e.dataset.pick)")
        # Close button returns focus to the marker too, and a click on the empty map closes the card
        open_first(s, "Enter")
        s.page.click("#indegoClose")
        assert s.page.is_hidden("#indegoCard") and s.page.evaluate("document.activeElement.classList.contains('ind-wrap')")
        s.page.evaluate("document.querySelectorAll('.ind-wrap').forEach(e => delete e.dataset.pick)")
        open_first(s)
        s.page.mouse.click(700, 120)
        s.page.wait_for_timeout(200)
        assert s.page.is_hidden("#indegoCard")
        assert not s.console_errors, s.console_errors


def test_one_card_at_a_time(root):
    with start(root) as s:
        boot(s, 16)
        open_first(s)
        # a vehicle card replaces the station card
        s.page.evaluate("document.querySelector('.veh-wrap').click()")
        s.page.wait_for_selector("#detail:not([hidden])")
        s.page.wait_for_timeout(200)
        assert s.page.is_hidden("#indegoCard")
        # and a station card replaces the vehicle card
        s.page.evaluate("document.querySelectorAll('.ind-wrap').forEach(e => delete e.dataset.pick)")
        open_first(s)
        assert s.page.is_hidden("#detail") and s.page.is_visible("#indegoCard")
        # Escape after a tap (focus not in the card) still closes it and puts focus on the marker
        s.page.keyboard.press("Escape")
        assert s.page.is_hidden("#indegoCard")
        assert s.page.evaluate("document.activeElement.classList.contains('ind-wrap')")
        # zooming out below 14 takes the card away with the markers
        s.page.evaluate("document.querySelectorAll('.ind-wrap').forEach(e => delete e.dataset.pick)")
        open_first(s)
        view(s, 13)
        assert s.page.is_hidden("#indegoCard") and n_markers(s) == 0


# ---------------------------------------------------------------- data freshness: polling, failure

def test_status_polls_once_a_minute_and_pauses_when_hidden_or_off(root):
    with start(root) as s:
        boot(s, 15)
        assert info_hits(s) == 1 and status_hits(s) == 1
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        n = status_hits(s)
        assert 4 <= n <= 5, ("about one status request a minute", n)
        assert info_hits(s) == 0, "station information is loaded once"
        # hidden tab: nothing
        set_hidden(s, True)
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        assert s.mocks.worker_indego_hits == [], s.mocks.worker_indego_hits
        # visible again: one request at once, then the minute rhythm
        set_hidden(s, False)
        s.page.wait_for_timeout(300)
        assert status_hits(s) == 1, s.mocks.worker_indego_hits
        # zoomed out: no polling either
        view(s, 12)
        s.mocks.worker_indego_hits.clear()
        s.tick(3 * MIN)
        assert s.mocks.worker_indego_hits == []
        view(s, 15)
        s.page.wait_for_timeout(300)
        assert status_hits(s) == 1
        # chip off: nothing
        s.page.click("label.k-indego")
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        assert s.mocks.worker_indego_hits == []
        assert n_markers(s) == 0
        # chip on again: markers come back from memory or one request, then it polls again
        s.page.click("label.k-indego")
        s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0")
        s.mocks.worker_indego_hits.clear()
        s.tick(2 * MIN)
        assert status_hits(s) >= 1
        assert not s.console_errors, s.console_errors


def test_idle_pause_stops_indego_polling(root):
    import test_idle_pause as I
    with start(root) as s:
        boot(s, 15)
        I.jump(s, 65)  # an hour and five minutes without a real interaction
        s.page.wait_for_timeout(300)
        s.mocks.worker_indego_hits.clear()
        s.tick(10 * MIN)
        assert s.mocks.worker_indego_hits == [], "paused after an hour without activity"
        s.page.keyboard.press("Shift")  # a real key press ends the pause
        s.page.wait_for_timeout(500)
        s.tick(2 * MIN)
        assert status_hits(s) >= 1


def test_failure_keeps_last_markers_dims_after_three_minutes_and_recovers(root):
    with start(root) as s:
        boot(s, 15)
        n0 = n_markers(s)
        assert s.page.is_hidden("#indegoHint")
        s.mocks.indego_mode = "http500"
        s.tick(MIN)
        s.tick(5000)
        s.page.wait_for_timeout(300)
        assert n_markers(s) == n0, "last data stays on the map"
        assert s.page.is_visible("#indegoHint") and "Indego data unavailable right now" in s.page.inner_text("#indegoHint")
        assert s.page.evaluate("document.querySelectorAll('.ind-wrap.stale').length") == 0, "not dimmed yet"
        for _ in range(4):
            s.tick(MIN)
        s.tick(5000)
        assert n_markers(s) == n0
        assert s.page.evaluate("document.querySelectorAll('.ind-wrap.stale').length") == n0, "dimmed after three minutes"
        lbl = s.page.evaluate("document.querySelector('.ind-wrap').getAttribute('aria-label')")
        assert lbl.endswith(", may be out of date"), lbl
        # a card shows the age and the warning
        open_first(s)
        assert "May be out of date" in s.page.inner_text("#indegoCard")
        # the feed comes back: markers brighten and the note goes
        s.mocks.indego_mode = "ok"
        s.tick(MIN)
        s.tick(3000)
        s.page.wait_for_timeout(300)
        assert s.page.evaluate("document.querySelectorAll('.ind-wrap.stale').length") == 0
        assert s.page.is_hidden("#indegoHint")
        assert not any("pageerror" in e for e in s.console_errors), s.console_errors


def test_failure_on_first_load_says_so_and_never_throws(root):
    with start(root) as s:
        s.mocks.indego_mode = "http500"
        s.open()
        s.wait_live()
        view(s, 15)
        s.tick(5000)
        s.page.wait_for_selector("#indegoHint:not([hidden])", timeout=8000)
        assert s.page.inner_text("#indegoHint") == "Indego data unavailable right now"
        assert n_markers(s) == 0
        assert not any("pageerror" in e for e in s.console_errors), s.console_errors


# ---------------------------------------------------------------- layout and colour

def test_phone_layout_no_overflow_and_card_clear_of_zoom(root):
    for vp in ((360, 740), (390, 844)):
        with R.session(root, vp, init_scripts=[HOOK, ON]) as s:
            s.open()
            s.wait_live()
            view(s, 15)
            s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0")
            R.check_overflow(s, vp, "markers")
            open_first(s)
            R.check_overflow(s, vp, "card")
            card, z, m = R.rect(s, "#indegoCard"), R.rect(s, ".leaflet-control-zoom"), R.rect(s, "#map")
            assert not R.overlap(card, z), (vp, card, z)
            assert card["l"] >= m["l"] and card["r"] <= m["r"] and card["b"] <= m["b"], (vp, card, m)
            # the marker was moved above the card
            e = s.page.evaluate("""() => { const r = document.querySelector('.ind-wrap.sel').getBoundingClientRect(); return {t: r.top, b: r.bottom, l: r.left, r: r.right}; }""")
            assert e["b"] <= card["t"] + 8 and e["t"] >= m["t"] - 1, (vp, e, card)
            # the Close button is a 44 px target; Walk here too
            for sel in ("#indegoClose", "#indegoDir"):
                r = R.rect(s, sel)
                assert r["w"] >= 43.5 and r["h"] >= 43.5, (sel, r)
            z_in = s.page.evaluate("""() => { const r = document.querySelector('.leaflet-control-zoom-in').getBoundingClientRect();
                return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).closest('.leaflet-control-zoom') !== null }""")
            assert z_in, "zoom buttons stay reachable"


def test_marker_and_badge_text_contrast_light_and_dark(root):
    js = """() => { const lum = (rgb) => { const c = rgb.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => v / 255).map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
      const out = {}; for (const cls of ['av-ok', 'av-low', 'av-none']) { const w = document.createElement('div'); w.className = 'ind-wrap'; const b = document.createElement('span'); b.className = 'ind-b ' + cls; b.textContent = '5'; w.appendChild(b); document.body.appendChild(w);
        const cs = getComputedStyle(b), a = lum(cs.color), c = lum(cs.backgroundColor); out[cls] = (Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05); w.remove(); } return out; }"""
    for scheme in ("light", "dark"):
        with Session(root, color_scheme=scheme) as s:
            s.open()
            s.wait_live()
            r = s.page.evaluate(js)
            assert set(r) == {"av-ok", "av-low", "av-none"} and all(v >= 4.5 for v in r.values()), (scheme, r)
    with Session(root) as s:  # the explicit theme switch works as well
        s.open()
        s.wait_live()
        s.page.evaluate("document.documentElement.dataset.theme = 'dark'")
        r = s.page.evaluate(js)
        assert all(v >= 4.5 for v in r.values()), r


def test_reduced_motion_adds_no_animation(root):
    with start(root, reduced_motion="reduce") as s:
        boot(s, 15)
        open_first(s)
        for sel in (".ind-wrap", "#indegoCard", "#indegoHint"):
            t = s.page.evaluate("(sel) => { const e = document.querySelector(sel); const cs = getComputedStyle(e); return [cs.transitionDuration, cs.animationName]; }", sel)
            assert t[0] in ("0s", "0s, 0s") and t[1] == "none", (sel, t)


# ---------------------------------------------------------------- v13 review fixes

def nearest(s, k=1):
    return sorted(s.mocks.stations(), key=lambda x: (x["lat"] - CC[0]) ** 2 + ((x["lon"] - CC[1]) * 0.77) ** 2)[:k]


def open_named(s, nm):
    s.page.evaluate("(nm) => [...document.querySelectorAll('.ind-wrap')].find(e => e.getAttribute('title') === nm).click()", nm)
    s.page.wait_for_selector("#indegoCard:not([hidden])")
    s.page.wait_for_timeout(300)


def failing_boot(s, zoom=15):
    s.open()
    s.wait_live()
    view(s, zoom)
    s.page.wait_for_selector("#indegoHint:not([hidden])", timeout=8000)


def no_page_errors(s):
    assert not any("pageerror" in e for e in s.console_errors), s.console_errors


BAD_ANSWERS = {
    "no stations key": {"data": {}},
    "no data": {},
    "stations not an array": {"data": {"stations": {"a": 1}}},
    "empty stations": {"data": {"stations": []}},
}


def test_malformed_status_is_a_failure_not_zero_stations(root):
    for label, bad in BAD_ANSWERS.items():
        with start(root) as s:
            good = s.mocks.indego_status
            s.mocks.indego_status = bad
            failing_boot(s)
            assert s.page.inner_text("#indegoHint") == "Indego data unavailable right now", label
            assert s.page.inner_text("#indegoN") == "" and n_markers(s) == 0, label
            s.mocks.indego_status = good
            s.tick(2 * MIN)
            s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0", timeout=8000)
            assert s.page.is_hidden("#indegoHint") and s.page.inner_text("#indegoN") != "", label
            no_page_errors(s)


def test_malformed_information_is_a_failure_and_is_not_cached(root):
    for label, bad in BAD_ANSWERS.items():
        with start(root) as s:
            good = s.mocks.indego_info
            s.mocks.indego_info = bad
            failing_boot(s)
            assert s.page.inner_text("#indegoHint") == "Indego data unavailable right now", label
            assert s.page.inner_text("#indegoN") == "" and n_markers(s) == 0, label
            assert info_hits(s) == 1
            s.mocks.indego_info = good
            s.tick(2 * MIN)
            s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0", timeout=8000)
            assert info_hits(s) == 2, ("the bad information answer must not be cached for the page", label, info_hits(s))
            no_page_errors(s)


def test_malformed_answer_keeps_last_stations_and_the_planner_still_reports_unavailable(root):
    with start(root) as s:
        boot(s, 15)
        n0 = n_markers(s)
        s.mocks.indego_status = {"data": {"stations": []}}
        s.tick(MIN)
        s.page.wait_for_timeout(300)
        assert n_markers(s) == n0 and s.page.inner_text("#indegoN") != "0"
        assert s.page.inner_text("#indegoHint") == "Indego data unavailable right now. Showing the last known bikes."
        code = s.page.evaluate("""() => window.SEPTA.routing.loadIndego(true).then(() => 'ok', e => e && e.code)""")
        assert code == "indego_unavailable", code
        no_page_errors(s)


def test_outage_backs_off_1_2_4_ticks_and_resets_on_success(root):
    with start(root) as s:
        boot(s, 15)
        s.mocks.indego_mode = "http500"
        s.mocks.worker_indego_hits.clear()
        attempts = []
        for minute in range(1, 17):
            before = status_hits(s)
            s.tick(MIN)
            if status_hits(s) > before:
                attempts.append(minute)
        assert attempts == [1, 3, 6, 11, 16], ("1, 2, 4, 4 ticks skipped between attempts", attempts)
        assert info_hits(s) == 0
        # the feed returns: the next attempt (minute 21) succeeds and the one-a-minute rhythm is back at once
        s.mocks.indego_mode = "ok"
        for _ in range(5):
            s.tick(MIN)
        s.page.wait_for_timeout(300)
        assert s.page.is_hidden("#indegoHint")
        s.mocks.worker_indego_hits.clear()
        s.tick(3 * MIN)
        assert status_hits(s) == 3, status_hits(s)
        no_page_errors(s)


def test_card_split_counts_smart_bikes_and_hides_when_it_does_not_add_up(root):
    with start(root) as s:
        a, b, c = nearest(s, 3)
        names = [x["name"] for x in (a, b, c)]
        s.mocks.set_station(a["station_id"], bikes=6, docks=4)
        s.mocks._status(a["station_id"])["num_bikes_available_types"] = {"electric": 2, "smart": 1, "classic": 3}
        s.mocks.set_station(b["station_id"], bikes=4, docks=4)
        s.mocks._status(b["station_id"])["num_bikes_available_types"] = {"electric": 0, "smart": 0, "classic": 4}
        s.mocks.set_station(c["station_id"], bikes=5, docks=4)
        s.mocks._status(c["station_id"])["num_bikes_available_types"] = {"electric": 1, "smart": 1, "classic": 1}
        boot(s, 17)
        open_named(s, names[0])
        assert "2 electric, 3 classic, 1 smart" in s.page.inner_text("#indegoCard")
        open_named(s, names[1])
        assert s.page.inner_text("#indegoTypes") == "4 classic"
        open_named(s, names[2])
        assert s.page.is_hidden("#indegoTypes"), "3 of 5 is no split"
        no_page_errors(s)


def test_non_string_names_do_not_throw(root):
    with start(root) as s:
        a, b, c = nearest(s, 3)
        a["name"], a["address"] = 12345, "1 Test St"
        b["name"] = {"x": 1}
        b.pop("address", None)
        c["name"] = None
        c["address"] = ["x"]
        boot(s, 17)
        titles = s.page.evaluate("[...document.querySelectorAll('.ind-wrap')].map(e => e.getAttribute('title'))")
        assert "1 Test St" in titles and titles.count("Indego station") >= 2, titles[:10]
        assert "12345" not in titles
        no_page_errors(s)


ALL_OFF_BUT_INDEGO = """(() => { try { localStorage.setItem('septa.prefs.v1', JSON.stringify({radius: 5,
  filters: {bus: false, trolley: false, subway: false, train: false, indego: INDEGO}})); } catch (e) {} })();"""


def test_show_all_modes_leaves_indego_as_it_was(root):
    for want in (True, False):
        with Session(root, viewport=(1280, 800), init_scripts=[HOOK, ALL_OFF_BUT_INDEGO.replace("INDEGO", "true" if want else "false")]) as s:
            s.open()
            view(s, 15)
            # The mock feed always has vehicles in range, so the empty state cannot be reached naturally; put its button in and click it.
            s.page.evaluate("""() => { const b = document.querySelector('#empty'); b.hidden = false;
                b.innerHTML = '<button class="btn primary" type="button" id="emptyAct" data-act="modes">Show all modes</button>'; }""")
            s.page.click("#emptyAct")
            s.page.wait_for_timeout(300)
            f = json.loads(s.page.evaluate("localStorage.getItem('septa.prefs.v1')"))["filters"]
            assert f == {"bus": True, "trolley": True, "subway": True, "train": True, "indego": want}, f
            assert s.page.locator('#modes input[data-mode="indego"]').is_checked() is want
            if want:
                s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0", timeout=8000)
            else:
                assert n_markers(s) == 0
            no_page_errors(s)


def test_card_closes_when_a_refresh_drops_its_station(root):
    with start(root) as s:
        boot(s, 16)
        nm = open_first(s)
        sid = next(x["station_id"] for x in s.mocks.stations() if x["name"] == nm)
        s.page.focus("#indegoHead")
        st = s.mocks.indego_status["data"]["stations"]
        s.mocks.indego_status["data"]["stations"] = [x for x in st if x["station_id"] != sid]
        s.tick(MIN)
        s.page.wait_for_timeout(300)
        assert s.page.is_hidden("#indegoCard"), "the card must not stay up for a station that is gone"
        assert s.page.evaluate("document.querySelector('#indegoLive').textContent") == ""
        assert s.page.evaluate("document.activeElement.classList.contains('leaflet-container')"), "focus goes to the map, not a removed marker"
        assert n_markers(s) > 0
        no_page_errors(s)


def test_zoom_out_closing_the_card_moves_focus_to_the_map(root):
    with start(root) as s:
        boot(s, 15)
        open_first(s, "Enter")
        assert s.page.evaluate("document.activeElement.id") == "indegoHead"
        view(s, 13)
        assert s.page.is_hidden("#indegoCard") and n_markers(s) == 0
        assert s.page.evaluate("document.activeElement.classList.contains('leaflet-container')"), s.page.evaluate("document.activeElement.outerHTML.slice(0, 80)")
        no_page_errors(s)


def _contrast_js():
    return """() => { const lum = (rgb) => { const c = rgb.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => v / 255).map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
      const w = document.querySelector('.ind-wrap.stale'); if (!w) return null; const b = w.querySelector('.ind-b'), cs = getComputedStyle(b);
      const a = lum(cs.color), c = lum(cs.backgroundColor);
      return {ratio: (Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05), wrap: getComputedStyle(w).opacity, badge: cs.opacity, bg: cs.backgroundColor}; }"""


def test_stale_markers_keep_readable_text_and_say_so(root):
    for scheme in ("light", "dark"):
        with start(root, color_scheme=scheme) as s:
            boot(s, 16)
            s.mocks.indego_mode = "http500"
            for _ in range(6):
                s.tick(MIN)
            s.tick(3000)
            s.page.wait_for_function("document.querySelectorAll('.ind-wrap.stale').length > 0", timeout=5000)
            r = s.page.evaluate(_contrast_js())
            assert r and r["ratio"] >= 4.5, (scheme, r)
            assert r["wrap"] == "1" and r["badge"] == "1", ("only the background is dimmed, never the number", r)
            labels = s.page.evaluate("[...document.querySelectorAll('.ind-wrap')].map(e => e.getAttribute('aria-label'))")
            assert labels and all(x.endswith(", may be out of date") for x in labels), labels[:3]
            s.mocks.indego_mode = "ok"
            for _ in range(6):
                s.tick(MIN)
            s.page.wait_for_function("document.querySelectorAll('.ind-wrap.stale').length === 0", timeout=5000)
            labels = s.page.evaluate("[...document.querySelectorAll('.ind-wrap')].map(e => e.getAttribute('aria-label'))")
            assert not any("out of date" in x for x in labels)


def test_panning_at_zoom_14_keeps_drawn_markers_until_they_rank_past_170(root):
    probe = """() => { const m = window.__SEPTA_TEST__.tripMap, c = m.getCenter(), k = Math.cos(c.lat * Math.PI / 180);
        const st = [...document.querySelectorAll('.ind-wrap')].map(e => e.getAttribute('title'));
        return {drawn: st, centre: [c.lat, c.lng], k: k}; }"""
    with start(root, vp=(1600, 1100)) as s:
        boot(s, 14)
        stn = [(x["name"], x["lat"], x["lon"]) for x in s.mocks.stations()]
        beyond = 0
        for dx, dy in ((0.004, 0), (0.0, 0.003), (-0.003, 0.002), (0.002, -0.004), (0.003, 0.003), (-0.004, -0.002)):
            before = set(s.page.evaluate(probe)["drawn"])
            c = s.page.evaluate("(() => { const c = window.__SEPTA_TEST__.tripMap.getCenter(); return [c.lat, c.lng]; })()")
            view(s, 14, (c[0] + dy, c[1] + dx))
            now = s.page.evaluate(probe)
            after = set(now["drawn"])
            lat0, lng0 = now["centre"]
            inb = s.page.evaluate("""(st) => { const b = window.__SEPTA_TEST__.tripMap.getBounds().pad(0.05); return st.filter(p => b.contains([p[1], p[2]])).map(p => p[0]); }""", stn)
            d = {n: (la - lat0) ** 2 + ((lo - lng0) * now["k"]) ** 2 for n, la, lo in stn if n in set(inb)}
            rank = {n: i for i, n in enumerate(sorted(d, key=d.get))}
            assert len(after) <= 170, len(after)
            for n in before & set(d):
                if rank[n] < 170:
                    assert n in after, ("a drawn marker inside the nearest 170 must stay", n, rank[n])
            for n in after - before:
                assert rank[n] < 150, ("a new marker enters only inside the nearest 150", n, rank[n])
            beyond += sum(1 for n in after if rank[n] >= 150)
        assert beyond > 0, "the pans never exercised the keep band"
        no_page_errors(s)
