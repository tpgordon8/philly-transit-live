"""Phone tab bar (ARCHITECTURE.md 15.9): Map, Trip, Board, Alerts and More at the bottom of a phone held upright. Only the current
tab's sections show in the sheet; wide screens and phone landscape keep the single side panel with no tab bar; the Board tab opens the
full-screen board and Back to map returns to the same tab; a stop link and the actions that target another tab switch to it; the tab
bar steps aside while a text field has focus (the on-screen keyboard). Each fast check runs again on a broken copy (`must_fail`)."""
import json

from harness import Session
from test_first_run import must_fail, seed

FAST = {
    "test_tabs_switch_and_only_the_current_tab_shows",
    "test_wide_screens_and_landscape_have_no_tab_bar",
    "test_board_tab_opens_the_board_and_back_returns",
    "test_stop_link_and_cross_tab_actions_switch_the_tab",
    "test_tab_bar_steps_aside_for_the_keyboard",
}

PHONE = (390, 844)
TAB_KEY = "septa.tab.v1"
STOP_HASH = "#stop=14880&route=21"
PLACES = {"home": {"name": "Home base", "lat": 39.95, "lng": -75.16}, "list": [{"id": "p1", "name": "Work", "lat": 39.96, "lng": -75.17}]}
SECTIONS = {  # one landmark per section, by tab
    "map": ["#h-find", "#filtersBtn"],
    "trip": ["#tripFrom", "#tripGo"],
    "alerts": ["#h-leave", "#h-alerts"],
    "more": ["#h-places", "#h-priv", "#h-about"],
}


def phone(root, **kw):
    return Session(root, viewport=kw.pop("viewport", PHONE), mobile=True, touch=True, **kw)


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()


def shown(s, sel):
    return s.page.evaluate("(sel) => { const e = document.querySelector(sel); return !!e && e.getClientRects().length > 0 }", sel)


def rect(s, sel):
    return s.page.evaluate("(sel) => document.querySelector(sel).getBoundingClientRect().toJSON()", sel)


def state(s):
    return s.page.evaluate("""() => ({tab: document.querySelector('#app').dataset.tab, sheet: document.querySelector('#app').dataset.sheet,
        current: [...document.querySelectorAll('#tabbar .tab[aria-current=page]')].map(b => b.dataset.go),
        stored: localStorage.getItem('septa.tab.v1'), active: document.activeElement && document.activeElement.id})""")


def only(s, tab):
    for t, sels in SECTIONS.items():
        for sel in sels:
            assert shown(s, sel) == (t == tab), (tab, sel, "should" + ("" if t == tab else " not") + " show")


def tabbar_h(s):
    return s.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--tabbar-h').trim()")


# ---------------------------------------------------------------- switching, storage, geometry, accessibility
def check_switch(root):
    with phone(root) as s:
        boot(s)
        st = state(s)
        assert st["tab"] == "map" and st["current"] == ["map"] and st["sheet"] == "peek" and st["stored"] is None, st
        only(s, "map")
        nav = s.page.evaluate("""() => { const n = document.querySelector('#tabbar'); return {tag: n.tagName, label: n.getAttribute('aria-label'),
            names: [...n.querySelectorAll('button')].map(b => b.querySelector('.tab-l').textContent),
            boxes: [...n.querySelectorAll('button')].map(b => { const r = b.getBoundingClientRect(); return [r.width, r.height, r.bottom]; }),
            bar: n.getBoundingClientRect().toJSON()}; }""")
        assert nav["tag"] == "NAV" and nav["label"] == "Sections" and nav["names"] == ["Map", "Trip", "Board", "Alerts", "More"], nav
        assert all(w >= 44 and h >= 56 for w, h, b in nav["boxes"]), nav["boxes"]
        assert abs(nav["bar"]["bottom"] - 844) < 1 and nav["bar"]["height"] >= 56, nav["bar"]
        assert tabbar_h(s) in ("calc(56px + 0px)", "56px") or s.page.evaluate("parseFloat(getComputedStyle(document.querySelector('#tabbar')).height)") == 56
        # the sheet and the map end at the tab bar: nothing is covered
        panel, mp = rect(s, "#panel"), rect(s, "#map")
        assert abs(panel["bottom"] - nav["bar"]["top"]) < 1.5 and mp["bottom"] <= panel["top"] + 1, (panel, mp, nav["bar"])
        assert rect(s, "#btnLocate")["bottom"] <= nav["bar"]["top"], "the quick actions are in the closed sheet, above the bar"
        # Trip: its sections only, the sheet opens, the choice is remembered
        s.page.click("#tabTrip")
        st = state(s)
        assert st["tab"] == "trip" and st["current"] == ["trip"] and st["sheet"] == "open" and st["stored"] == "trip", st
        only(s, "trip")
        s.page.wait_for_timeout(350)
        assert rect(s, "#map")["height"] > 200 and abs(rect(s, "#panel")["bottom"] - nav["bar"]["top"]) < 1.5
        s.page.click("#tabAlerts")
        only(s, "alerts")
        # keyboard: Tab reaches the tab buttons and Enter activates one
        s.page.focus("#tabMore")
        s.page.keyboard.press("Enter")
        st = state(s)
        assert st["tab"] == "more" and st["current"] == ["more"] and st["stored"] == "more" and st["active"] == "tabMore", st
        only(s, "more")
        # Map closes the sheet to the peek; the current Map tab toggles it
        s.page.click("#tabMap")
        assert state(s)["sheet"] == "peek" and state(s)["tab"] == "map"
        s.page.click("#tabMap")
        assert state(s)["sheet"] == "open"
        s.page.click("#tabMore")
        s.page.reload()
        s.wait_live()
        st = state(s)
        assert st["tab"] == "more" and st["sheet"] == "open", ("remembered", st)
        only(s, "more")
        assert not s.console_errors, s.console_errors
    for junk in ("board", "x", "{}"):
        with phone(root, init_scripts=[seed(TAB_KEY, junk)]) as s:
            boot(s)
            assert state(s)["tab"] == "map", junk


