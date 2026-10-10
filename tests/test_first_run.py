"""WP-J1 first run and everyday clarity (ARCHITECTURE.md 6 and 15.4): all buses by default (septa.defaults.v3), the star toast and the
"My routes only" pill, errors and Use my location in the phone peek, the welcome card, the one-time vehicle tip and the legend, the
"More" sheet handle, and the Barlow wordmark's contrast.

Every fast test runs its check on the real page and then again on a copy of the site with one line of the code under test broken
(`must_fail`): a check that still passes on the broken copy would not notice a regression."""
import contextlib
import json
import pathlib
import shutil
import tempfile

from harness import Session
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_v3_defaults_migration_keeps_choices",
    "test_star_toast_and_my_routes_pill",
    "test_errors_and_location_icon_in_the_phone_peek",
    "test_welcome_card_vehicle_tip_and_legend",
    "test_wordmark_font_and_more_label",
    "test_my_routes_pill_keeps_the_map_size_and_taps_exact",
    "test_stop_link_on_a_fresh_browser_still_shows_the_card_next_visit",
}

PREFS, ROUTES, PLACES, SEEN = "septa.prefs.v1", "septa.routes.v1", "septa.places.v1", "septa.seen.v1"
V2, V3 = "septa.defaults.v2", "septa.defaults.v3"
PHONE = (390, 844)
THREE = ["bus", "trolley", "subway"]
CLS = """(() => { window.__cls = 0;
 new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({type: 'layout-shift', buffered: true}); })();"""
# Which elements moved, for layouts where the chips (visible beside the map, hidden below the fold in the sheet) grow when their counts arrive.
SHIFTS = """(() => { window.__shifts = [];
 new PerformanceObserver(l => { for (const e of l.getEntries()) for (const x of e.sources) window.__shifts.push((x.node && (x.node.id || x.node.className || x.node.tagName)) + ''); }).observe({type: 'layout-shift', buffered: true}); })();"""
SITE = ("index.html", "js", "css", "data", "icons", "manifest.webmanifest")


def seed(key, value):
    raw = value if isinstance(value, str) else json.dumps(value)
    return f"try {{ if (localStorage.getItem({json.dumps(key)}) === null) localStorage.setItem({json.dumps(key)}, {json.dumps(raw)}); }} catch (e) {{}}"


@contextlib.contextmanager
def mutant(root, edits):
    """A temporary copy of the site with each (file, old, new) text edit applied; `old` must exist, so a refactor cannot silently void it."""
    root = pathlib.Path(root)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for name in SITE:
            src = root / name
            shutil.copytree(src, tmp / name) if src.is_dir() else shutil.copy(src, tmp / name)
        for rel, old, new in edits:
            f = tmp / rel
            text = f.read_text()
            assert old in text, f"mutation target not found in {rel}: {old}"
            f.write_text(text.replace(old, new, 1))
        yield tmp


def must_fail(check, root, *edits):
    with mutant(root, edits) as broken:
        try:
            check(broken)
        except (AssertionError, PlaywrightTimeout):
            return
    raise AssertionError(f"the check still passed with the code broken: {edits}")


def rect(s, sel):
    return s.page.evaluate("""(sel) => { const r = document.querySelector(sel).getBoundingClientRect();
        return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; }""", sel)


def chips_on(s):
    return s.page.evaluate("[...document.querySelectorAll('#modes input')].filter(i => i.checked).map(i => i.dataset.mode)")


def ls(s, key):
    raw = s.page.evaluate("(k) => localStorage.getItem(k)", key)
    return None if raw is None else json.loads(raw)


def overlap(a, b):
    return a["l"] < b["r"] and b["l"] < a["r"] and a["t"] < b["b"] and b["t"] < a["b"]


def boot(s):
    s.open()
    s.wait_live()


# ---------------------------------------------------------------- 1. defaults and the v3 migration
OLD_PREFS = {"center": {"lat": 39.99, "lng": -75.12, "label": "Kensington"}, "radius": 1.25,
             "filters": {"bus": False, "trolley": False, "subway": False, "train": True}}
OLD_PLACES = {"home": {"name": "Home base", "lat": 39.95, "lng": -75.16}, "list": [{"id": "p1", "name": "Work", "lat": 39.96, "lng": -75.17}]}
OLD_RULES = {"rules": []}


