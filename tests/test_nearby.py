"""WP-S2: Nearby stops, Get me home through the trip planner, the empty From rule and address-first suggestions.

Hermetic: the bus network, Photon, Nominatim, routing and Indego all come from the harness mocks (see test_trip_ui.session).
The stop ids in the small network below exist in tests/fixtures/Stops.json for routes 12, 21 and 42, so a row can open the real stop card.
"""
import copy
import json
import math

from harness import Session, photon_feature as F
from test_first_run import must_fail
from test_trip_ui import CENTER, HOOK, SEED_PREFS, boot as trip_boot, session, wait_cards

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_nearest_list_content_order_card_and_lazy_load",
    "test_get_me_home_plans_from_location_to_home",
    "test_typed_address_ranks_above_businesses_and_keeps_its_number",
    "test_load_failure_says_so_and_the_next_search_retries",
    "test_loading_line_and_live_region",
    "test_empty_from_without_location_says_add_a_start",
}

SEARCH = {"lat": 39.9500, "lng": -75.1650}
HOME = {"name": "Home", "lat": 39.9300, "lng": -75.1900}
PLACES = json.dumps({"home": HOME, "list": []})
SEED_HOME = f"try {{ localStorage.setItem('septa.places.v1', {json.dumps(PLACES)}); }} catch (e) {{}}"
GEO = {"latitude": 39.9560, "longitude": -75.1700}


def at(north_m=0, east_m=0):
    """A point north_m / east_m metres from the search point."""
    return [round(SEARCH["lat"] + north_m / 111195, 6), round(SEARCH["lng"] + east_m / (111195 * math.cos(math.radians(SEARCH["lat"]))), 6)]


def stop(name, **off):
    return at(**off) + [name]


NET = {
    "v": 1, "generated": "2026-01-01", "feed": {"start": "20260101", "end": "20271231"},
    "stops": {
        "14885": stop("Walnut St & 11th St", north_m=80),
        "14884": stop("Walnut St & 12th St", east_m=200),
        "14883": stop("Walnut St & 13th St", north_m=-450),
        "14882": stop("Spruce St & 11th St", east_m=-700),
        "14887": stop("Pine St & 11th St", north_m=900),
        "14080": stop("Lombard St & 11th St", north_m=1000),
        "14886": stop("Far St & Far Ave", north_m=6000),
    },
    "patterns": [
        {"id": "12-0-1", "route": "12", "kind": "bus", "dir": 0, "head": "West", "stops": ["14885", "14882", "14886"], "mins": [0, 3, 9], "hw": 10, "trips": 40},
        {"id": "21-0-1", "route": "21", "kind": "bus", "dir": 0, "head": "East", "stops": ["14885", "14884", "14883"], "mins": [0, 2, 6], "hw": 12, "trips": 40},
        {"id": "42-0-1", "route": "42", "kind": "bus", "dir": 0, "head": "North", "stops": ["14885", "14884", "14887", "14080"], "mins": [0, 2, 6, 8], "hw": 15, "trips": 30},
    ],
}
EXPECTED = [  # name, distance text, route chips, in order
    ("Walnut St & 11th St", "250 ft", ["12", "21", "42"]),
    ("Walnut St & 12th St", "650 ft", ["21", "42"]),
    ("Walnut St & 13th St", "0.3 mi", ["21"]),
    ("Spruce St & 11th St", "0.4 mi", ["12"]),
    ("Pine St & 11th St", "0.6 mi", ["42"]),
]


def boot(s, net=NET):
    """The fixture feed has real buses on routes 12, 21 and 42 in Center City; only the test's own bus (99021) stays tracked."""
    tv = s.worker.data["TransitView"]
    tv["bus"] = [b for b in tv["bus"] if b["route_id"] not in ("12", "21", "42") or b["VehicleID"] == "99021"]
    s.mocks.network = copy.deepcopy(net)
    s.open()
    s.wait_live()


