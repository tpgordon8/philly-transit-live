"""Place and address suggestions (ARCHITECTURE.md section 15.1, WP-C): js/suggest.js, js/landmarks.js, css/suggest.css.

Hermetic: Photon comes from the harness mock (s.photon: request log, canned features, failure modes); Nominatim from
Session(extra_routes=...) via test_trip_ui.session; the page clock runs in real time, so debounce and the one-request-per-second
gap are measured with real waits. The three entry points are the search box (#addr) and the trip fields (#tripFrom, #tripTo).
"""
import pathlib
import re

from harness import Session, photon_feature as F
from test_trip_ui import CENTER, boot, session, wait_cards

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_landmark_is_instant_and_needs_no_network",
    "test_pick_in_search_box_skips_geocode_and_enter_rules",
    "test_keyboard_and_aria",
    "test_debounce_abort_and_one_request_per_second",
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
CITY_HALL = (39.95240, -75.16299)
MARKET = F("1234 Market", lng=-75.1609552, lat=39.9517176, housenumber="1234", street="Market Street", osm_value="commercial", postcode="19107")


def opts(s):
    """The visible options of the open list: id, label, second line, aria-selected."""
    return s.page.evaluate("""() => [...document.querySelectorAll('.sug-list:not([hidden]) [role=option]')].map(e => ({id: e.id,
        label: e.querySelector('.sug-l1').textContent, sub: (e.querySelector('.sug-l2') || {}).textContent || '', sel: e.getAttribute('aria-selected')}))""")


def labels(s):
    return [o["label"] for o in opts(s)]


def live(s):
    return (s.page.text_content("#sugLive") or "").strip()


def type_in(s, sel, text):
    s.page.click(sel)
    s.page.fill(sel, text)


def wait_hits(s, n, timeout=5000):
    waited = 0
    while len(s.photon.hits) < n:
        assert waited < timeout, f"expected {n} Photon request(s), saw {len(s.photon.hits)}"
        s.page.wait_for_timeout(50)
        waited += 50


def wait_live(s, text=None, timeout=5000):
    s.page.wait_for_function(
        "t => { const e = document.querySelector('#sugLive'); const v = e ? e.textContent.trim() : ''; return t ? v === t : v !== ''; }",
        arg=text, timeout=timeout)


def nominatim_log(s):
    reqs = []
    s.page.on("request", lambda r: reqs.append(r.url) if "nominatim" in r.url else None)
    return reqs


def saved_center(s):
    return s.page.evaluate("JSON.parse(localStorage.getItem('septa.prefs.v1')).center")


def submit_search(s):
    s.page.click("#btnSearch")
    s.page.wait_for_function("!document.querySelector('#btnSearch').disabled")


def near(a, b, tol=0.0002):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def no_page_errors(s):
    assert not [e for e in s.console_errors if e.startswith("pageerror")], s.console_errors
    assert not s.septa_direct, s.septa_direct


# ------------------------------------------------------------------ built-in places
def test_landmark_is_instant_and_needs_no_network(root):
    with session() as s:
        boot(s)
        s.page.click("#addr")
        s.page.fill("#addr", "city hall")
        # read in the same turn as the keystroke: no debounce has elapsed, so no request can have been made
        assert len(s.photon.hits) == 0
        got = opts(s)
        assert got and got[0]["label"] == "Philadelphia City Hall" and got[0]["sub"] == "1 Penn Square, Philadelphia, PA", got
        assert s.page.get_attribute("#addr", "aria-expanded") == "true"
        assert not s.unexpected and not s.septa_direct
        # an alias, a substring and a mixed-case query with an apostrophe all find places too
        for q, want in (("PHL", "Philadelphia International Airport"), ("terminal market", "Reading Terminal Market"), ("penns land", "Penn's Landing"),
                        ("wells fargo", "Xfinity Mobile Arena (Wells Fargo Center)")):
            s.page.fill("#addr", q)
            assert want in labels(s), (q, labels(s))
        s.page.fill("#addr", "nothingmatches")
        assert opts(s) == []
        no_page_errors(s)


def test_landmarks_prefix_matches_come_before_substring_matches(root):
    with session() as s:
        boot(s)
        type_in(s, "#addr", "east")
        # "Eastern State Penitentiary" starts with it; Jefferson Station only has it inside the alias "market east station"
        # (and is earlier in the list, so only the prefix-first rule puts Eastern State on top)
        assert labels(s) == ["Eastern State Penitentiary", "Jefferson Station"], labels(s)
        type_in(s, "#addr", "station")
        got = labels(s)
        assert len(got) == 4 and "Suburban Station" in got, got
        type_in(s, "#addr", "philadelphia")  # six places start with it: only the first four in list order are offered
        assert labels(s) == ["Philadelphia City Hall", "30th Street Station", "Philadelphia Museum of Art", "Philadelphia International Airport"], labels(s)