def check_v3(root):
    # old browser: saved filters with Trolley and Subway off and "only my routes" on
    before = "window.__before = {prefs: localStorage.getItem('septa.prefs.v1'), routes: localStorage.getItem('septa.routes.v1'), v3: localStorage.getItem('septa.defaults.v3')};"
    scripts = [seed(V2, "1"), seed(PREFS, OLD_PREFS), seed(ROUTES, {"stars": ["21", "train:Paoli/Thorndale"], "onlyMine": True}), seed(PLACES, OLD_PLACES), before]
    with Session(root, legacy_defaults=False, init_scripts=scripts) as s:
        boot(s)
        was = s.page.evaluate("window.__before")  # what was saved before the app ran: Trolley and Subway off, only my routes on, no v3 key
        assert json.loads(was["prefs"])["filters"] == OLD_PREFS["filters"] and json.loads(was["routes"])["onlyMine"] is True and was["v3"] is None, was
        assert chips_on(s) == ["trolley", "subway", "train"], chips_on(s)  # Bus stays off: the saved Bus and Regional Rail choices are kept
        prefs = ls(s, PREFS)
        assert prefs["filters"] == {"bus": False, "trolley": True, "subway": True, "train": True, "indego": False}, prefs
        assert prefs["radius"] == 1.25 and prefs["center"] == OLD_PREFS["center"], prefs
        assert ls(s, ROUTES) == {"stars": ["21", "train:Paoli/Thorndale"], "onlyMine": False}, ls(s, ROUTES)
        assert ls(s, PLACES) == OLD_PLACES
        assert ls(s, V3) in ("1", 1)
        assert s.page.inner_text("#myToggle").strip() == "Showing all routes"
        assert s.page.locator("#myPillRow").is_hidden()
        assert not s.console_errors, s.console_errors
        # it runs once: choices made afterwards survive a reload
        s.page.check("#modes input[data-mode=bus]", force=True)
        s.page.uncheck("#modes input[data-mode=subway]", force=True)
        s.page.click("#myToggle")
        s.page.reload()
        s.wait_live()
        assert chips_on(s) == ["bus", "trolley", "train"], chips_on(s)
        assert ls(s, ROUTES)["onlyMine"] is True


def check_v3_new_and_corrupt(root):
    # a brand-new browser gets the same result
    with Session(root, legacy_defaults=False) as s:
        boot(s)
        assert chips_on(s) == THREE and ls(s, V3) in ("1", 1)
        assert not s.page.locator("#myToggle").count() and s.page.evaluate("document.querySelectorAll('.veh-wrap').length") > 5
    # a corrupt prefs file, a corrupt routes file and a non-object places file still load
    scripts = [seed(V2, "1"), seed(PREFS, "{not json"), seed(ROUTES, "[1,2"), seed(PLACES, "[1,2]")]
    with Session(root, legacy_defaults=False, init_scripts=scripts) as s:
        boot(s)
        assert chips_on(s) == THREE, chips_on(s)
        assert ls(s, PREFS)["filters"] == {"bus": True, "trolley": True, "subway": True, "train": False, "indego": False}
        assert ls(s, V3) in ("1", 1)
        assert not s.console_errors, s.console_errors


def test_v3_defaults_migration_keeps_choices(root):
    check_v3(root)
    check_v3_new_and_corrupt(root)
    # mutation checks: a migration that leaves Trolley off, or leaves "only my routes" on, is noticed
    must_fail(check_v3, root, ("js/util.js", "prefs.filters.trolley = true;", "prefs.filters.trolley = prefs.filters.trolley;"))
    must_fail(check_v3, root, ("js/util.js", "routesStore.onlyMine = false;\n      saveRoutes();", "saveRoutes();"))


# ---------------------------------------------------------------- 2. star toast and the "My routes only" pill
def check_star_pill(root):
    with Session(root, viewport=PHONE, mobile=True, touch=True) as s:
        boot(s)
        total = s.markers()
        route = s.page.evaluate("""() => { const w = document.querySelector('.veh-wrap'); w.click(); return w.querySelector('.rt').textContent.trim(); }""")
        s.page.click("#starBtn")
        toast = s.page.locator("#toasts .toast")
        assert toast.count() == 1, "the first star raises one toast"
        assert toast.locator(".tmsg").inner_text() == f"Route {route} starred.", toast.inner_text()
        act = toast.locator(".tact")
        assert act.inner_text() == "Show only my routes"
        assert s.markers() == total and s.page.locator("#myPillRow").is_hidden(), "starring alone does not filter"
        assert ls(s, ROUTES)["onlyMine"] is False
        act.click()
        assert toast.count() == 0, "the action closes its toast"
        assert 0 < s.markers() < total and ls(s, ROUTES)["onlyMine"] is True
        pill = s.page.locator("#myPill")
        assert pill.is_visible() and pill.inner_text().strip() == "My routes only. Show all", pill.inner_text()
        r, panel, addr = rect(s, "#myPill"), rect(s, "#panel"), rect(s, "#addr")
        assert r["h"] >= 44 - 0.5 and r["w"] >= 44, r
        assert panel["t"] <= r["t"] and r["b"] <= panel["b"] <= 844, (r, panel)  # inside the closed sheet, in view
        assert addr["b"] <= panel["b"] and not overlap(r, addr), (r, addr)  # the search field is still in the peek
        assert s.page.get_attribute("#app", "data-sheet") == "peek"
        pill.click()
        assert s.page.get_attribute("#app", "data-sheet") == "peek", "using the pill does not open the sheet"
        assert s.markers() == total and s.page.locator("#myPillRow").is_hidden() and ls(s, ROUTES)["onlyMine"] is False
        # only the first star offers it: a second star raises no toast
        s.page.evaluate("""(r) => { [...document.querySelectorAll('.veh-wrap')].find(w => w.querySelector('.rt').textContent.trim() !== r).click(); }""", route)
        s.page.click("#starBtn")
        assert len(ls(s, ROUTES)["stars"]) == 2 and s.page.locator("#toasts .toast").count() == 0
        assert not s.console_errors, s.console_errors