def search(s, q="Search Place"):
    s.page.fill("#addr", q)
    s.page.click("#btnSearch")
    s.page.wait_for_function("!document.querySelector('#btnSearch').disabled")


def search_session(**kw):
    kw["extra_routes"] = {"q=Search": (200, "application/json", json.dumps(
        [{"lat": str(SEARCH["lat"]), "lon": str(SEARCH["lng"]), "display_name": "Search Place, Philadelphia, Pennsylvania, USA"}]))}
    return session(**kw)


def rows(s):
    return s.page.evaluate("""() => [...document.querySelectorAll('#nearList .near-row')].map(b => ({
        name: b.querySelector('.near-nm').textContent, dist: b.querySelector('.near-d').textContent,
        chips: [...b.querySelectorAll('.near-chip')].map(c => c.textContent), label: b.getAttribute('aria-label'), h: b.getBoundingClientRect().height}))""")


def prefs_center(s):
    return s.page.evaluate("JSON.parse(localStorage.getItem('septa.prefs.v1')).center")


# ------------------------------------------------------------------ Nearby stops
def test_nearest_list_content_order_card_and_lazy_load(root):
    with search_session() as s:
        boot(s)
        s.tick(20000)
        assert s.mocks.network_hits == 0, "the bus network must not load on page load"
        assert s.page.locator("#nearSec").is_hidden()
        search(s)
        s.page.wait_for_selector("#nearSec:not([hidden]) .near-row")
        assert s.mocks.network_hits == 1
        got = rows(s)
        assert [(r["name"], r["dist"], r["chips"]) for r in got] == EXPECTED, got  # 5 nearest, the 6th and the far one left out
        assert all(r["h"] >= 44 for r in got), got
        assert got[0]["label"] == "Walnut St & 11th St, 250 ft, routes 12, 21, 42"
        # placement, heading, list semantics, hint
        assert s.page.evaluate("""() => { const f = document.querySelector('#h-find').closest('section'), n = document.querySelector('#nearSec');
            return f.nextElementSibling === n && n.getAttribute('aria-labelledby') === 'h-near' && document.querySelector('#h-near').tagName === 'H2'
              && document.querySelector('#nearList').tagName === 'UL' && document.querySelectorAll('#nearList > li').length === 5 }""")
        assert s.page.text_content("#h-near") == "Nearby stops"
        assert s.page.inner_text("#nearHint") == "Tap a stop for arrivals and alerts"
        live = s.page.locator("#nearStatus")
        assert live.get_attribute("role") == "status" and live.get_attribute("aria-live") == "polite"
        assert live.text_content() == "5 nearby stops" and "sr-only" in live.get_attribute("class"), live.text_content()
        # tapping a row opens the stop card (no tracked bus: the first route), with the share-link hash, and the list stays put
        saved = prefs_center(s)
        s.page.click("#nearList .near-row >> nth=0")
        s.page.wait_for_selector("#stopCard:not([hidden]) .sub")
        assert "Stop 14885 · Route 12" in s.page.inner_text("#stopCard"), s.page.inner_text("#stopCard")
        assert s.page.evaluate("location.hash") == "#stop=14885&route=12"
        assert len(rows(s)) == 5 and s.mocks.network_hits == 1
        assert s.page.evaluate("document.querySelector('#stopCard').contains(document.activeElement)"), "focus moves into the stop card"
        assert prefs_center(s) == saved, "opening a stop must not move the saved center"
        # keyboard: Enter on a focused row opens that stop
        s.page.focus("#nearList .near-row >> nth=3")
        s.page.keyboard.press("Enter")
        s.page.wait_for_function("document.querySelector('#stopCard').textContent.includes('Stop 14882')")
        assert "Route 12" in s.page.inner_text("#stopCard")
        # a second search re-lists without fetching the network again
        search(s)
        s.page.wait_for_selector("#nearList .near-row")
        assert s.mocks.network_hits == 1 and len(rows(s)) == 5
        assert not s.console_errors and not s.septa_direct