def test_tabs_switch_and_only_the_current_tab_shows(root):
    check_switch(root)
    must_fail(check_switch, root, ("css/layout.css", "#app[data-tab=trip] #panel>[data-tab]:not([data-tab=trip]),", ""))
    must_fail(check_switch, root, ("js/sheet.js", "if (opts.save) saveTab(t);", ""))
    must_fail(check_switch, root, ("js/sheet.js", "else if (changed) setOpen(t !== 'map');", ""))


def test_alerts_badge_and_filters_disclosure(root):
    with phone(root) as s:
        boot(s)
        s.page.wait_for_function("/\\d/.test(document.querySelector('#alertCount').textContent)")
        n = int(s.page.text_content("#alertCount").strip("() "))
        assert s.page.text_content("#tabAlertN") == (str(n) if n < 100 else "99+") and shown(s, "#tabAlertN")
        assert s.page.evaluate("document.querySelector('#tabAlerts').textContent.replace(/\\s+/g, ' ').trim()").endswith(f"Alerts, {n} service alert{'s' if n != 1 else ''}")
        s.page.evaluate("document.querySelector('#alertCount').textContent = ''")
        s.page.wait_for_timeout(50)
        assert not shown(s, "#tabAlertN") and s.page.text_content("#tabAlertSr") == ""
        # Filters: closed on a phone, with a summary of what is on; opening shows the chips and the radius
        s.page.click("#tabMap")
        assert s.page.get_attribute("#filtersBtn", "aria-expanded") == "false" and not shown(s, "#modes") and not shown(s, "#radius")
        assert s.page.text_content("#filtersSum") == "Bus, Trolley, Subway, Regional Rail · 1.5 mi", s.page.text_content("#filtersSum")
        s.page.click("#filtersBtn")
        assert s.page.get_attribute("#filtersBtn", "aria-expanded") == "true" and shown(s, "#modes") and shown(s, "#radius")
        s.page.uncheck("#modes input[data-mode=train]", force=True)
        assert s.page.text_content("#filtersSum") == "Bus, Trolley, Subway · 1.5 mi"
        assert s.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "the chip row scrolls inside itself"
    with Session(root) as s:
        boot(s)
        assert s.page.get_attribute("#filtersBtn", "aria-expanded") == "true" and shown(s, "#modes"), "wide screens keep the filters open"


# ---------------------------------------------------------------- wide screens and phone landscape
def check_wide(root):
    for vp, mobile in (((1280, 800), False), ((768, 1024), False), ((844, 390), True), ((740, 360), True)):
        with Session(root, viewport=vp, mobile=mobile, touch=mobile, init_scripts=[seed(TAB_KEY, "more")]) as s:
            boot(s)
            assert not shown(s, "#tabbar"), (vp, "no tab bar")
            assert tabbar_h(s) == "0px", (vp, tabbar_h(s))
            for sels in SECTIONS.values():
                for sel in sels:
                    if sel != "#filtersBtn" or vp[0] > 760:
                        assert shown(s, sel), (vp, sel, "every section shows")
            assert s.page.evaluate("document.querySelector('#app').getBoundingClientRect().bottom") >= vp[1] - 1, vp


def test_wide_screens_and_landscape_have_no_tab_bar(root):
    check_wide(root)
    must_fail(check_wide, root, ("css/layout.css", "  #app[data-tab] #panel>[data-tab]:not([hidden]){display:block;animation:none}\n", ""))
    must_fail(check_wide, root, ("css/layout.css", "  :root{--tabbar-row:0px;--tabbar-h:0px}\n  .tabbar{display:none}\n", ""))


