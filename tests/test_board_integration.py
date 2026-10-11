"""My stops board, logic and view together (no fakes): pin a stop from its card, open the board, and check that the row on screen
shows the same numbers S.board.rows() computes from the live mock feed, that they tick, and that removing the pin empties the board."""
import json
import re

from harness import Session
from test_first_run import must_fail, seed
from test_stop_board import SID, SROUTE, setup_moving, step
from test_board_logic import KEY, PLACES, SETUP2, T0, js, pin

FAST = {"test_pin_a_stop_and_see_it_on_the_board"}
HASH = f"#stop={SID}&route={SROUTE}"


def check_pin_and_see_it(root):
    with Session(root, viewport=(1133, 744), init_scripts=[seed("septa.places.v1", PLACES)]) as s:
        setup_moving(s)
        s.open(hash_=HASH)
        s.wait_live()
        s.settle()
        for _ in range(3):
            step(s, "3678", 120)
        s.page.wait_for_selector("#pinBoard")
        s.page.click("#pinBoard")
        s.page.locator("#pinChoose button").first.click()  # Home
        assert s.page.inner_text("#stopLive") == "Pinned to board."
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector("#boardView", state="visible")
        s.settle()
        rows = s.page.locator("#boardView li")
        assert rows.count() == 1, rows.count()
        txt = rows.first.inner_text()
        assert "21" in txt and "Home" in txt and re.search(r"Bus in \(estimate\)\s*\d+\s*min|about\s*\d+", txt, re.I), txt
        assert re.search(r"LATER|SOON|LEAVE NOW|MISSED", txt), txt
        r = js(s, "window.SEPTA.board.rows(Date.now())[0]")
        eta = r["arrivals"][0]["etaMin"]
        shown = int(re.search(r"(\d+)\s*min", txt.split("Bus in", 1)[-1]).group(1)) if "Bus in" in txt else None
        assert shown is None or abs(shown - eta) <= 1.5, (shown, eta, txt)
        # settings: Remove empties the board and shows the empty state
        s.page.click("#boardView button:has-text('Settings')")
        s.page.locator("#boardView button:has-text('Remove')").first.click()
        assert js(s, "window.SEPTA.board.pins().length") == 0
        s.page.wait_for_selector("#boardView :text('Nothing on your board yet')", timeout=5000)
        assert not s.console_errors, s.console_errors


def test_pin_a_stop_and_see_it_on_the_board(root):
    check_pin_and_see_it(root)
    must_fail(check_pin_and_see_it, root, ("js/board.js", "S.board.rows = rows;", "S.board.rows = function () { return []; };"))


# ---------------------------------------------------------------------------------------------------------------------------
# The three tests below are written against the FIX CONTRACT (tests fix brief, review items 6, 7 and 10) and read the REAL view
# (js/boardview.js from the view lane): "Place removed" for a deleted place, "Bus nearby" for buses with no measured time yet and
# "45+" for an arrival more than 45 minutes away. They fail until the view lane is merged; the architect runs them after the merge.
# They are deliberately not in FAST.
# ---------------------------------------------------------------------------------------------------------------------------
def board_text(s):
    s.page.evaluate("location.hash = '#board'")
    s.page.wait_for_selector("#boardView", state="visible")
    s.settle()
    return s.page.locator("#boardView li").first.inner_text()


def check_removed_place_on_screen(root):
    stored = json.dumps({"pins": [pin(0, placeId="gone", stopName="Market St & 15th", walkMin=None)], "bufferMin": 2, "bad": False})
    with Session(root, viewport=(1133, 744), init_scripts=[seed(KEY, stored)]) as s:
        s.open()
        s.wait_live()
        s.settle()
        txt = board_text(s)
        assert "Place removed" in txt and "5 min" in txt, txt
        assert js(s, "window.SEPTA.board.pins().length") == 1, "the pin is not dropped"
        assert not s.console_errors, s.console_errors