def test_star_toast_and_my_routes_pill(root):
    check_star_pill(root)
    must_fail(check_star_pill, root, ("js/panel.js", "S.sheet.starTip(k);", "0;"))
    must_fail(check_star_pill, root, ("js/sheet.js", "pillRow.hidden = !on;", "pillRow.hidden = true;"))
    must_fail(check_star_pill, root, ("js/sheet.js", "util.routesStore.onlyMine = on;", "util.routesStore.onlyMine = true;"))


# ---------------------------------------------------------------- 3. errors and Use my location in the phone peek
def check_peek(root):
    with Session(root, viewport=PHONE, mobile=True, touch=True) as s:
        boot(s)
        handle = s.page.locator("#sheetHandle")
        assert handle.inner_text().strip() == "More" and handle.get_attribute("aria-expanded") == "false"
        assert s.page.get_attribute("#app", "data-sheet") == "peek"
        icon = s.page.locator("#btnLocatePeek")
        r, search, addr = rect(s, "#btnLocatePeek"), rect(s, "#btnSearch"), rect(s, "#addr")
        assert icon.get_attribute("aria-label") == "Use my location" and r["w"] >= 44 - 0.5 and r["h"] >= 44 - 0.5, r
        assert addr["r"] <= r["l"] <= r["r"] <= search["l"] and r["b"] <= 844, (addr, r, search)  # in the peek row, next to Search
        # a search error (empty submit) opens the sheet and the message is on screen
        s.page.click("#btnSearch")
        assert s.page.get_attribute("#app", "data-sheet") == "open" and handle.get_attribute("aria-expanded") == "true"
        n = rect(s, "#note")
        assert s.page.inner_text("#note") == "Type a street address or intersection first." and 0 <= n["t"] and n["b"] <= 844 and n["h"] > 0, n
        s.page.click("#sheetHandle")  # close it again, then a location error (the browser refuses)
        assert s.page.get_attribute("#app", "data-sheet") == "peek"
        s.page.evaluate("Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition: (ok, bad) => bad({code: 1})}, configurable: true})")
        icon.tap()
        s.page.wait_for_function("document.querySelector('#note').textContent.startsWith(\"Location isn't available\")")
        assert s.page.get_attribute("#app", "data-sheet") == "open"
        n = rect(s, "#note")
        assert 0 <= n["t"] and n["b"] <= 844, n
        assert s.page.locator("#btnLocatePeek").is_enabled() and s.page.locator("#btnLocate").is_enabled()
        assert not s.console_errors, s.console_errors


def check_peek_locate(root):
    # the icon runs the same handler as the Use my location button: a granted location moves the search point
    with Session(root, viewport=PHONE, mobile=True, touch=True, geolocation={"latitude": 39.9526, "longitude": -75.1652}) as s:
        boot(s)
        s.page.locator("#btnLocatePeek").tap()
        s.page.wait_for_function("document.querySelector('#note').textContent === 'Showing vehicles around your current location.'")
        assert s.page.evaluate("JSON.parse(localStorage.getItem('septa.prefs.v1')).center.label") == "Your location"
        assert s.page.get_attribute("#app", "data-sheet") == "peek", "a success note does not open the sheet"


def test_errors_and_location_icon_in_the_phone_peek(root):
    check_peek(root)
    check_peek_locate(root)
    must_fail(check_peek, root, ("js/sheet.js", "setOpen(true);\n    note.scrollIntoView", "note.scrollIntoView"))
    must_fail(check_peek_locate, root, ("js/sheet.js", "    loc.click();", "    /* nothing */"))


# ---------------------------------------------------------------- 4. welcome card, vehicle tip, legend
TIP = "Star to save this route. View stop for arrivals and alerts."


def marker_tap(s):
    s.page.evaluate("document.querySelector('.veh-wrap').click()")