def test_row_opens_the_route_with_the_nearest_tracked_bus(root):
    with search_session() as s:
        tv = s.worker.data["TransitView"]["bus"]
        bus = dict(tv[0])
        la, ln = at(north_m=60)
        bus.update(route_id="21", VehicleID="99021", label="99021", lat=str(la), lng=str(ln), late=0,
                   timestamp=max(int(b["timestamp"]) for b in tv), next_stop_id="14884")
        tv.append(bus)
        boot(s)
        search(s)
        s.page.wait_for_selector("#nearList .near-row")
        s.page.click("#nearList .near-row >> nth=0")
        s.page.wait_for_function("document.querySelector('#stopCard').textContent.includes('Route')")
        assert "Stop 14885 · Route 21" in s.page.inner_text("#stopCard")


def test_use_my_location_lists_stops(root):
    with search_session(geolocation={"latitude": SEARCH["lat"], "longitude": SEARCH["lng"]}) as s:
        boot(s)
        s.page.click("#btnLocate")
        s.page.wait_for_selector("#nearList .near-row")
        assert len(rows(s)) == 5
        assert s.page.locator("#nearSec").is_visible() and "Your location" in (s.page.evaluate("JSON.parse(localStorage.getItem('septa.prefs.v1')).center.label"))


def test_loading_line_and_live_region(root):
    with search_session() as s:
        boot(s)
        held = []
        s.page.route("**/data/bus-network.json*", lambda route: held.append(route))  # the answer waits until the test releases it
        search(s)
        s.page.wait_for_function("document.querySelector('#nearStatus').textContent === 'Finding nearby stops'")
        st = s.page.locator("#nearStatus")
        assert st.is_visible() and st.get_attribute("aria-live") == "polite" and s.page.locator("#nearList .near-row").count() == 0
        assert s.page.locator("#nearHint").is_hidden()
        assert held and s.mocks.network_hits == 0
        s.mocks.handle_network(held[0])
        s.page.wait_for_selector("#nearList .near-row")
        assert st.text_content() == "5 nearby stops" and "sr-only" in st.get_attribute("class") and s.page.locator("#nearHint").is_visible()
        assert len(held) == 1 and s.mocks.network_hits == 1, "one fetch"


SAVE_DATA = "Object.defineProperty(navigator, 'connection', {value: {saveData: true}, configurable: true});"


def check_data_saver(root):
    with search_session(root=root, init_scripts=[HOOK, SEED_PREFS, SAVE_DATA]) as s:
        boot(s)
        search(s)
        btn = s.page.locator("#nearLoad")
        btn.wait_for()
        assert btn.inner_text() == "Show nearby stops (about 275 KB)" and s.page.locator("#nearSec").is_visible()
        assert s.page.locator("#nearList .near-row").count() == 0 and s.mocks.network_hits == 0, "Data Saver: no automatic fetch"
        s.page.wait_for_timeout(300)
        assert s.mocks.network_hits == 0 and s.page.locator("#nearLoad").count() == 1
        assert s.page.evaluate("document.querySelectorAll('#nearSec button').length") == 1, "a single button"
        btn.click()
        s.page.wait_for_selector("#nearList .near-row")
        assert s.mocks.network_hits == 1 and s.page.locator("#nearLoad").count() == 0 and s.page.locator("#nearList .near-row").count() == 5
        # a later search while the file is in memory lists stops without asking again
        search(s)
        s.page.wait_for_selector("#nearList .near-row")
        assert s.page.locator("#nearLoad").count() == 0 and s.mocks.network_hits == 1
        assert not s.console_errors, s.console_errors


def test_data_saver_waits_for_a_tap_before_loading_the_network_file(root):
    check_data_saver(root)
    must_fail(check_data_saver, root, ("js/nearby.js", "if (dataSaver() &&", "if (false &&"))
    must_fail(check_data_saver, root, ("js/nearby.js", "b.remove();\n        load(c, mine);", "b.remove();"))