def check_far_and_pending_on_screen(root):
    two = json.dumps({"pins": [pin(0, walkMin=3), pin(1, stopId="101", walkMin=3)], "bufferMin": 2, "bad": False})
    with Session(root, viewport=(1133, 744), init_scripts=[seed(KEY, two)]) as s:
        s.open()
        s.wait_live()
        s.settle()
        # pin 0: one bus 52 minutes away; pin 1: two buses heading here with no measured time
        js(s, """() => { const S = window.SEPTA;
            S.stops.boardRows = (stop) => ({ a: (stop.id === '100' ? [{ key: 'far', min: 52 }] : [{ key: 'x', min: null }, { key: 'y', min: null }])
                .map(x => ({ v: { key: x.key }, d: 0.1, eta: { min: x.min, rough: false } })), b: [] });
            S.board.refresh(); }""")
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector("#boardView", state="visible")
        s.settle()
        rows = s.page.locator("#boardView li")
        assert rows.count() == 2, rows.count()
        far, pending = rows.nth(0).inner_text(), rows.nth(1).inner_text()
        assert "45+" in far and not re.search(r"LEAVE NOW|SOON|LATER|MISSED", far), far
        assert "Bus nearby" in pending and "time not known yet" in pending, pending
        assert not s.console_errors, s.console_errors


def test_removed_place_is_shown_on_the_board(root):
    check_removed_place_on_screen(root)
    must_fail(check_removed_place_on_screen, root, ("js/board.js", "note: pin.placeId && !pl ? 'place-removed' : ''", "note: ''"))


def test_far_and_pending_arrivals_are_shown_on_the_board(root):
    check_far_and_pending_on_screen(root)
    must_fail(check_far_and_pending_on_screen, root, ("js/board.js", "pending++;", ""))
    must_fail(check_far_and_pending_on_screen, root, ("js/board.js", "if (left > FAR_MIN) a.far = true;", ""))


FAST.add("test_panel_renders_before_the_sheet_module_has_loaded")


def check_panel_without_sheet(root):
    # a page opened straight on #board can refresh before js/sheet.js has run: the panel must not throw
    with Session(root) as s:
        s.open()
        s.wait_live()
        s.page.evaluate("window.__sp = window.SEPTA.sheet.syncPill; delete window.SEPTA.sheet.syncPill")
        err = s.page.evaluate("(() => { try { window.SEPTA.panel.renderMyRoutes(); return ''; } catch (e) { return String(e); } })()")
        s.page.evaluate("window.SEPTA.sheet.syncPill = window.__sp")
        assert err == "", err


def test_panel_renders_before_the_sheet_module_has_loaded(root):
    check_panel_without_sheet(root)
    must_fail(check_panel_without_sheet, root, ("js/panel.js", "if (S.sheet.syncPill)\n      S.sheet.syncPill();", "S.sheet.syncPill();"))


FAST.add("test_the_board_path_opens_the_board")


def check_board_path(root):
    with Session(root, viewport=(1133, 744)) as s:
        s.open(path="board/")
        s.page.wait_for_url("**/index.html#board" if False else "**/#board", timeout=10000)
        s.page.wait_for_selector("#boardView", state="visible", timeout=10000)
        assert s.page.url.endswith("/#board"), s.page.url


def test_the_board_path_opens_the_board(root):
    check_board_path(root)
    must_fail(check_board_path, root, ("board/index.html", "location.replace('../#board');", ""),
              ("board/index.html", '<meta http-equiv="refresh" content="0; url=../#board">', ""))


# ---------------------------------------------------------------------------------------------------------------------------
# "Add a bus stop" (js/boardadd.js): search a street, intersection, address, stop name or location, pick a stop, see it on the board.
# Hermetic: the bus network is the small one from test_nearby, Nominatim comes from extra_routes, Photon returns nothing.
# ---------------------------------------------------------------------------------------------------------------------------
import copy

from harness import photon_feature as PF
from test_nearby import NET as ADD_NET, SEARCH as ADD_AT, GEO as ADD_GEO
from test_trip_ui import HOOK, SEED_PREFS, geo

FAST.update({"test_add_a_bus_stop_by_name_then_see_it_on_the_board", "test_add_a_bus_stop_by_address_and_location"})
Q = "#bvStopQ"
ADD = "#bvAdd"
JSON_EMPTY = (200, "application/json", "[]")


def add_session(root, extra=(), routes=None, **kw):
    r = {"q=100": geo(ADD_AT["lat"], ADD_AT["lng"], "100 Test Ave"), "q=Nowhere": JSON_EMPTY, "q=Newark": geo(40.7357, -74.1724, "Newark")}
    r.update(routes or {})
    return Session(root, viewport=kw.pop("viewport", (1133, 744)), extra_routes=r, init_scripts=[HOOK, SEED_PREFS] + list(extra), **kw)