# ---------------------------------------------------------------- the Board tab
def check_board(root):
    with phone(root) as s:
        boot(s)
        s.page.click("#tabTrip")
        s.page.click("#tabBoard")
        s.page.wait_for_selector("#boardView:not([hidden])")
        assert s.page.evaluate("location.hash") == "#board" and state(s)["tab"] == "trip"
        assert s.page.evaluate("document.querySelector('#app').inert") is True, "the tab bar sits in #app, which the board makes inert"
        s.page.click("#bvClose")
        s.page.wait_for_selector("#boardView", state="hidden")
        s.page.wait_for_timeout(50)
        st = state(s)
        assert st["tab"] == "trip" and st["active"] == "tabBoard" and st["stored"] == "trip", st
        only(s, "trip")
        # Escape and the browser's Back leave it the same way
        s.page.click("#tabBoard")
        s.page.wait_for_selector("#boardView:not([hidden])")
        s.page.keyboard.press("Escape")
        s.page.wait_for_selector("#boardView", state="hidden")
        s.page.wait_for_timeout(50)
        assert state(s)["active"] == "tabBoard" and state(s)["tab"] == "trip"
        s.page.click("#tabBoard")
        s.page.wait_for_selector("#boardView:not([hidden])")
        s.page.go_back()
        s.page.wait_for_selector("#boardView", state="hidden")
        assert state(s)["tab"] == "trip"
    # a #board link on a phone: closing it puts focus on the Board tab (the panel's Board button is not shown there)
    with phone(root) as s:
        boot(s, "#board")
        s.page.wait_for_selector("#boardView:not([hidden])")
        s.page.click("#bvClose")
        s.page.wait_for_timeout(100)
        assert state(s)["active"] == "tabBoard" and state(s)["tab"] == "map"


def test_board_tab_opens_the_board_and_back_returns(root):
    check_board(root)
    must_fail(check_board, root, ("js/sheet.js", "if (tabsOn() && (boardFromTab || lost)) $('#tabBoard').focus({ preventScroll: true });", ""))


# ---------------------------------------------------------------- links and actions that target another tab
def check_cross(root):
    with phone(root, init_scripts=[seed(TAB_KEY, "alerts")]) as s:
        boot(s, STOP_HASH)
        s.page.wait_for_selector("#stopCard:not([hidden])")
        st = state(s)
        assert st["tab"] == "map" and st["sheet"] == "peek" and st["stored"] == "alerts", ("a stop link shows the map; not remembered", st)
    with phone(root, init_scripts=[seed("septa.places.v1", PLACES)]) as s:
        boot(s)
        s.page.click("#tabTrip")
        s.page.evaluate("location.hash = '#stop=14880&route=21'")
        s.page.wait_for_selector("#stopCard:not([hidden])")
        assert state(s)["tab"] == "map"
        s.page.click("#stopClose") if shown(s, "#stopClose") else s.page.keyboard.press("Escape")
        # Get me home (Map tab) plans in the Trip tab
        s.page.evaluate("Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition: (ok, bad) => bad({code: 1})}, configurable: true})")
        s.page.click("#btnHome")
        s.page.wait_for_function("document.activeElement && document.activeElement.id === 'tripFrom'")
        st = state(s)
        assert st["tab"] == "trip" and st["sheet"] == "open" and shown(s, "#tripFromErr"), st
        s.page.wait_for_timeout(400)
        assert not shown(s, "#tabbar"), "From has focus (the keyboard): the bar is aside"
        s.page.evaluate("document.activeElement.blur()")
        # a saved place's Go (More tab) shows it on the map
        s.page.click("#tabMore")
        s.page.locator("#places li", has_text="Work").locator("button", has_text="Go").click()
        st = state(s)
        assert st["tab"] == "map" and st["sheet"] == "peek", st
        # anything that sets a trip destination (the Indego card's Walk here) brings the planner forward
        s.page.evaluate("window.SEPTA.trip.setDestination({lat: 39.95, lng: -75.15, name: 'Dock'})")
        assert state(s)["tab"] == "trip" and shown(s, "#tripTo") and s.page.input_value("#tripTo") == "Dock"
        # the privacy link in About opens the details in More
        s.page.click("#tabMap")
        s.page.evaluate("document.querySelector('.priv-link').click()")
        assert state(s)["tab"] == "more" and s.page.evaluate("document.querySelector('#privacyDetails').open")
        # a search error opens the Map tab's sheet
        s.page.click("#tabAlerts")
        s.page.evaluate("document.querySelector('#searchForm').requestSubmit()")
        st = state(s)
        assert st["tab"] == "map" and st["sheet"] == "open" and shown(s, "#note"), st
        assert state(s)["stored"] == "alerts", "only a tab the person picks is remembered"