def check_welcome(root):
    with Session(root, viewport=PHONE, mobile=True, touch=True, legacy_defaults=False, init_scripts=[CLS, SHIFTS]) as s:
        boot(s)
        s.page.wait_for_timeout(600)
        card = s.page.locator("#welcome")
        assert s.page.evaluate("localStorage.getItem('septa.seen.v1')") is None
        assert card.is_visible() and card.locator("p").inner_text() == "Live SEPTA vehicles near you. Tap Use my location or type an address."
        ok = s.page.locator("#welcomeOk")
        assert ok.inner_text() == "Got it" and rect(s, "#welcomeOk")["h"] >= 44 - 0.5
        c, panel = rect(s, "#welcome"), rect(s, "#panel")
        assert c["l"] >= 0 and c["r"] <= 390 and c["t"] >= 0 and c["b"] <= panel["t"] + 0.5, (c, panel)  # above the closed sheet, inside the screen
        for sel in ("#addr", "#btnSearch", "#btnLocatePeek", "#sheetHandle"):
            assert not overlap(c, rect(s, sel)), sel
        zoom = rect(s, ".leaflet-control-zoom")
        assert not overlap(c, zoom), (c, zoom)
        moved = s.page.evaluate("window.__shifts")  # the status text may re-wrap by a hair when "Live" replaces "Connecting"; nothing else moves
        assert not [m for m in moved if m in ("welcome", "welcomeOk", "addr", "btnSearch", "btnLocatePeek", "sheetHandle", "map", "stage")], moved
        assert s.page.evaluate("window.__cls") < 0.001, s.page.evaluate("window.__cls")
        assert s.page.get_attribute("#app", "data-sheet") == "peek"
        ok.tap()
        assert card.is_hidden() and ls(s, SEEN) == {"welcome": True, "vehicleTip": False}, ls(s, SEEN)
        s.page.reload()
        s.wait_live()
        assert s.page.locator("#welcome").is_hidden(), "dismissed for good"
        # the vehicle tip: once, in the card, kept while that card stays open
        marker_tap(s)
        tip = s.page.locator("#detail .tip")
        assert tip.count() == 1 and tip.inner_text() == TIP, tip.count()
        assert ls(s, SEEN) == {"welcome": True, "vehicleTip": True}
        s.tick(15000)
        assert s.page.locator("#detail .tip").count() == 1, "a refresh rebuilds the card and keeps the tip"
        s.page.click("#detailClose")
        marker_tap(s)
        assert s.page.locator("#detail .tip").count() == 0, "shown once"
        s.page.reload()
        s.wait_live()
        marker_tap(s)
        assert s.page.locator("#detail").is_visible() and s.page.locator("#detail .tip").count() == 0
        assert not s.console_errors, s.console_errors


def check_legend(root):
    with Session(root, viewport=PHONE, mobile=True, touch=True) as s:
        boot(s)
        s.page.click("#sheetHandle")  # the legend is in the panel: seen when the sheet is open
        lg = s.page.locator("#legend")
        lg.scroll_into_view_if_needed()
        assert lg.is_visible() and lg.inner_text() == "Letter on a bus is its direction. Faded marker is an old position."
        r = rect(s, "#legend")
        assert 0 <= r["t"] and r["b"] <= 844 and rect(s, "#panel")["b"] >= r["b"], r


def check_welcome_rules(root):
    # Escape dismisses and remembers; a #stop= share link never shows the card; a returning browser (saved prefs) never sees it
    with Session(root, legacy_defaults=False) as s:
        boot(s)
        assert s.page.locator("#welcome").is_visible()
        c, panel = rect(s, "#welcome"), rect(s, "#panel")
        assert panel["l"] <= c["l"] and c["r"] <= panel["r"], (c, panel)  # wide screens: in the panel, off the map
        s.page.keyboard.press("Shift")
        assert s.page.locator("#welcome").is_visible(), "only Escape dismisses"
        s.page.keyboard.press("Escape")
        assert s.page.locator("#welcome").is_hidden() and ls(s, SEEN)["welcome"] is True
        s.page.reload()
        s.wait_live()
        assert s.page.locator("#welcome").is_hidden()
    with Session(root, legacy_defaults=False, init_scripts=[seed(PREFS, {"radius": 0.5})]) as s:
        boot(s)
        assert s.page.locator("#welcome").is_hidden(), "returning visitor"
    with Session(root, legacy_defaults=False) as s:
        s.open(hash_="#stop=2275&route=21")
        s.wait_live()
        assert s.page.locator("#welcome").is_hidden(), "share link"