def add_open(s, net=ADD_NET, hash_="#board", empty=True):
    s.mocks.network = copy.deepcopy(net)
    s.open(hash_=hash_)
    s.wait_live()
    s.page.wait_for_selector("#boardView", state="visible")
    if not empty:  # a board with pins: the way in is the Settings sheet
        s.page.click("#bvSet")
        s.page.click("[data-fk=addstop]")
    else:
        s.page.click("#bvAddStop")
    s.page.wait_for_selector(ADD, state="visible")


def look(s, q):
    s.page.fill(Q, q)
    s.page.click(f"{ADD} button[type=submit]")


def picks_(s):
    return s.page.evaluate(f"""() => [...document.querySelectorAll('{ADD} .bv-pick')].map(b => ({{label: b.getAttribute('aria-label'), text: b.innerText.replace(/\\s+/g, ' ').trim(),
        off: b.disabled, h: b.getBoundingClientRect().height}}))""")


def wait_picks(s, n=None):
    s.page.wait_for_function(f"document.querySelectorAll('{ADD} .bv-pick').length {'> 0' if n is None else '=== ' + str(n)}", timeout=8000)
    return picks_(s)


def active(s):
    return s.page.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.dataset.fk || document.activeElement.textContent.trim())")


def msg(s):
    return s.page.inner_text("#bvAddMsg").strip()


def stored_pins(s):
    return js(s, "window.SEPTA.board.pins()")


def check_add_by_name(root):
    with add_session(root) as s:
        add_open(s)
        assert s.mocks.network_hits == 0, "the stop list is fetched by a search, not by opening the sheet"
        look(s, "walnut and 11th street")  # "and" and "street" say nothing about which stop
        got = wait_picks(s, 3)
        assert [g["label"] for g in got] == [f"Route {r} toward {h} at Walnut St & 11th St" for r, h in (("12", "West"), ("21", "East"), ("42", "North"))], got
        assert all(g["h"] >= 44 for g in got) and "1 bus stop with a name like that" in msg(s), (got, msg(s))
        # a typed route number narrows to that route, before or after the street words
        for q in ("21 walnut 11th", "walnut 11th 21"):
            look(s, q)
            s.page.wait_for_function("document.querySelectorAll('#bvAdd .bv-pick').length === 1")
            assert [g["label"] for g in wait_picks(s, 1)] == ["Route 21 toward East at Walnut St & 11th St"], q
        look(s, "walnut and 11th street")
        got = wait_picks(s, 3)
        s.page.locator(f"{ADD} .bv-pick").nth(1).click()  # no saved places: pinned at once
        s.page.wait_for_selector(f"{ADD} :text('Added Route 21 at Walnut St & 11th St to your board.')")
        s.tick(200)  # the live region is written 50 ms after it is cleared
        assert "Added Route 21 at Walnut St & 11th St" in s.page.inner_text("#bvLive")
        pins = stored_pins(s)
        assert len(pins) == 1 and (pins[0]["route"], pins[0]["stopId"], pins[0]["placeId"], pins[0]["walkMin"]) == ("21", "14885", None, None), pins
        assert active(s) == "Show my board", active(s)
        s.page.keyboard.press("Enter")
        assert s.page.locator(ADD).is_hidden()
        li = s.page.locator("#bvList > li")
        assert li.count() == 1 and "21" in li.first.inner_text() and "Walnut St & 11th St" in li.first.inner_text()
        assert s.page.locator("#bvEmpty").is_hidden() and active(s) == "bvSet", active(s)
        # reachable from Settings now; the stop just added is marked and cannot be added twice
        s.page.click("#bvSet")
        s.page.click("[data-fk=addstop]")
        look(s, "walnut 11th")
        got = wait_picks(s, 3)
        assert [g["off"] for g in got] == [False, True, False] and "(on board)" in got[1]["text"] and "already on the board" in got[1]["label"], got
        s.page.keyboard.press("Escape")
        assert "Route 21 at Walnut St & 11th St" in s.page.inner_text("#bvSettings") and active(s) == "addstop"
        assert not s.console_errors, s.console_errors