def test_landmark_list_is_complete_and_accurate(root):
    """The built-in list: well-formed rows, the places the owner named, unique names, every point inside the region box."""
    with Session(root) as s:
        s.open()
        rows = s.page.evaluate("window.SEPTA.landmarks.LIST")
    assert 38 <= len(rows) <= 60, len(rows)
    names = []
    for r in rows:
        name, aliases, addr, lat, lng = r.split("|")
        names.append(name)
        assert name and addr and 39.7 <= float(lat) <= 40.2 and -75.5 <= float(lng) <= -74.8, r
    assert len(set(names)) == len(names)
    for need in ("City Hall", "30th Street Station", "Suburban Station", "Jefferson Station", "Reading Terminal Market", "Liberty Bell Center",
                 "Independence Hall", "Philadelphia Museum of Art", "Franklin Institute", "LOVE Park", "Rittenhouse Square", "Washington Square",
                 "Penn's Landing", "Lincoln Financial Field", "Wells Fargo Center", "Citizens Bank Park", "Philadelphia International Airport",
                 "University of Pennsylvania", "Drexel University", "Temple University", "Italian Market", "Eastern State Penitentiary",
                 "Please Touch Museum", "Philadelphia Zoo", "Barnes Foundation", "Magic Gardens"):
        assert any(need.lower() in r.lower() for r in rows), need
    ch = next(r for r in rows if r.startswith("Philadelphia City Hall")).split("|")
    assert near((float(ch[3]), float(ch[4])), CITY_HALL, 0.0005)  # checked against OpenStreetMap, see ARCHITECTURE.md 15.1


# ------------------------------------------------------------------ Photon
def test_address_query_goes_to_photon_with_bias_and_box(root):
    with session() as s:
        s.photon.features = [MARKET]
        boot(s)
        type_in(s, "#addr", "1234 market")
        wait_hits(s, 1)
        wait_live(s, "1 suggestion")
        h = s.photon.hits[0]
        assert h["q"] == "1234 market" and h["limit"] == "6" and h["bbox"] == "-75.5,39.7,-74.8,40.2" and h["lang"] == "en", h
        assert (h["lat"], h["lon"]) == ("39.94", "-75.15"), h  # the seeded map center 39.9400, -75.1500, rounded to 2 decimals
        assert h["url"].startswith("https://photon.komoot.io/api/?q=1234%20market&lat=")
        got = opts(s)
        assert got[0]["label"] == "1234 Market Street" and got[0]["sub"] == "Philadelphia, PA", got
        no_page_errors(s)


def test_labels_region_filter_duplicates_and_caps(root):
    with session() as s:
        s.photon.features = [
            F("Moore College of Art and Design", lng=-75.1720755, lat=39.9568373, housenumber="1916", street="Race Street", osm_value="college"),
            F("Moore College of Art and Design", lng=-75.1720755, lat=39.9568373, housenumber="1916", street="Race Street", osm_value="college"),  # duplicate
            F("Camden City Hall", lng=-75.1199618, lat=39.94484, housenumber="520", street="Market Street", city="Camden", state="New Jersey"),
            F("Harrisburg Diner", lng=-76.88, lat=40.27, city="Harrisburg"),            # outside the box (west and north)
            F("Far East Cafe", lng=-74.5, lat=39.95, city="Trenton", state="New Jersey"),  # outside the box (east)
            F("Market Street", lng=-75.16, lat=39.95, type="street"),
            F(None, lng=-75.1500, lat=39.9400, housenumber="9", street="Pine Street"),   # no name at all: the address is the label
            F("N" * 300, lng=-75.1501, lat=39.9401, street="S" * 300),
            {"type": "Feature", "properties": {"name": "Broken"}, "geometry": None},
        ]
        boot(s)
        type_in(s, "#addr", "moore race")
        wait_live(s)
        got = {o["label"]: o["sub"] for o in opts(s)}
        assert got["Moore College of Art and Design"] == "1916 Race Street, Philadelphia, PA", got
        assert got["Camden City Hall"] == "520 Market Street, Camden, NJ", got
        assert got["Market Street"] == "Philadelphia, PA" and got["9 Pine Street"] == "Philadelphia, PA", got
        assert [o["label"] for o in opts(s)].count("Moore College of Art and Design") == 1
        assert "Harrisburg Diner" not in got and "Far East Cafe" not in got and "Broken" not in got, got
        big = [o for o in opts(s) if o["label"].startswith("NNN")][0]
        assert len(big["label"]) <= 80 and len(big["sub"]) <= 100, (len(big["label"]), len(big["sub"]))
        no_page_errors(s)