def test_welcome_card_vehicle_tip_and_legend(root):
    check_welcome(root)
    check_legend(root)
    check_welcome_rules(root)
    must_fail(check_welcome, root, ("js/sheet.js", "if (util.firstVisit && !util.seen.welcome) welcome.hidden = false;", "welcome.hidden = true;"))
    must_fail(check_welcome_rules, root, ("js/util.js", "!/[#&]stop=/.test(location.hash)", "true"))
    must_fail(check_welcome_rules, root, ("js/sheet.js", "e.key !== 'Escape' || welcome.hidden", "welcome.hidden"))
    must_fail(check_welcome_rules, root, ("js/util.js", "var firstVisit = fresh && ", "var firstVisit = "))
    must_fail(check_welcome, root, ("js/sheet.js", "util.markSeen('welcome');", "0;"))
    must_fail(check_welcome, root, ("js/map.js", "if (!seen.vehicleTip || tipFor === state.selected) {", "if (false) {"))
    must_fail(check_welcome, root, ("js/map.js", "markSeen('vehicleTip');", "0;"))


# ---------------------------------------------------------------- 5. wordmark font and the "More" handle
def check_brand_and_handle(root):
    with Session(root, viewport=PHONE, mobile=True, touch=True) as s:
        boot(s)
        got = s.page.evaluate("""() => { const c = getComputedStyle(document.querySelector('.brand h1'));
            return {family: c.fontFamily, weight: c.fontWeight, ls: c.letterSpacing, size: c.fontSize,
                    fonts: [...document.querySelectorAll('link[href*="fonts.googleapis"]')].map(l => decodeURIComponent(l.href.replace(/\+/g, " "))).join(' ')}; }""")
        assert got["family"].split(",")[0].strip("\"' ") == "Barlow Condensed" and got["weight"] == "700", got
        assert got["ls"].endswith("px") and 0 < float(got["ls"][:-2]) <= 1, got  # about .02em of 22 px on a phone
        assert "Barlow Condensed:wght@600;700" in got["fonts"], got  # the 700 weight is loaded by the page
        assert s.page.inner_text("#sheetHandle").strip() == "More"
        assert "Controls" not in s.page.inner_text("#sheetHandle")


def test_wordmark_font_and_more_label(root):
    check_brand_and_handle(root)
    must_fail(check_brand_and_handle, root, ("css/base.css", "letter-spacing:.02em;text-transform:none;color:var(--accent)}", "letter-spacing:normal;text-transform:none;color:var(--accent)}"))
    must_fail(check_brand_and_handle, root, ("css/base.css", '--f-title:"Barlow Condensed",', '--f-title:"Helvetica Neue",'))
    must_fail(check_brand_and_handle, root, ("index.html", '<span class="sheet-label">More</span>', '<span class="sheet-label">Controls</span>'))
    must_fail(check_brand_and_handle, root, ("index.html", "Barlow+Condensed:wght@600;700", "Barlow+Condensed:wght@600"))


# ---------------------------------------------------------------- full-only
def test_welcome_card_geometry_across_layouts(root):
    """The card never covers the search field, the sheet handle, the zoom buttons or the map's content area on wide screens, and never
    leaves the screen: at 320, 360 and 390 (sheet), 760 (the last sheet width), 768 and 1280 (side panel) and phone landscape; on a phone it steps aside for
    the vehicle card and for the open sheet."""
    for vp in ((320, 640), (360, 740), (390, 844), (414, 896), (760, 900), (768, 1024), (1280, 800), (844, 390)):
        phone = vp[0] <= 760 or vp[1] <= 500
        with Session(root, viewport=vp, mobile=phone, touch=phone, legacy_defaults=False, init_scripts=[CLS, SHIFTS]) as s:
            boot(s)
            s.page.wait_for_timeout(300)
            c, panel = rect(s, "#welcome"), rect(s, "#panel")
            assert c["h"] > 0 and c["l"] >= 0 and c["r"] <= vp[0] and c["t"] >= 0 and c["b"] <= vp[1], (vp, c)
            assert not overlap(c, rect(s, ".leaflet-control-zoom")), vp
            assert not overlap(c, rect(s, ".leaflet-control-attribution")), vp
            assert not overlap(c, rect(s, "#addr")), vp
            if vp[0] > 760 or vp[1] <= 500:
                assert panel["l"] <= c["l"] and c["r"] <= panel["r"], (vp, c, panel)  # in the panel
            moved = s.page.evaluate("window.__shifts")
            assert not [m for m in moved if m in ("map", "stage", "addr", "btnSearch", "btnLocatePeek", "sheetHandle") or "leaflet" in m], (vp, moved)
            assert s.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), vp
            if vp[0] <= 760 and vp[1] > 500:
                marker_tap(s)
                assert s.page.locator("#welcome").is_hidden() and s.page.locator("#detail").is_visible(), vp
                s.page.click("#detailClose")
                assert s.page.locator("#welcome").is_visible(), vp
                s.page.click("#sheetHandle")
                assert s.page.locator("#welcome").is_hidden(), vp