def test_add_a_bus_stop_by_name_then_see_it_on_the_board(root):
    check_add_by_name(root)
    must_fail(check_add_by_name, root, ("js/boardadd.js", "return h.indexOf(w) === 0;", "return false;"))
    must_fail(check_add_by_name, root, ("js/boardadd.js", "if (rows.length) return rows;", ""))
    must_fail(check_add_by_name, root, ("js/boardadd.js", "return b.hasPin(r.route, r.id, o.placeId);", "return false;"))
    must_fail(check_add_by_name, root, ("js/boardadd.js", "nodes.doneShow.focus();", ""))


def check_add_by_address_and_location(root):
    with add_session(root, geolocation=ADD_GEO) as s:
        add_open(s)
        look(s, "100 Test Ave")
        got = wait_picks(s, 7)
        assert got[0]["label"] == "Route 12 toward West at Walnut St & 11th St, 250 ft", got[0]
        assert [g["label"].split(" at ")[1].split(",")[0] for g in got] == ["Walnut St & 11th St"] * 3 + ["Walnut St & 12th St"] * 2 + ["Spruce St & 11th St", "Pine St & 11th St"], got
        assert "4 bus stops near 100 Test Ave" in msg(s) and s.mocks.network_hits == 1, msg(s)
        # a stop where the route ends is not offered (nobody boards there); far stops stay out
        assert not any("13th" in g["label"] or "Far St" in g["label"] for g in got)
        s.page.click(f"{ADD} :text('Use my location')")
        s.page.wait_for_function("document.querySelector('#bvAddMsg').textContent.includes('your location')")
        got = wait_picks(s)
        assert "bus stops near your location" in msg(s) and s.mocks.network_hits == 1 and got, (msg(s), got[:1])
        look(s, "Nowhere")
        s.page.wait_for_function("document.querySelector('#bvAddMsg').textContent.startsWith('No match')")
        assert picks_(s) == [] and "cross street or a ZIP" in msg(s)
        look(s, "Newark")
        s.page.wait_for_function("document.querySelector('#bvAddMsg').textContent.startsWith('No bus stops')")
        assert picks_(s) == [] and "within a mile" in msg(s)
        look(s, "")
        assert msg(s).startswith("Type a street")
        assert not s.console_errors, s.console_errors
    # no location here: the button is not offered; a refusal says so
    with add_session(root, extra=["Object.defineProperty(navigator, 'geolocation', {value: undefined, configurable: true})"]) as s:
        add_open(s)
        assert s.page.locator(f"{ADD} :text('Use my location')").count() == 0
    with add_session(root, extra=["Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition: (ok, bad) => bad({code: 1})}, configurable: true})"]) as s:
        add_open(s)
        s.page.click(f"{ADD} :text('Use my location')")
        s.page.wait_for_function("document.querySelector('#bvAddMsg').textContent.startsWith('Location')")
        assert "Type an address instead" in msg(s) and picks_(s) == []


def test_add_a_bus_stop_by_address_and_location(root):
    check_add_by_address_and_location(root)
    must_fail(check_add_by_address_and_location, root, ("js/boardadd.js", "if (i === p.stops.length - 1 && p.stops.length > 1) return;", ""))
    must_fail(check_add_by_address_and_location, root, ("js/boardadd.js", "NEAR_RADII_M = [", "NEAR_RADII_M = [1], UNUSED_ = ["))
    must_fail(check_add_by_address_and_location, root, ("js/boardadd.js", "if (!rows.length) return note(", "if (false) return note("))
    must_fail(check_add_by_address_and_location, root, ("js/boardadd.js", "if (navigator.geolocation) row.appendChild", "if (true) row.appendChild"))