def test_load_failure_says_so_and_the_next_search_retries(root):
    with search_session() as s:
        s.mocks.network_mode = "http500"
        boot(s)
        search(s)
        s.tick(4000)  # the loader's own retry has run
        st = s.page.locator("#nearStatus")
        s.page.wait_for_function("document.querySelector('#nearStatus').textContent === 'Nearby stops unavailable right now'")
        assert st.is_visible() and s.page.locator("#nearList .near-row").count() == 0 and s.page.locator("#nearHint").is_hidden()
        assert "Part of Septer" not in s.page.inner_text("body")
        assert s.page.locator("#note.bad").count() == 0
        failed = s.mocks.network_hits
        s.tick(120000)
        assert s.mocks.network_hits == failed, "no background retries; the next search tries again"
        # the next search tries again and succeeds
        s.mocks.network_mode = "ok"
        search(s)
        s.page.wait_for_selector("#nearList .near-row")
        assert len(rows(s)) == 5 and st.text_content() == "5 nearby stops"
        assert not [e for e in s.console_errors if e.startswith("pageerror")], s.console_errors


def test_no_stop_within_a_mile_says_so(root):
    net = copy.deepcopy(NET)
    for v in net["stops"].values():
        v[0] = round(v[0] + 0.1, 6)  # every stop about 11 km north of the search point
    with search_session() as s:
        boot(s, net)
        search(s)
        s.page.wait_for_function("document.querySelector('#nearStatus').textContent.startsWith('No bus or trolley stops')")
        assert s.page.locator("#nearStatus").is_visible() and s.page.locator("#nearList .near-row").count() == 0


def test_list_layout_and_targets_from_320_to_1280(root):
    for w, h in ((320, 640), (390, 844), (768, 900), (1280, 800)):
        with search_session(viewport=(w, h)) as s:
            boot(s)
            search(s)
            s.page.wait_for_selector("#nearList .near-row")
            s.page.locator("#nearSec").scroll_into_view_if_needed()
            m = s.page.evaluate("""() => { const p = document.querySelector('#panel'), l = document.querySelector('#nearList').getBoundingClientRect();
                return {sw: document.documentElement.scrollWidth, iw: innerWidth, psw: p.scrollWidth, pcw: p.clientWidth, l: l.left, r: l.right,
                  rows: [...document.querySelectorAll('#nearList .near-row')].map(b => { const r = b.getBoundingClientRect();
                    return {w: r.width, h: r.height, over: b.scrollWidth > b.clientWidth + 1, inside: r.left >= 0 && r.right <= innerWidth}; }),
                  btns: [...document.querySelectorAll('#nearList button')].length} }""")
            assert m["sw"] <= m["iw"] and m["psw"] <= m["pcw"] + 1, (w, m)
            assert m["l"] >= 0 and m["r"] <= m["iw"], (w, m)
            assert len(m["rows"]) == 5 and all(r["h"] >= 44 and r["w"] >= 44 and not r["over"] and r["inside"] for r in m["rows"]), (w, m["rows"])
            if w == 390 or w == 1280:
                s.shot(f"nearby_list_{w}")


def test_list_text_contrast_in_dark_and_light(root):
    js = """() => {
      const lum = (rgb) => { const c = rgb.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => v / 255).map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
      const bg = (e) => { for (; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (!/rgba\\(.*, 0\\)|transparent/.test(c)) return c; } return 'rgb(255,255,255)'; };
      const ratio = (e) => { const a = lum(getComputedStyle(e).color), b = lum(bg(e)); return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); };
      const q = (sel) => [...document.querySelectorAll(sel)].map(e => [sel, ratio(e)]);
      return [].concat(q('#nearList .near-nm'), q('#nearList .near-d'), q('#nearList .near-chip'), q('#nearHint'), q('#h-near'));
    }"""
    for scheme in ("light", "dark"):
        with search_session(color_scheme=scheme) as s:
            boot(s)
            search(s)
            s.page.wait_for_selector("#nearList .near-row")
            got = s.page.evaluate(js)
            assert len(got) >= 5 * 3 + 2, got
            low = [g for g in got if g[1] < 4.5]
            assert not low, (scheme, low)