def test_photon_result_that_repeats_a_builtin_place_is_dropped(root):
    with session() as s:
        s.photon.features = [F("Philadelphia City Hall", lng=-75.1629893, lat=39.9523995, housenumber="1", street="Penn Square"),
                             F("Old City Hall", lng=-75.1494128, lat=39.9488714, housenumber="5", street="South 5th Street")]
        boot(s)
        type_in(s, "#addr", "city hall")
        wait_hits(s, 1)
        wait_live(s)
        assert labels(s) == ["Philadelphia City Hall", "Old City Hall"], labels(s)  # built-in first, Photon's copy dropped, the other kept


def test_results_near_the_bias_come_first(root):
    with session() as s:
        s.photon.features = [F("Far Diner", lng=-75.40, lat=40.10, street="Lancaster Pike"), F("Near Diner", lng=-75.1480, lat=39.9410, street="Pine Street")]
        boot(s)
        type_in(s, "#addr", "diner")
        wait_hits(s, 1)
        wait_live(s)
        assert labels(s) == ["Near Diner", "Far Diner"], labels(s)  # Photon ranked the far one first; it is ~15 mi from the map center


def test_bias_is_home_for_trip_fields_and_center_for_search(root):
    with session() as s:
        boot(s)
        s.page.evaluate("localStorage.setItem('septa.places.v1', JSON.stringify({home: {name: 'Home spot', lat: 39.9912, lng: -75.1234}, list: []}))")
        s.page.reload()
        s.wait_live()
        type_in(s, "#tripFrom", "abc")
        wait_hits(s, 1)
        assert (s.photon.hits[0]["lat"], s.photon.hits[0]["lon"]) == ("39.99", "-75.12"), s.photon.hits[0]
        s.page.wait_for_timeout(1100)
        type_in(s, "#addr", "abd")
        wait_hits(s, 2)
        assert (s.photon.hits[1]["lat"], s.photon.hits[1]["lon"]) == (f"{CENTER['lat']:.2f}", f"{CENTER['lng']:.2f}"), s.photon.hits[1]


def test_debounce_abort_and_one_request_per_second(root):
    with session() as s:
        s.photon.mode = "hang"  # requests stay in flight until the page aborts them
        failed = []
        s.page.on("requestfailed", lambda r: failed.append(r.url) if "photon" in r.url else None)
        boot(s)
        s.page.click("#addr")
        s.page.keyboard.type("1234 market", delay=40)  # 11 keystrokes, each well inside the 250 ms pause
        wait_hits(s, 1)
        s.page.wait_for_timeout(400)
        assert len(s.photon.hits) == 1 and s.photon.hits[0]["q"] == "1234 market", s.photon.hits  # rapid typing made ONE request
        s.page.keyboard.type(" st")
        wait_hits(s, 2, 4000)
        assert any("q=1234%20market&" in u for u in failed), failed  # the first, still in flight, was aborted
        assert s.photon.hits[1]["q"] == "1234 market st"
        gap = s.photon.hits[1]["t"] - s.photon.hits[0]["t"]
        assert gap >= 0.95, gap  # no more than one request per second
        s.page.wait_for_timeout(300)
        assert len(s.photon.hits) == 2


def test_minimum_three_characters(root):
    with session() as s:
        s.photon.features = [MARKET]
        boot(s)
        type_in(s, "#addr", "ci")
        s.page.wait_for_timeout(600)
        assert len(s.photon.hits) == 0 and opts(s) == [] and live(s) == ""
        s.page.fill("#addr", "cit")
        wait_hits(s, 1)
        assert s.photon.hits[0]["q"] == "cit"
        s.page.fill("#addr", "  ci ")  # spaces do not count
        s.page.wait_for_timeout(500)
        assert len(s.photon.hits) == 1 and opts(s) == []


def test_session_cache_by_normalised_query(root):
    with session() as s:
        s.photon.features = [MARKET]
        boot(s)
        type_in(s, "#addr", "1234 market")
        wait_hits(s, 1)
        wait_live(s, "1 suggestion")
        s.page.fill("#addr", "")
        s.page.fill("#addr", "1234  MARKET ")  # same query after normalising: answered from the cache, instantly, no request
        assert labels(s) == ["1234 Market Street"]
        s.page.wait_for_timeout(700)
        assert len(s.photon.hits) == 1, s.photon.hits
        type_in(s, "#tripTo", "1234 market")  # the cache is shared by all fields
        assert labels(s) == ["1234 Market Street"]
        s.page.wait_for_timeout(500)
        assert len(s.photon.hits) == 1