def test_peek_row_fits_without_wrapping_at_small_widths(root):
    """Wordmark, status line, search field, Search and the location button all sit in the closed sheet at 320 and 360 px, each on one line."""
    for vp in ((320, 640), (360, 740)):
        with Session(root, viewport=vp, mobile=True, touch=True) as s:
            boot(s)
            panel = rect(s, "#panel")
            for sel in ("#sheetHandle", ".brand h1", "#statusText", "#addr", "#btnSearch", "#btnLocatePeek"):
                r = rect(s, sel)
                assert r["h"] > 0 and r["l"] >= 0 and r["r"] <= vp[0] and r["b"] <= panel["b"] + 0.5, (vp, sel, r)
            row = [rect(s, x) for x in ("#addr", "#btnLocatePeek", "#btnSearch")]
            assert max(r["t"] for r in row) - min(r["t"] for r in row) < 2 and row[0]["r"] <= row[1]["l"] and row[1]["r"] <= row[2]["l"], (vp, row)
            assert rect(s, "#btnSearch")["h"] < 60 and s.page.evaluate("document.querySelector('#btnSearch').getClientRects().length") == 1
            h1 = s.page.evaluate("(() => { const e = document.querySelector('.brand h1'); return e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight); })()")
            assert h1 <= 1.05, (vp, "wordmark wraps")


def test_saved_filter_pill_is_there_at_load_without_layout_shift(root):
    routes = {"stars": ["21", "48"], "onlyMine": True}
    with Session(root, viewport=PHONE, mobile=True, touch=True, init_scripts=[CLS, SHIFTS, seed(ROUTES, routes)]) as s:
        boot(s)
        s.page.wait_for_timeout(500)
        assert s.page.locator("#myPill").is_visible()
        # the pill is in place from the first paint: nothing it or the search row sits in moves (the status text may re-wrap by a hair when "Live" replaces "Connecting")
        moved = s.page.evaluate("window.__shifts")
        assert not [m for m in moved if m in ("myPill", "myPillRow", "addr", "btnSearch", "btnLocatePeek", "searchForm")], moved
        assert s.page.evaluate("window.__cls") < 0.001, s.page.evaluate("window.__cls")
        assert rect(s, "#addr")["b"] <= rect(s, "#panel")["b"] <= 844


def test_seen_store_is_validated(root):
    for junk in ("[1]", '"x"', '{"welcome":"yes","vehicleTip":1}', "{not json", "null"):
        with Session(root, legacy_defaults=False, init_scripts=[seed(SEEN, junk)]) as s:
            boot(s)
            assert s.page.locator("#welcome").is_visible(), junk
            s.page.click("#welcomeOk")
            assert ls(s, SEEN) == {"welcome": True, "vehicleTip": False}, junk
            assert not s.console_errors, (junk, s.console_errors)


def test_defaults_show_all_buses_and_routes_store_defaults_off(root):
    for junk, expect in (("not json", False), ('{"stars":["21"]}', False), ('{"stars":["21"],"onlyMine":"yes"}', False), ('{"stars":["21"],"onlyMine":true}', True)):
        with Session(root, legacy_defaults=False, init_scripts=[seed(V2, "1"), seed(V3, "1"), seed(ROUTES, junk)]) as s:
            boot(s)
            assert s.page.locator("#myPillRow").is_visible() == expect, junk
            assert (s.page.locator("#myToggle").count() == 0) == (junk == "not json"), junk