def check_failures(root):
    with add_session(root) as s:  # offline before anything loaded: no request is made; online again, the same search works
        s.mocks.network = copy.deepcopy(ADD_NET)
        s.open(hash_="#board")
        s.wait_live()
        s.page.click("#bvAddStop")
        s.ctx.set_offline(True)
        look(s, "walnut 11th")
        assert msg(s).startswith("You're offline") and s.mocks.network_hits == 0 and picks_(s) == []
        s.ctx.set_offline(False)
        look(s, "walnut 11th")
        assert len(wait_picks(s, 3)) == 3
        s.ctx.set_offline(True)  # stops known, address needs Nominatim
        look(s, "100 Test Ave")
        assert msg(s).startswith("You're offline") and "address" in msg(s)
        look(s, "walnut 11th")  # a name needs no network
        assert len(wait_picks(s, 3)) == 3
    with add_session(root) as s:  # the lookup fails, the list fails and recovers
        s.mocks.network_mode = "http500"
        s.mocks.network = copy.deepcopy(ADD_NET)
        s.open(hash_="#board")
        s.wait_live()
        s.page.click("#bvAddStop")
        look(s, "walnut 11th")
        s.page.wait_for_selector(f"{ADD} button:text('Try again')")
        assert "couldn't load" in msg(s) and picks_(s) == []
        s.mocks.network_mode = "ok"
        s.page.click(f"{ADD} button:text('Try again')")
        assert len(wait_picks(s, 3)) == 3 and s.page.locator(f"{ADD} button:text('Try again')").count() == 0
        look(s, "zzzz unknown")  # Nominatim is not mocked for this one: the request fails
        s.page.wait_for_function("document.querySelector('#bvAddMsg').textContent.startsWith('Address lookup failed')", timeout=15000)
        assert picks_(s) == []
    saver = "Object.defineProperty(navigator, 'connection', {value: {saveData: true}, configurable: true})"
    with add_session(root, extra=[saver]) as s:  # Data Saver: one tap loads the 275 KB list
        add_open(s)
        look(s, "walnut 11th")
        s.page.wait_for_selector(f"{ADD} button:text('Load bus stops (about 275 KB)')")
        assert s.mocks.network_hits == 0 and "Data Saver" in msg(s)
        s.page.click(f"{ADD} button:text('Load bus stops (about 275 KB)')")
        assert len(wait_picks(s, 3)) == 3 and s.mocks.network_hits == 1


def test_add_a_bus_stop_offline_failures_and_data_saver(root):
    check_failures(root)
    must_fail(check_failures, root, ("js/boardadd.js", "if (offline()) return note(\"You're offline. Reconnect to look up bus stops.\");", ""))
    must_fail(check_failures, root, ("js/boardadd.js", "if (dataSaver() && !S.routing.networkRequested()) {", "if (false) {"))
    must_fail(check_failures, root, ("js/boardadd.js", "Address lookup failed.", "Failed."))


def check_limits_and_places(root):
    seven = json.dumps({"pins": [pin(i, walkMin=3) for i in range(7)], "bufferMin": 2, "bad": False})
    with add_session(root, extra=[seed(KEY, seven)]) as s:
        add_open(s, empty=False)
        look(s, "walnut 11th")
        wait_picks(s, 3)
        js(s, "window.SEPTA.board.addPin({route: '99', stopId: '555', stopName: 'Other', lat: 39.9, lng: -75.1, placeId: null})")  # full while the list is open
        s.page.locator(f"{ADD} .bv-pick").first.click()
        assert "up to 8 bus stops" in msg(s) and len(stored_pins(s)) == 8
        s.page.keyboard.press("Escape")  # back in Settings, drawn again: no button, the limit instead
        assert s.page.locator("#bvSettings").is_visible() and s.page.locator("[data-fk=addstop]").count() == 0
        assert "up to 8 bus stops" in s.page.inner_text("#bvSettings")
        s.page.keyboard.press("Escape")
        assert s.page.locator("#boardView").is_visible() and s.page.locator("#bvSettings").is_hidden()
        js(s, "window.SEPTA.boardadd.open()")  # opened some other way: the search is not offered
        assert s.page.locator(Q).is_hidden() and "Remove one in Settings" in s.page.inner_text(ADD)
        s.page.keyboard.press("Escape")
        assert s.page.locator("#boardView").is_visible() and s.page.locator(ADD).is_hidden()
        assert not s.console_errors, s.console_errors
    with add_session(root, extra=[seed("septa.places.v1", PLACES)]) as s:  # saved places: which place is the stop for?
        add_open(s)
        look(s, "walnut 11th")
        wait_picks(s, 3)
        s.page.locator(f"{ADD} .bv-pick").nth(1).click()
        s.page.wait_for_selector(f"{ADD} :text('Which place is Route 21')")
        assert js(s, "window.SEPTA.board.pins().length") == 0
        names = s.page.locator(f"{ADD} [data-fk=pl]").all_inner_texts()
        assert names == ["Home", "Gym", "No place"], names
        s.page.locator(f"{ADD} [data-fk=pl]").first.click()
        s.page.wait_for_selector(f"{ADD} :text('Added Route 21')")
        pins = stored_pins(s)
        assert len(pins) == 1 and pins[0]["placeId"] == "home" and pins[0]["walkMin"] is None, pins
        s.page.click(f"{ADD} :text('Add another stop')")
        assert active(s) == "bvStopQ" and s.page.input_value(Q) == ""
        look(s, "walnut 11th")
        wait_picks(s, 3)
        s.page.locator(f"{ADD} .bv-pick").nth(1).click()  # Home is taken for this stop, the others are not
        s.page.wait_for_selector(f"{ADD} :text('Which place is Route 21')")
        off = s.page.locator(f"{ADD} [data-fk=pl]").evaluate_all("els => els.map(e => e.disabled)")
        assert off == [True, False, False], off
        s.page.click(f"{ADD} :text('Back to the list')")
        assert len(picks_(s)) == 3