def test_failure_is_silent_and_submit_still_geocodes(root):
    for mode in ("http500", "abort"):
        with session() as s:
            s.photon.mode = mode
            boot(s)
            reqs = nominatim_log(s)
            type_in(s, "#addr", "Origin St")
            wait_hits(s, 1)
            wait_live(s, "No suggestions")
            assert opts(s) == [] and s.page.get_attribute("#addr", "aria-expanded") == "false"
            assert s.page.is_visible("#note") is True and s.page.inner_text("#note") == ""
            s.page.keyboard.press("Enter")  # today's behaviour: the form submits and Nominatim answers
            s.page.wait_for_function("/Showing vehicles near/.test(document.querySelector('#note').textContent)")
            assert len(reqs) == 1 and "q=Origin" in reqs[0], reqs
            no_page_errors(s)
    with session() as s:  # a failed request is not cached: the same query is asked again
        s.photon.mode = "http500"
        boot(s)
        type_in(s, "#addr", "1234 market")
        wait_hits(s, 1)
        wait_live(s, "No suggestions")
        s.photon.mode = "ok"
        s.photon.features = [MARKET]
        s.page.wait_for_timeout(1000)
        s.page.fill("#addr", "")
        s.page.fill("#addr", "1234 market")
        wait_hits(s, 2)
        wait_live(s, "1 suggestion")


def test_intersections_are_left_to_nominatim(root):
    with session() as s:
        s.photon.features = [MARKET]
        boot(s)
        reqs = nominatim_log(s)
        for q in ("10th and race", "Broad & Market", "10th at race", "market / 40th"):
            type_in(s, "#addr", q)
            s.page.wait_for_timeout(450)
            assert opts(s) == [], (q, opts(s))
        assert len(s.photon.hits) == 0, s.photon.hits
        s.page.fill("#addr", "10th and race")
        s.page.keyboard.press("Enter")
        s.page.wait_for_function("/Showing vehicles near/.test(document.querySelector('#note').textContent)")
        assert len(reqs) == 1 and "q=10th" in reqs[0]


# ------------------------------------------------------------------ picking, in all three entry points
def test_pick_in_search_box_skips_geocode_and_enter_rules(root):
    with session() as s:
        boot(s)
        reqs = nominatim_log(s)
        type_in(s, "#addr", "city hall")
        s.page.click(".sug-list:not([hidden]) [role=option]:first-child")
        assert s.page.input_value("#addr") == "Philadelphia City Hall"
        assert opts(s) == [] and s.page.get_attribute("#addr", "aria-expanded") == "false"
        submit_search(s)
        c = saved_center(s)
        assert near((c["lat"], c["lng"]), CITY_HALL) and c["label"] == "Philadelphia City Hall", c
        assert s.page.inner_text("#note") == "Showing vehicles near Philadelphia City Hall."
        assert reqs == [], reqs  # no geocoding at all
        # Enter with an option highlighted picks it (and does not submit); the next Enter submits with the stored coordinates
        s.page.fill("#addr", "liberty bell")
        s.page.keyboard.press("ArrowDown")
        s.page.keyboard.press("Enter")
        assert s.page.input_value("#addr") == "Liberty Bell Center" and saved_center(s)["label"] == "Philadelphia City Hall"
        s.page.keyboard.press("Enter")
        s.page.wait_for_function("document.querySelector('#note').textContent.includes('Liberty Bell Center')")
        assert reqs == [] and abs(saved_center(s)["lat"] - 39.94995) < 0.0002
        # Enter with nothing highlighted keeps today's behaviour: the typed text is geocoded
        s.page.fill("#addr", "Origin St")
        s.page.keyboard.press("Enter")
        s.page.wait_for_function("document.querySelector('#note').textContent.includes('Origin')")
        assert len(reqs) == 1 and "q=Origin" in reqs[0], reqs
        # ... also while the list is open with nothing highlighted
        s.page.fill("#addr", "station")
        assert len(opts(s)) == 4 and all(o["sel"] == "false" for o in opts(s))
        s.page.keyboard.press("Enter")
        s.page.wait_for_function("document.querySelector('#btnSearch').disabled === false && document.querySelector('#note').textContent !== ''")
        assert len(reqs) == 2 and "q=station" in reqs[1], reqs
        no_page_errors(s)