def test_stop_link_and_cross_tab_actions_switch_the_tab(root):
    check_cross(root)
    must_fail(check_cross, root, ("js/sheet.js", "if (/[#&]stop=/.test(location.hash)) show('map', { open: false });", ""))
    must_fail(check_cross, root, ("js/panel.js", "    sheetShow('trip', { open: true });", ""))


# ---------------------------------------------------------------- the keyboard
def check_keyboard(root):
    with phone(root) as s:
        boot(s)
        full = rect(s, "#app")["bottom"]
        assert abs(full - (844 - 56)) < 1, full
        s.page.focus("#addr")
        assert shown(s, "#tabbar"), "not before the tap's click has landed"
        s.page.wait_for_timeout(400)
        assert not shown(s, "#tabbar") and tabbar_h(s) == "0px"
        assert abs(rect(s, "#app")["bottom"] - 844) < 1, "the sheet takes the bar's room"
        # iOS: only the visual viewport shrinks; the page shrinks by the keyboard and the field stays above it
        s.page.evaluate("""() => { const vv = window.visualViewport;
            Object.defineProperty(vv, 'height', {configurable: true, get: () => window.innerHeight - 330});
            vv.dispatchEvent(new Event('resize')); }""")
        s.page.wait_for_timeout(450)
        assert rect(s, "#app")["bottom"] <= 844 - 330 + 1 and rect(s, "#addr")["bottom"] <= 844 - 330 + 1
        s.page.evaluate("() => { delete window.visualViewport.height; document.activeElement.blur(); }")
        s.page.wait_for_timeout(700)
        assert shown(s, "#tabbar") and abs(rect(s, "#app")["bottom"] - (844 - 56)) < 1
        # moving between two fields does not bring the bar back in between
        s.page.click("#tabTrip")
        s.page.focus("#tripFrom")
        s.page.evaluate("""() => { window.__flash = 0; new MutationObserver(() => { if (!document.documentElement.dataset.typing) window.__flash++; })
            .observe(document.documentElement, {attributes: true, attributeFilter: ['data-typing']}); }""")
        s.page.wait_for_timeout(400)
        s.page.focus("#tripTo")
        s.page.wait_for_timeout(400)
        assert s.page.evaluate("window.__flash") == 0 and not shown(s, "#tabbar")
        # the welcome card and toasts sit above the bar
    with phone(root, legacy_defaults=False) as s:
        boot(s)
        w, bar = rect(s, "#welcome"), rect(s, "#tabbar")
        assert shown(s, "#welcome") and w["bottom"] <= rect(s, "#panel")["top"] and w["bottom"] <= bar["top"], (w, bar)
        s.page.evaluate("window.SEPTA.util.toastOnce('t', 'Hello')")
        s.page.wait_for_selector("#toasts .toast")
        assert rect(s, "#toasts .toast")["bottom"] <= bar["top"], (rect(s, "#toasts .toast"), bar)


def test_tab_bar_steps_aside_for_the_keyboard(root):
    check_keyboard(root)
    must_fail(check_keyboard, root, ("css/layout.css", "  :root[data-typing] .tabbar{display:none}\n", ""))
    must_fail(check_keyboard, root, ("css/layout.css", "bottom:calc(8px + max(var(--tabbar-h),env(safe-area-inset-bottom,0px)))", "bottom:8px"))


def test_reduced_motion_turns_the_glide_and_fade_off(root):
    for motion, want in (("reduce", True), ("no-preference", False)):
        with phone(root, reduced_motion=motion) as s:
            boot(s)
            got = s.page.evaluate("""() => ({t: getComputedStyle(document.querySelector('#app')).transitionDuration,
                a: getComputedStyle(document.querySelector('.sec-find')).animationName})""")
            assert (got["t"] in ("0s", "") and got["a"] == "none") == want, (motion, got)


def test_tab_store_is_plain_and_documented(root):
    import pathlib
    arch = (pathlib.Path(root) / "ARCHITECTURE.md").read_text()
    assert "`septa.tab.v1`" in arch
    with phone(root) as s:
        boot(s)
        s.page.click("#tabAlerts")
        assert json.dumps(s.page.evaluate("localStorage.getItem('septa.tab.v1')")) == '"alerts"'
        # storage that throws: tabs still work, nothing is raised, no toast
        s.page.evaluate("() => { Storage.prototype.setItem = function () { throw new Error('quota'); }; }")
        s.page.click("#tabMore")
        assert state(s)["tab"] == "more" and not s.page.locator("#toasts .toast").count() and not s.console_errors