def test_add_a_bus_stop_limit_and_saved_places(root):
    check_limits_and_places(root)
    must_fail(check_limits_and_places, root, ("js/boardadd.js", "nodes.search.hidden = !!full;", "nodes.search.hidden = false;"))
    must_fail(check_limits_and_places, root, ("js/boardadd.js", "if (opts.length < 2) return pin(r, null);", "if (true) return pin(r, null);"))
    must_fail(check_limits_and_places, root, ("js/boardsettings.js", "if (count >= max) {", "if (false) {"))


def check_suggest_escape_and_sizes(root):
    with add_session(root) as s:
        s.photon.features = [PF("Test Ave Plaza", lng=ADD_AT["lng"], lat=ADD_AT["lat"], street="Test Ave", housenumber="100")]
        add_open(s)
        s.page.fill(Q, "city hall")  # a built-in place: no network
        s.page.wait_for_selector(".sug-list:not([hidden]) [role=option]")
        s.page.keyboard.press("Escape")  # first the suggestions, then the text, then the sheet
        assert s.page.locator(".sug-list:not([hidden])").count() == 0 and s.page.locator(ADD).is_visible()
        s.page.keyboard.press("Escape")
        assert s.page.input_value(Q) == "" and s.page.locator(ADD).is_visible()
        s.page.keyboard.press("Escape")
        assert s.page.locator(ADD).is_hidden() and s.page.locator("#boardView").is_visible()
        s.page.click("#bvAddStop")
        s.page.fill(Q, "city hall")
        s.page.wait_for_selector(".sug-list:not([hidden]) [role=option]")
        s.page.locator(".sug-list [role=option]").first.click()  # a suggestion searches at once
        assert len(wait_picks(s)) > 0 and "near" in msg(s) and "City Hall" in msg(s), msg(s)
        assert not s.console_errors, s.console_errors
    for vp, kw in (((390, 844), dict(mobile=True, touch=True)), ((768, 1024), {})):
        with add_session(root, viewport=vp, **kw) as s:
            add_open(s)
            look(s, "100 Test Ave")
            got = wait_picks(s)
            assert all(g["h"] >= 44 for g in got), got
            boxes = s.page.evaluate(f"""() => [...document.querySelectorAll('{ADD} button, {ADD} input')].filter(b => b.offsetParent).map(b => [b.textContent.trim() || b.id, b.getBoundingClientRect().height, b.getBoundingClientRect().right])""")
            assert all(h >= 44 and r <= vp[0] for _, h, r in boxes), boxes
            assert s.page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_add_a_bus_stop_escape_suggestions_and_touch_targets(root):
    check_suggest_escape_and_sizes(root)
    must_fail(check_suggest_escape_and_sizes, root, ("js/boardview.js", "e.preventDefault(); /* a search box", "/* a search box"))
    must_fail(check_suggest_escape_and_sizes, root, ("js/boardadd.js", "if (q.getAttribute('aria-expanded') === 'true') {", "if (false) {"))
    must_fail(check_suggest_escape_and_sizes, root, ("js/boardadd.js", "onPick: function () {\n        submit();", "onPick: function () {\n        "))