def test_pick_a_photon_result_in_search_box(root):
    with session() as s:
        s.photon.features = [MARKET]
        boot(s)
        reqs = nominatim_log(s)
        type_in(s, "#addr", "1234 market")
        wait_live(s, "1 suggestion")
        s.page.click("[role=option]")
        submit_search(s)
        c = saved_center(s)
        assert near((c["lat"], c["lng"]), (39.9517176, -75.1609552)) and c["label"] == "1234 Market Street", c
        assert reqs == []


def test_pick_in_trip_fields_skips_geocode(root):
    with session() as s:
        s.photon.features = [MARKET]
        boot(s)
        reqs = nominatim_log(s)
        type_in(s, "#tripFrom", "city hall")
        s.page.click(".sug-list:not([hidden]) [role=option]:first-child")
        assert s.page.input_value("#tripFrom") == "Philadelphia City Hall"
        type_in(s, "#tripTo", "1234 market")
        wait_live(s, "1 suggestion")
        s.page.click(".sug-list:not([hidden]) [role=option]:first-child")
        assert s.page.input_value("#tripTo") == "1234 Market Street"
        s.page.click("#tripGo")
        wait_cards(s)
        assert reqs == [], reqs
        hits = s.mocks.worker_route_hits
        assert any(h["from"] and near(h["from"], CITY_HALL, 0.0002) for h in hits), hits[:3]
        assert any(h["to"] and near(h["to"], (39.9517176, -75.1609552), 0.0002) for h in hits), hits[:3]
        no_page_errors(s)


def test_edit_after_pick_discards_the_coordinates(root):
    with session() as s:
        boot(s)
        reqs = nominatim_log(s)
        # search box: pick, then edit, then submit: the edited text is geocoded (it starts with "Origin"), not the stale point
        type_in(s, "#addr", "city hall")
        s.page.click("[role=option]")
        s.page.keyboard.press("Home")
        s.page.keyboard.type("Origin ")
        s.page.keyboard.press("Enter")
        s.page.wait_for_function("/Showing vehicles near/.test(document.querySelector('#note').textContent)")
        assert len(reqs) == 1 and "q=Origin%20Philadelphia%20City%20Hall" in reqs[0], reqs
        assert abs(saved_center(s)["lat"] - 39.94) < 0.01, saved_center(s)  # Origin St, not City Hall
        # same text typed back by hand after an edit: still a fresh lookup, the pick is gone
        s.page.fill("#addr", "city hall")
        s.page.click("[role=option]")
        s.page.fill("#addr", "Philadelphia City Hall")
        submit_search(s)
        assert len(reqs) == 2, reqs
        # trip fields: pick From, edit it, plan: the edited text is looked up
        type_in(s, "#tripFrom", "city hall")
        s.page.click("[role=option]")
        s.page.keyboard.press("Home")
        s.page.keyboard.type("Origin ")
        s.page.fill("#tripTo", "Dest Ave")
        s.page.click("#tripGo")
        wait_cards(s)
        qs = [u for u in reqs[2:]]
        assert len(qs) == 2 and "q=Origin%20Philadelphia%20City%20Hall" in qs[0] and "Dest" in qs[1], qs