def test_leave_now_hint_points_to_nearby_stops(root):
    with session() as s:
        trip_boot(s)
        assert s.page.inner_text("#rulesEmpty") == "Tap a stop on the map or in Nearby stops, then tap Add alert."


# ------------------------------------------------------------------ Get me home
def home_session(**kw):
    from test_trip_ui import HOOK, SEED_PREFS, nominatim
    kw.setdefault("extra_routes", nominatim())
    kw["init_scripts"] = [HOOK, SEED_PREFS, SEED_HOME]
    return Session(**kw)


def test_get_me_home_plans_from_location_to_home(root):
    with home_session(geolocation=GEO) as s:
        trip_boot(s)
        before = prefs_center(s)
        btn = s.page.locator("#btnHome")
        assert btn.inner_text() == "Get me home" and btn.is_visible()
        box = btn.bounding_box()
        panel = s.page.locator("#h-find").bounding_box()
        assert box["height"] >= 44 and box["width"] >= 120 and box["y"] > panel["y"]  # a quick action under the search bar
        assert abs(box["y"] - s.page.locator("#btnLocate").bounding_box()["y"]) < 1, "next to Near me"
        assert s.page.evaluate("document.querySelector('#btnHome').closest('section').querySelector('#h-find') !== null")
        btn.click()
        wait_cards(s)
        assert s.page.input_value("#tripFrom") == "Your location" and s.page.input_value("#tripTo") == "Home"
        walk = s.mocks.routing_hits[0]
        assert abs(walk["from"][0] - GEO["latitude"]) < 1e-3 and abs(walk["from"][1] - GEO["longitude"]) < 1e-3, walk
        assert any(abs(h["to"][0] - HOME["lat"]) < 1e-3 and abs(h["to"][1] - HOME["lng"]) < 1e-3 for h in s.mocks.routing_hits)
        assert prefs_center(s) == before, "Get me home must not change the saved search center"
        assert s.page.locator("#gmh").count() == 0 and s.page.locator("#tripResults .tp-card").count() >= 1
        assert not s.page.locator("#btnHome").is_disabled()


def test_get_me_home_without_location_guesses_nothing(root):
    with home_session() as s:
        trip_boot(s)
        before = prefs_center(s)
        s.page.click("#btnHome")
        s.page.wait_for_selector("#tripFromErr:not([hidden])")
        assert s.page.inner_text("#tripFromErr") == "Add a start to get home"
        assert s.page.input_value("#tripTo") == "Home" and s.page.input_value("#tripFrom") == ""
        assert s.page.evaluate("document.activeElement.id") == "tripFrom"
        assert s.mocks.routing_hits == [] and s.page.locator("#tripResults .tp-card").count() == 0
        assert prefs_center(s) == before
        assert not s.page.locator("#btnHome").is_disabled()


def test_get_me_home_button_only_when_home_is_set(root):
    with session() as s:
        trip_boot(s)
        assert s.page.locator("#btnHome").is_hidden()
        assert s.page.inner_text("#homeHelp") == "Set a Home to use Get me home" and s.page.locator("#homeHelp").is_visible()
        s.page.evaluate(f"localStorage.setItem('septa.places.v1', {json.dumps(PLACES)})")
        s.page.reload()
        s.wait_live()
        assert s.page.locator("#btnHome").is_visible() and s.page.locator("#homeHelp").is_hidden()
        s.page.click("#places button[aria-label='Remove Home']")
        assert s.page.locator("#btnHome").is_hidden() and s.page.locator("#homeHelp").is_visible()