def test_wordmark_contrast_in_both_themes(root):
    def lum(rgb):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (ch(float(x)) for x in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def parse(css):
        return [float(x) for x in css[css.index("(") + 1:css.index(")")].replace("/", ",").split(",")[:3]]

    for scheme in ("light", "dark"):
        with Session(root, color_scheme=scheme) as s:
            boot(s)
            got = s.page.evaluate("""() => { const h = getComputedStyle(document.querySelector('.brand h1')),
                p = getComputedStyle(document.querySelector('#panel'));
                return {h1: h.color, bg: p.backgroundColor, tag: document.querySelector('.brand h1').tagName}; }""")
            assert got["tag"] == "H1"
            bg = lum(parse(got["bg"]))
            for k in ("h1",):
                fg = lum(parse(got[k]))
                ratio = (max(fg, bg) + 0.05) / (min(fg, bg) + 0.05)
                assert ratio >= 4.5, (scheme, k, ratio, got)


# ---------------------------------------------------------------- 6. fix round after the independent review
HOOK = "window.__SEPTA_TEST__ = true"


def map_geometry(s):
    return s.page.evaluate("""() => { const m = window.__SEPTA_TEST__.tripMap, b = m.getContainer(), z = m.getSize(), p = m.latLngToContainerPoint(m.getCenter()), c = m.getCenter();
        return {box: [b.clientWidth, b.clientHeight], size: [z.x, z.y], mid: [p.x, p.y], lat: c.lat, lng: c.lng, zoom: m.getZoom()}; }""")


def check_pill_resizes_the_map(root):
    # in the closed sheet the My routes pill row changes the map's height by 34 px: Leaflet must follow, keeping the view and the tap mapping
    with Session(root, viewport=PHONE, mobile=True, touch=True, init_scripts=[HOOK]) as s:
        boot(s)
        s.page.evaluate("document.querySelector('.veh-wrap').click()")
        s.page.click("#starBtn")
        s.page.click("#detailClose")
        s.settle()
        start = map_geometry(s)
        assert start["box"] == start["size"], start

        def verify(what, was):
            s.settle()
            g = map_geometry(s)
            assert g["box"] == g["size"], (what, g)
            assert abs(g["mid"][0] - g["box"][0] / 2) <= 1 and abs(g["mid"][1] - g["box"][1] / 2) <= 1, (what, g)
            assert abs(g["lat"] - was["lat"]) < 1e-9 and abs(g["lng"] - was["lng"]) < 1e-9 and g["zoom"] == was["zoom"], (what, g, was)
            # a tap in the middle of the visible map lands on the map's centre (markers are switched off for the tap)
            s.page.evaluate("document.querySelector('.leaflet-marker-pane').style.pointerEvents = 'none'; window.__ll = null; window.__SEPTA_TEST__.tripMap.once('click', e => { window.__ll = e.latlng; });")
            box = rect(s, "#map")
            s.page.mouse.click(box["l"] + box["w"] / 2, box["t"] + box["h"] / 2)
            ll = s.page.evaluate("window.__ll")
            assert ll and abs(ll["lat"] - g["lat"]) < 2e-5 and abs(ll["lng"] - g["lng"]) < 2e-5, (what, ll, g)
            return g

        s.page.locator("#toasts .tact").click()
        assert s.page.locator("#myPillRow").is_visible() and s.page.get_attribute("#app", "data-sheet") == "peek"
        shrunk = verify("pill shown by the toast", start)
        assert shrunk["box"][1] == start["box"][1] - 34, (start, shrunk)
        s.page.click("#myPill")
        assert s.page.locator("#myPillRow").is_hidden()
        verify("pill hidden by the pill", shrunk)
        assert not s.console_errors, s.console_errors


def test_my_routes_pill_keeps_the_map_size_and_taps_exact(root):
    check_pill_resizes_the_map(root)
    must_fail(check_pill_resizes_the_map, root, ("js/sheet.js", "resizeMap(); /* in peek the row changes the map row's height by --pillrow */", ""))


def check_escape_rules(root):
    # Escape closes the vehicle card and leaves the welcome card alone; with focus on "Got it" it dismisses and focus moves to the search field
    with Session(root, legacy_defaults=False) as s:
        boot(s)
        marker_tap(s)
        assert s.page.locator("#detail").is_visible() and s.page.locator("#welcome").is_visible()
        s.page.keyboard.press("Escape")
        assert s.page.locator("#detail").is_hidden()
        assert s.page.locator("#welcome").is_visible() and not (ls(s, SEEN) or {}).get("welcome"), "Escape that closed the vehicle card must not dismiss the welcome card"
        s.page.focus("#welcomeOk")
        s.page.keyboard.press("Escape")
        assert s.page.locator("#welcome").is_hidden() and ls(s, SEEN)["welcome"] is True
        assert s.page.evaluate("document.activeElement.id") == "addr", s.page.evaluate("document.activeElement.id")
    with Session(root, viewport=PHONE, mobile=True, touch=True, legacy_defaults=False) as s:
        boot(s)
        marker_tap(s)
        assert s.page.locator("#welcome").is_hidden(), "covered on a phone while the vehicle card shows"
        s.page.keyboard.press("Escape")
        assert s.page.locator("#detail").is_hidden() and s.page.locator("#welcome").is_visible() and not (ls(s, SEEN) or {}).get("welcome")
        s.page.click("#sheetHandle")  # the open sheet hides the card; Escape with nothing focused must not dismiss what nobody sees
        s.page.evaluate("document.activeElement.blur()")
        assert s.page.locator("#welcome").is_hidden()
        s.page.keyboard.press("Escape")
        assert not (ls(s, SEEN) or {}).get("welcome"), "dismissed a card that was not on screen"
    with Session(root, legacy_defaults=False) as s:
        boot(s)
        s.page.click("#welcomeOk")
        assert s.page.evaluate("document.activeElement.id") == "addr", "after Got it focus goes to the search field"


def test_escape_dismisses_the_welcome_card_only_when_it_is_the_target(root):
    check_escape_rules(root)
    must_fail(check_escape_rules, root, ("js/sheet.js", "#detail:not([hidden]), ", ""),
              ("js/sheet.js", "    true\n  );\n  syncPill()", "    false\n  );\n  syncPill()"))
    must_fail(check_escape_rules, root, ("js/sheet.js", "welcome.getClientRects().length &&", ""))
    must_fail(check_escape_rules, root, ("js/sheet.js", "if (inside) $('#addr').focus();", ""))


def check_stop_link_first(root):
    # a fresh browser opened from a #stop= link keeps the same prefs as before, writes only the migration flags, and still sees the card next visit
    with Session(root, legacy_defaults=False) as s:
        s.open(hash_="#stop=2275&route=21")
        s.wait_live()
        assert s.page.locator("#welcome").is_hidden(), "share link"
        assert s.page.evaluate("localStorage.getItem('septa.prefs.v1')") is None, "a share link must not make the browser look like a returning one"
        assert s.page.evaluate("[localStorage.getItem('septa.defaults.v2'), localStorage.getItem('septa.defaults.v3')]") == ['"1"', '"1"']
        assert chips_on(s) == THREE and s.page.input_value("#radius") == "0.5", (chips_on(s), s.page.input_value("#radius"))
        s.page.evaluate("history.replaceState(null, '', location.pathname)")
        s.page.reload()
        s.wait_live()
        assert s.page.locator("#welcome").is_visible(), "the next plain visit shows the card"
        assert chips_on(s) == THREE and s.page.input_value("#radius") == "0.5"
        s.page.click("#welcomeOk")
        s.page.reload()
        s.wait_live()
        assert s.page.locator("#welcome").is_hidden(), "and only once"
        assert not s.console_errors, s.console_errors


def test_stop_link_on_a_fresh_browser_still_shows_the_card_next_visit(root):
    check_stop_link_first(root)
    must_fail(check_stop_link_first, root,
              ("js/util.js", "return localStorage.getItem('septa.prefs.v1') === null;", "return localStorage.getItem('septa.prefs.v1') === null && !/[#&]stop=/.test(location.hash);"))


def check_welcome_phone_extras(root):
    # 390 px: clear of the map attribution, hidden by the Indego card and by the on-screen keyboard (a focused panel field)
    with Session(root, viewport=PHONE, mobile=True, touch=True, legacy_defaults=False) as s:
        boot(s)
        c = rect(s, "#welcome")
        assert not overlap(c, rect(s, ".leaflet-control-attribution")), (c, rect(s, ".leaflet-control-attribution"))
        assert not overlap(c, rect(s, ".leaflet-control-zoom"))
        assert abs((rect(s, "#panel")["t"] - c["b"]) - 24) <= 1, (c, rect(s, "#panel"))
        s.page.evaluate("document.querySelector('#indegoCard').hidden = false")
        assert s.page.locator("#welcome").is_hidden(), "Indego card"
        s.page.evaluate("document.querySelector('#indegoCard').hidden = true")
        assert s.page.locator("#welcome").is_visible()
        s.page.focus("#addr")
        assert s.page.locator("#welcome").is_hidden(), "a field in the panel is focused (keyboard)"
        s.page.evaluate("document.activeElement.blur()")
        assert s.page.locator("#welcome").is_visible()


def test_welcome_card_on_a_phone_clears_attribution_indego_card_and_keyboard(root):
    check_welcome_phone_extras(root)
    must_fail(check_welcome_phone_extras, root, ("css/panel.css", "bottom:calc(var(--peek) + 24px)", "bottom:calc(var(--peek) + 8px)"))
    must_fail(check_welcome_phone_extras, root, ("css/panel.css", "#app:has(#indegoCard:not([hidden])) #welcome,", ""))
    must_fail(check_welcome_phone_extras, root, ("css/panel.css", "#app:has(#panel :is(input,select,textarea):focus) #welcome", "#app:has(#nonesuch) #welcome"))


def check_toast_wraps(root):
    for w in (320, 360):
        with Session(root, viewport=(w, 640), mobile=True, touch=True) as s:
            boot(s)
            s.page.evaluate("document.querySelector('.veh-wrap').click()")
            s.page.click("#starBtn")
            msg, toast, act = rect(s, "#toasts .tmsg"), rect(s, "#toasts .toast"), rect(s, "#toasts .tact")
            assert msg["w"] >= 150, (w, msg)
            assert act["t"] >= msg["b"] - 0.5, (w, "the buttons sit on their own row", msg, act)
            assert toast["l"] >= 0 and toast["r"] <= w and toast["b"] <= 640, (w, toast)
            assert s.page.locator("#toasts .tact").inner_text() == "Show only my routes"


def test_star_toast_gives_its_message_room_on_narrow_phones(root):
    check_toast_wraps(root)
    must_fail(check_toast_wraps, root, ("css/alerts.css", ".toast{flex-wrap:wrap;justify-content:flex-end}", ".toast{justify-content:flex-end}"))