# ------------------------------------------------------------------ keyboard and ARIA
def test_keyboard_and_aria(root):
    with session() as s:
        boot(s)
        reqs = nominatim_log(s)
        a = lambda name: s.page.get_attribute("#addr", name)  # noqa: E731
        # at rest
        assert (a("role"), a("aria-autocomplete"), a("aria-expanded"), a("aria-haspopup")) == ("combobox", "list", "false", "listbox")
        lid = a("aria-controls")
        assert lid and s.page.get_attribute("#" + lid, "role") == "listbox" and a("aria-activedescendant") is None
        assert s.page.get_attribute("#" + lid, "hidden") is not None
        # open
        type_in(s, "#addr", "station")
        got = opts(s)
        assert len(got) == 4 and a("aria-expanded") == "true" and a("aria-activedescendant") is None
        assert len({o["id"] for o in got}) == 4 and all(o["sel"] == "false" for o in got)
        assert s.page.evaluate("document.querySelector('.sug-list:not([hidden])').id") == lid
        # Down, Up (wrapping), End, Home
        press = s.page.keyboard.press

        def active():
            g = opts(s)
            sel = [i for i, o in enumerate(g) if o["sel"] == "true"]
            assert len(sel) <= 1, g
            return (sel[0] if sel else None, a("aria-activedescendant"), [o["id"] for o in g])

        press("ArrowDown")
        i, d, ids = active()
        assert i == 0 and d == ids[0]
        press("ArrowDown")
        press("ArrowDown")
        i, d, ids = active()
        assert i == 2 and d == ids[2]
        press("ArrowUp")
        assert active()[0] == 1
        press("End")
        i, d, ids = active()
        assert i == 3 and d == ids[3]
        press("ArrowDown")
        assert active()[0] == 0  # wraps
        press("ArrowUp")
        assert active()[0] == 3
        press("Home")
        assert active()[0] == 0
        assert s.page.evaluate("document.activeElement.id") == "addr"  # focus stays in the field the whole time
        # Enter picks the highlighted option and closes
        press("ArrowDown")
        want = opts(s)[1]["label"]
        press("Enter")
        assert s.page.input_value("#addr") == want and a("aria-expanded") == "false" and a("aria-activedescendant") is None
        assert opts(s) == [] and reqs == [] and s.page.inner_text("#note") == ""  # picking does not submit
        # Escape: first closes and keeps the text, then clears it
        type_in(s, "#addr", "station")
        press("ArrowDown")
        press("Escape")
        assert a("aria-expanded") == "false" and s.page.input_value("#addr") == "station" and a("aria-activedescendant") is None
        press("Escape")
        assert s.page.input_value("#addr") == "" and opts(s) == []
        # Down re-opens a closed list that still has suggestions
        s.page.fill("#addr", "station")
        press("Escape")
        assert a("aria-expanded") == "false"
        press("ArrowDown")
        assert a("aria-expanded") == "true" and active()[0] == 0
        # Tab closes the list on its own (a synthetic Tab does not move focus, so the blur cannot be what closed it) and then moves on
        s.page.fill("#addr", "station")
        assert a("aria-expanded") == "true"
        s.page.dispatch_event("#addr", "keydown", {"key": "Tab"})
        assert a("aria-expanded") == "false" and s.page.evaluate("document.activeElement.id") == "addr"
        s.page.fill("#addr", "station")
        press("Tab")
        assert a("aria-expanded") == "false" and opts(s) == []
        assert s.page.evaluate("document.activeElement.id") != "addr"
        # the two trip fields are comboboxes with their own lists
        for sel in ("#tripFrom", "#tripTo"):
            assert s.page.get_attribute(sel, "role") == "combobox" and s.page.get_attribute(sel, "aria-controls") != lid
        no_page_errors(s)


def test_live_region_announces_counts(root):
    with session() as s:
        s.photon.features = [MARKET, F("Market Street", lng=-75.16, lat=39.95, type="street")]
        boot(s)
        assert s.page.get_attribute("#sugLive", "role") == "status" and s.page.get_attribute("#sugLive", "aria-live") == "polite"
        type_in(s, "#addr", "chop")
        assert live(s) == ""  # one built-in place, but Photon has not answered: the count waits for the final list
        wait_live(s, "3 suggestions")
        s.page.wait_for_timeout(1100)
        s.page.fill("#addr", "zzzzz")
        wait_live(s, "3 suggestions")  # the mock answers every query with the same two places
        s.photon.features = []
        s.page.wait_for_timeout(1100)
        s.page.fill("#addr", "qqqqq")
        wait_live(s, "No suggestions")
        s.page.fill("#addr", "ci")  # below three characters: nothing is announced
        assert live(s) == ""
        s.page.fill("#addr", "city hall")
        s.page.fill("#addr", "")
        assert live(s) == ""


# ------------------------------------------------------------------ safety and looks
def test_service_text_is_rendered_as_text(root):
    payload = "<img src=x onerror=\"window.__xss=1\">"
    with session() as s:
        s.photon.features = [F(payload, lng=-75.15, lat=39.94, street="<b>bold</b>", housenumber="1"), F("a&amp;b", lng=-75.151, lat=39.941, street="</li><script>window.__xss=2</script>")]
        boot(s)
        type_in(s, "#addr", "zzzz")
        wait_live(s, "2 suggestions")
        got = opts(s)
        assert got[0]["label"] == payload and got[0]["sub"] == "1 <b>bold</b>, Philadelphia, PA", got
        assert got[1]["label"] == "a&amp;b" and "<script>" in got[1]["sub"], got
        assert s.page.evaluate("document.querySelectorAll('.sug-list img, .sug-list b, .sug-list script').length") == 0
        s.page.click("[role=option]")
        s.page.wait_for_timeout(300)
        assert s.page.input_value("#addr") == payload
        assert s.page.evaluate("window.__xss") is None
        no_page_errors(s)


