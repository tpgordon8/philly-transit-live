"""Indego bike stations on the map (ARCHITECTURE.md 15.5): the mode chip, markers by availability, zoom rules, the station card,
Directions into the trip planner, polling rules, failure behaviour, phone layout and badge contrast. Hermetic: the harness mocks the
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
        assert n_markers(s) == 150, n_markers(s)
        far = s.page.evaluate("""() => { const m = window.__SEPTA_TEST__.tripMap, c = m.getCenter(); let worst = 0, ok = 0;
          document.querySelectorAll('.ind-wrap').forEach(e => { const r = e.getBoundingClientRect(), mr = m.getContainer().getBoundingClientRect();
            const d = Math.hypot(r.left + 22 - mr.left - mr.width / 2, r.top + 38 - mr.top - mr.height / 2); worst = Math.max(worst, d); ok++; }); return worst; }""")
        near_unshown = s.page.evaluate("""(st) => { const m = window.__SEPTA_TEST__.tripMap, mr = m.getContainer().getBoundingClientRect(); const shown = new Set();
          document.querySelectorAll('.ind-wrap').forEach(e => shown.add(e.getAttribute('title')));
          let best = 1e9; st.forEach(s => { if (shown.has(s.name)) return; const p = m.latLngToContainerPoint([s.lat, s.lon]); if (!m.getBounds().contains([s.lat, s.lon])) return;
            best = Math.min(best, Math.hypot(p.x - mr.width / 2, p.y - mr.height / 2)); }); return best; }""",
                                      [{"lat": x["lat"], "lon": x["lon"], "name": x["name"]} for x in s.mocks.stations()])
        assert near_unshown >= far - 3, ("a nearer station was left out", near_unshown, far)
        # zoom 16 and closer: every station in the bounds
        view(s, 16)
        assert n_markers(s) == in_bounds(s) and n_markers(s) > 0
        # below 14: no markers, a hint pill, no count
        view(s, 13)
        assert n_markers(s) == 0
        assert s.page.is_visible("#indegoHint") and s.page.inner_text("#indegoHint") == "Zoom in to see Indego stations"
        assert s.page.inner_text("#indegoN") == ""
        view(s, 14)
        assert n_markers(s) > 0 and s.page.is_hidden("#indegoHint")
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
        if t["electric"] + t["classic"] == b and b:
            assert f"{t['electric']} electric, {t['classic']} classic" in card, card
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
        # Directions fills the To field with this station and opens the planner
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
        assert s.page.is_visible("#indegoHint") and "Indego bike data unavailable" in s.page.inner_text("#indegoHint")
        assert s.page.evaluate("document.querySelectorAll('.ind-wrap.stale').length") == 0, "not dimmed yet"
        for _ in range(4):
            s.tick(MIN)
        s.tick(5000)
        assert n_markers(s) == n0
        assert s.page.evaluate("document.querySelectorAll('.ind-wrap.stale').length") == n0, "dimmed after three minutes"
        assert s.page.evaluate("getComputedStyle(document.querySelector('.ind-wrap')).opacity") != "1"
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
        assert s.page.inner_text("#indegoHint") == "Indego bike data unavailable"
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
            # the Close button is a 44 px target; Directions too
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