# ------------------------------------------------------------------ Plan trip with an empty From
def test_empty_from_tries_your_location_first(root):
    with session(geolocation=GEO) as s:
        trip_boot(s)
        s.page.fill("#tripTo", "Dest Ave")
        s.page.click("#tripGo")
        wait_cards(s)
        assert s.page.input_value("#tripFrom") == "Your location"
        walk = next(h for h in s.mocks.routing_hits if h["profile"] == "foot")
        assert abs(walk["from"][0] - GEO["latitude"]) < 1e-3 and abs(walk["from"][1] - GEO["longitude"]) < 1e-3, walk


def test_empty_from_without_location_says_add_a_start(root):
    with session() as s:
        trip_boot(s)
        before = prefs_center(s)
        s.page.fill("#tripTo", "Dest Ave")
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripFromErr:not([hidden])")
        assert s.page.inner_text("#tripFromErr") == "Add a start" and s.page.input_value("#tripFrom") == ""
        assert s.page.evaluate("document.activeElement.id") == "tripFrom"
        assert s.mocks.routing_hits == [] and s.page.locator("#tripResults").is_hidden()
        assert prefs_center(s) == before == CENTER


# ------------------------------------------------------------------ Photon: a typed address stays an address
BROAD = dict(lng=-75.1695, lat=39.9393, street="South Broad Street")


def test_typed_address_ranks_above_businesses_and_keeps_its_number(root):
    with session() as s:
        s.photon.features = [
            F("Broad Street Diner", street="South Broad Street", osm_value="restaurant", lng=-75.1690, lat=39.9400),
            F(None, housenumber="1601", type="house", **BROAD),
            F("Morel Grocery", housenumber="1600", osm_value="convenience", **BROAD),
            F(None, housenumber="1600", type="house", lng=-75.1696, lat=39.9394, street="South Broad Street"),
        ]
        trip_boot(s)
        s.page.click("#addr")
        s.page.fill("#addr", "1600 south broad")
        s.page.wait_for_selector(".sug-list:not([hidden]) [role=option]")
        opts = s.page.evaluate("""() => [...document.querySelectorAll('.sug-list:not([hidden]) [role=option]')].map(e => [e.querySelector('.sug-l1').textContent, (e.querySelector('.sug-l2') || {}).textContent || ''])""")
        # the typed number first, then other numbered addresses, then businesses; the grocery at 1600 is detail on the address row
        assert [o[0] for o in opts] == ["1600 South Broad Street", "1601 South Broad Street", "Broad Street Diner"], opts
        assert opts[0][1].startswith("Morel Grocery"), opts
        s.page.keyboard.press("ArrowDown")
        s.page.keyboard.press("Enter")
        s.page.click("#btnSearch")
        s.page.wait_for_function("document.querySelector('#note').textContent.includes('Showing vehicles near')")
        assert s.page.inner_text("#note") == "Showing vehicles near 1600 South Broad Street."


def test_a_business_alone_at_the_typed_number_is_labelled_with_the_address(root):
    with session() as s:
        s.photon.features = [F("Morel Grocery", housenumber="1600", osm_value="convenience", **BROAD)]
        trip_boot(s)
        s.page.click("#addr")
        s.page.fill("#addr", "1600 south broad")
        s.page.wait_for_selector(".sug-list:not([hidden]) [role=option]")
        assert s.page.inner_text(".sug-list:not([hidden]) .sug-l1") == "1600 South Broad Street"
        assert s.page.inner_text(".sug-list:not([hidden]) .sug-l2").startswith("Morel Grocery")


def test_a_query_without_a_number_keeps_businesses_as_they_are(root):
    with session() as s:
        s.photon.features = [F("Morel Grocery", housenumber="1600", osm_value="convenience", **BROAD),
                             F(None, housenumber="1601", type="house", **BROAD)]
        trip_boot(s)
        s.page.click("#addr")
        s.page.fill("#addr", "morel grocery")
        s.page.wait_for_selector(".sug-list:not([hidden]) [role=option]")
        labels = s.page.evaluate("[...document.querySelectorAll('.sug-list:not([hidden]) .sug-l1')].map(e => e.textContent)")
        assert labels == ["Morel Grocery", "1601 South Broad Street"], labels