def test_list_is_visible_unclipped_and_tall_enough_at_390_and_1280(root):
    for vp, sels in (((390, 844), ("#addr", "#tripFrom", "#tripTo")), ((1280, 800), ("#addr", "#tripFrom", "#tripTo")), ((390, 420), ("#tripTo",))):
        with session(viewport=vp) as s:
            s.photon.features = [F(f"Place number {i}", lng=-75.15 + i / 1000, lat=39.95, street="Pine Street") for i in range(5)]
            s.photon.features.append(F("Place bare", lng=-75.155, lat=39.95, city="", state=""))  # no second line: a one-line row must still be 44 px
            boot(s)
            for sel in sels:
                s.page.locator(sel).scroll_into_view_if_needed()
                type_in(s, sel, "place")
                s.page.wait_for_selector(".sug-list:not([hidden]) [role=option]")
                wait_live(s)
                g = s.page.evaluate("""(sel) => { const l = document.querySelector('.sug-list:not([hidden])'), r = l.getBoundingClientRect(), i = document.querySelector(sel).getBoundingClientRect();
                    const opts = [...l.querySelectorAll('[role=option]')], first = opts[0].getBoundingClientRect(), mid = [r.left + r.width / 2, Math.min(r.bottom - 5, r.top + 20)];
                    const top = document.elementFromPoint(mid[0], mid[1]);
                    return {l: r.left, t: r.top, rt: r.right, b: r.bottom, iw: innerWidth, ih: innerHeight, sh: l.scrollHeight, ch: l.clientHeight, minh: Math.min(...opts.map(o => o.getBoundingClientRect().height)),
                            hitList: !!(top && top.closest('.sug-list')), inputTop: i.top, inputBottom: i.bottom, n: opts.length, z: getComputedStyle(l).zIndex}; }""", sel)
                assert g["l"] >= 0 and g["rt"] <= g["iw"] and g["t"] >= 0 and g["b"] <= g["ih"], (vp, sel, g)
                assert g["minh"] >= 44 and g["hitList"] and g["n"] == 6, (vp, sel, g)
                assert g["b"] <= g["inputTop"] or g["t"] >= g["inputBottom"] - 1, (vp, sel, g)  # never covers the field being typed in
                if vp[1] == 420:
                    assert g["sh"] > g["ch"], g  # too long for the room: it scrolls inside its own box
                    s.page.keyboard.press("End")
                    assert s.page.evaluate("(() => { const l = document.querySelector('.sug-list:not([hidden])'); const o = l.querySelector('[aria-selected=true]').getBoundingClientRect(), r = l.getBoundingClientRect(); return o.bottom <= r.bottom + 1 && o.top >= r.top - 1; })()")
                s.page.keyboard.press("Escape")
            s.shot("list_%d" % vp[0])


def test_highlight_does_not_rely_on_colour_in_light_and_dark(root):
    for scheme in ("light", "dark"):
        with session() as s:
            boot(s)
            s.page.emulate_media(color_scheme=scheme)
            type_in(s, "#addr", "station")
            s.page.keyboard.press("ArrowDown")
            st = s.page.evaluate("""() => { const q = (e) => { const c = getComputedStyle(e); return {ow: parseFloat(c.outlineWidth), os: c.outlineStyle, bl: parseFloat(c.borderLeftWidth), blc: c.borderLeftColor, bg: c.backgroundColor, fg: c.color}; };
                const o = [...document.querySelectorAll('.sug-list:not([hidden]) [role=option]')]; return {on: q(o[0]), off: q(o[1]), list: q(document.querySelector('.sug-list:not([hidden])'))}; }""")
            assert st["on"]["os"] == "solid" and st["on"]["ow"] >= 2 and st["on"]["bl"] >= 4, st  # a shape cue: outline and heavy edge
            assert st["off"]["ow"] == 0 or st["off"]["os"] == "none", st
            assert st["on"]["blc"] != st["off"]["blc"], st  # the heavy edge bar is drawn only on the highlighted row
            assert st["list"]["bg"] != st["list"]["fg"] and st["on"]["bg"] != st["off"]["bg"], st
            lum = lambda c: sum(int(x) * w for x, w in zip(re.findall(r"\d+", c)[:3], (0.2126, 0.7152, 0.0722)))  # noqa: E731
            assert (lum(st["list"]["bg"]) < 128) == (scheme == "dark"), (scheme, st)  # the list follows the theme
            s.shot("highlight_" + scheme)


def test_touch_pick_on_a_phone_does_not_fall_through(root):
    with session(viewport=(390, 844), touch=True) as s:
        boot(s)
        s.page.evaluate("window.__hits = []; document.addEventListener('click', e => window.__hits.push((e.target.id || e.target.className || e.target.tagName) + ''), true)")
        s.page.locator("#addr").scroll_into_view_if_needed()
        s.page.tap("#addr")
        s.page.fill("#addr", "city hall")
        box = s.page.locator(".sug-list:not([hidden]) [role=option]").first.bounding_box()
        assert box["height"] >= 44 and 0 <= box["x"] and box["x"] + box["width"] <= 390, box
        s.page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        s.page.wait_for_function("document.querySelector('#addr').value === 'Philadelphia City Hall'")
        assert opts(s) == []
        hits = s.page.evaluate("window.__hits")
        assert all("sug-" in h or h == "addr" for h in hits), hits  # the tap did not land on a control the list had covered
        assert s.page.evaluate("document.activeElement.id") == "addr"  # focus stayed (the keyboard stays up)
        submit_search(s)
        c = saved_center(s)
        assert near((c["lat"], c["lng"]), CITY_HALL), c
        s.shot("touch_pick")


def test_mouse_picks_on_pointerdown_but_touch_waits_for_the_tap(root):
    with session() as s:
        boot(s)
        type_in(s, "#addr", "city hall")
        ev = "(t) => document.querySelector('.sug-list:not([hidden]) [role=option]').dispatchEvent(new PointerEvent('pointerdown', {pointerType: t, button: 0, bubbles: true}))"
        s.page.evaluate(ev, "touch")  # a finger going down may be the start of a scroll: nothing is picked yet
        s.page.evaluate(ev, "pen")
        assert s.page.input_value("#addr") == "city hall" and len(opts(s)) >= 1
        s.page.evaluate(ev, "mouse")  # a mouse press picks at once, before any blur or click
        assert s.page.input_value("#addr") == "Philadelphia City Hall" and opts(s) == []


def test_scrolling_a_long_list_by_touch_does_not_pick(root):
    with session(viewport=(390, 420), touch=True) as s:
        s.photon.features = [F(f"Station cafe {i}", lng=-75.15 + i / 1000, lat=39.95, street="Pine Street") for i in range(6)]
        boot(s)
        s.page.locator("#addr").scroll_into_view_if_needed()
        s.page.tap("#addr")
        s.page.fill("#addr", "station")
        wait_live(s)
        assert s.page.evaluate("(() => { const l = document.querySelector('.sug-list:not([hidden])'); return l.scrollHeight > l.clientHeight; })()")
        box = s.page.locator(".sug-list:not([hidden]) [role=option]").nth(2).bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        cdp = s.page.context.new_cdp_session(s.page)  # a real finger drag: touch down on an option, move up, lift
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        for k in range(1, 9):
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y - 12 * k}]})
            s.page.wait_for_timeout(16)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        s.page.wait_for_timeout(300)
        top = s.page.evaluate("document.querySelector('.sug-list:not([hidden])').scrollTop")
        assert top > 20, top  # the drag scrolled the list ...
        assert s.page.input_value("#addr") == "station" and len(opts(s)) == 8  # ... and picked nothing
        s.page.wait_for_timeout(300)  # and the list keeps its scroll position, also when the page is re-measured (resize, keyboard)
        s.page.evaluate("window.dispatchEvent(new Event('resize'))")
        assert s.page.evaluate("document.querySelector('.sug-list:not([hidden])').scrollTop") == top


# ------------------------------------------------------------------ privacy text
def test_privacy_text_and_attribution_in_page_and_docs(root):
    root = pathlib.Path(root)
    html = (root / "index.html").read_text()
    readme = (root / "README.md").read_text()
    arch = (root / "ARCHITECTURE.md").read_text()
    assert html.count("Suggestions: ") == 2 and html.count('https://photon.komoot.io/"') == 2
    with session() as s:
        s.open()
        s.wait_live()
        for sel in ("#sugAttrFind", "#sugAttrTrip"):
            assert s.page.inner_text(sel) == "Suggestions: Photon, © OpenStreetMap contributors", s.page.inner_text(sel)
        priv = s.page.inner_text(".tp-priv")
    for text in (priv, readme, arch[arch.index("### 12.4"):arch.index("## 13.")]):
        for part in ("photon.komoot.io", "2 decimals", "Nominatim"):
            assert part in text, part
        assert re.search(r"typed text|typed search text", text) and re.search(r"map cent(er|re)", text) and re.search(r"intersection", text)
    assert "Photon" in readme and "Photon" in arch


def test_files_and_order(root):
    html = (ROOT / "index.html").read_text()
    assert html.index("css/trip.css") < html.index("css/suggest.css") < html.index("css/stops.css")
    assert html.index("js/map.js") < html.index("js/landmarks.js") < html.index("js/suggest.js") < html.index("js/panel.js") < html.index("js/trip.js")
    assert "suggest:{}" in html and "landmarks:{}" in html
    for f in ("js/suggest.js", "js/landmarks.js"):
        assert (ROOT / f).read_text().count("\n") <= 700
