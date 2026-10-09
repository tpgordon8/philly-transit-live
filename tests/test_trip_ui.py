"""Trip planner UI (ARCHITECTURE.md section 12): the "Plan a trip" sidebar section, result cards, the map drawing layer.

Hermetic: Nominatim comes from Session(extra_routes=...), Indego / routing / the bus network from s.mocks (synthetic network
tests/fixtures/bus-network.test.json, routes X47/X45/X99). One live vehicle on X47 is added to the TransitView feed so that
route counts as running. The planner itself is the oracle for expected minutes and mode summaries.
"""
import copy
import json
import re

from harness import FIX, Session

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_a_form_labels_placement_and_geocoding",
    "test_f_routing_failure_message_and_retry",
    "test_i_phone_no_horizontal_scroll_touch_targets_and_show_map",
    "test_s_out_of_region_is_refused_before_any_call",
    "test_s_leg_rounding_note_and_total_from_exact_sum",
}

NET = json.loads((FIX / "bus-network.test.json").read_text())
HOOK = "window.__SEPTA_TEST__ = true"
O = {"lat": 39.94, "lng": -75.15824}
D = {"lat": 39.9575, "lng": -75.15824}
D2 = {"lat": 39.9500, "lng": -75.1600}
CENTER = {"lat": 39.9400, "lng": -75.1500, "label": "Test center"}
PREFS = {"center": CENTER, "radius": 1.5, "filters": {"bus": True, "trolley": True, "subway": True, "train": True}}
SEED_PREFS = f"try {{ if (!/center/.test(localStorage.getItem('septa.prefs.v1') || '')) localStorage.setItem('septa.prefs.v1', {json.dumps(json.dumps(PREFS))}); }} catch (e) {{}}"
SV_SPY = "window.__sv = []; const _s = Element.prototype.scrollIntoView; Element.prototype.scrollIntoView = function (a) { window.__sv.push({id: this.id, a: a}); return _s.apply(this, arguments); };"


def geo(lat, lng, name="X"):
    return (200, "application/json", json.dumps([{"lat": str(lat), "lon": str(lng), "display_name": name + ", Philadelphia, Pennsylvania, USA"}]))


def nominatim():
    return {"q=Origin": geo(O["lat"], O["lng"], "Origin St"), "q=Dest": geo(D["lat"], D["lng"], "Dest Ave"),
            "q=Other": geo(D2["lat"], D2["lng"], "Other Ave"), "q=10th": geo(39.9553, -75.1560, "10th and Race"),
            "q=Nowhere": (200, "application/json", "[]"),
            "q=Near": geo(O["lat"] + 0.0012, O["lng"], "Near St"), "q=Newark": geo(40.7357, -74.1724, "Newark")}


def session(**kw):
    kw.setdefault("extra_routes", nominatim())
    kw.setdefault("init_scripts", [HOOK, SEED_PREFS])
    return Session(**kw)


def boot(s, bikes=5, net=NET, bus_route="X47"):
    """Open the page with the synthetic network, one live X47 bus and (by default) 5 bikes / 5 docks everywhere."""
    s.mocks.network = copy.deepcopy(net)
    if bikes is not None:
        s.mocks.set_all(bikes=bikes, docks=bikes)
    tv = s.worker.data["TransitView"]["bus"]
    newest = max(int(b["timestamp"]) for b in tv)
    bus = dict(tv[0])
    bus.update(route_id=bus_route, next_stop_id="S1", VehicleID="99001", label="99001", timestamp=newest, late=0, lat="39.9300", lng="-75.1580")
    tv.append(bus)
    s.open()
    s.wait_live()


def fill(s, frm="Origin St", to="Dest Ave"):
    s.page.fill("#tripFrom", frm)
    s.page.fill("#tripTo", to)


def wait_cards(s, timeout=15000):
    s.page.wait_for_selector("#tripResults .tp-card", timeout=timeout)


def plan_ui(s, frm="Origin St", to="Dest Ave"):
    fill(s, frm, to)
    s.page.click("#tripGo")
    wait_cards(s)


def oracle(s, o=None, d=None):
    """The planner's own answer for the same points and names (same page, same mocks)."""
    o = o or dict(O, name="Origin St")
    d = d or dict(D, name="Dest Ave")
    return s.page.evaluate("async ([o, d]) => await window.__SEPTA_TEST__.planTrips(o, d, {})", [o, d])


def cards(s):
    return s.page.evaluate("""() => [...document.querySelectorAll('#tripResults .tp-card')].map(b => ({
        i: +b.dataset.i, min: b.querySelector('.tp-min').textContent, sum: b.querySelector('.tp-l2').textContent,
        pressed: b.getAttribute('aria-pressed'), badges: [...b.querySelectorAll('.tp-badge')].map(x => x.textContent),
        visible: b.offsetParent !== null, text: b.textContent}))""")


def lines(s):
    return s.page.evaluate("[...document.querySelectorAll('#map path.tp-line')].map(p => p.getAttribute('class').replace(/leaflet-\\S+|tp-line/g, '').trim())")


def pins(s):
    return s.page.evaluate("[...document.querySelectorAll('#map .tp-mk')].map(e => e.textContent)")


def card_for(s, word):
    return s.page.locator("#tripResults .tp-card", has_text=word).first


def card_like(s, regex):
    """The card whose mode-summary line matches the regex."""
    return s.page.locator("#tripResults .tp-card").filter(has=s.page.locator(".tp-l2", has_text=re.compile(regex))).first


def expected_sum(o):
    return " · ".join(("Bus " + l["route"]) if l["mode"] == "bus" else ("Drive" if l["mode"] == "car" else l["mode"].capitalize()) + " " + str(l["minutes"]) for l in o["legs"])


def no_errors(s):
    assert not s.console_errors, s.console_errors
    assert not s.unexpected and not s.septa_direct, (s.unexpected, s.septa_direct)


# ------------------------------------------------------------------ (a) form basics and cards
def test_a_form_labels_placement_and_geocoding(root):
    with session() as s:
        boot(s)
        reqs = []
        s.page.on("request", lambda r: reqs.append(r.url) if "nominatim" in r.url else None)
        info = s.page.evaluate("""() => { const sec = document.querySelector('#tripSec');
            return {labelled: sec.getAttribute('aria-labelledby'), h: document.querySelector('#h-trip').textContent,
                prev: sec.previousElementSibling.getAttribute('aria-labelledby'), next: sec.nextElementSibling.getAttribute('aria-labelledby'),
                from: document.querySelector('label[for=tripFrom]').textContent, to: document.querySelector('label[for=tripTo]').textContent,
                ph: [tripFrom.placeholder, tripTo.placeholder], vals: [tripFrom.value, tripTo.value],
                btn: tripGo.textContent, hasLoc: !!document.querySelector('#tripLocate'), hasSwap: !!document.querySelector('#tripSwap'),
                homeBtns: [tripFromHome.hidden, tripToHome.hidden], priv: sec.querySelector('.tp-priv').textContent, attr: document.querySelector('#tripAttr').textContent}; }""")
        assert info["labelled"] == "h-trip" and info["h"] == "Plan a trip"
        assert info["prev"] == "h-find" and info["next"] == "h-places"
        assert (info["from"], info["to"]) == ("From", "To") and info["vals"] == ["", ""]
        assert info["ph"] == ["Start: address or intersection", "Destination: address or intersection"]
        assert info["btn"] == "Plan trip" and info["hasLoc"] and info["hasSwap"] and info["homeBtns"] == [True, True]
        for part in ("go to Photon (photon.komoot.io, OpenStreetMap data)", "rounded to 2 decimals", "A typed From or To address you did not pick from the suggestions", "go to Nominatim (OpenStreetMap) to be looked up", "rounds them to 4 decimals", "saved Home and place buttons", "Use my location and the map center",
                     "exactly the same way as a typed address", "cannot be reached, is an older version", "unrounded, to 5 decimals", "is not a failure and is never re-sent"):
            assert part in info["priv"], part
        assert info["attr"] == "Routing by OSRM / data \u00a9 OpenStreetMap contributors", info["attr"]
        # an intersection gets ", Philadelphia, PA" appended once; text with a comma is sent as typed
        plan_ui(s, "10th & Race", "Dest Ave, Philadelphia")
        from urllib.parse import unquote
        qs = [unquote(u.split("&q=")[1]) for u in reqs]
        assert qs == ["10th & Race, Philadelphia, PA", "Dest Ave, Philadelphia"], qs
        no_errors(s)


def test_a_cards_headline_summary_selection_and_badges(root):
    with session() as s:
        boot(s)
        plan_ui(s)
        res = oracle(s)
        main = [o for o in res["options"] if not o["dominated"]]
        got = [c for c in cards(s) if c["visible"]]
        assert [c["min"] for c in got] == [f"{o['minutes']} min" for o in main], (got, [o["minutes"] for o in main])
        assert [c["sum"] for c in got] == [expected_sum(o) for o in main]
        structures = [o["structure"] for o in main]
        assert "car" in structures and len(structures) >= 3
        # first non-car option is selected, one at a time
        first = next(i for i, o in enumerate(main) if o["structure"] != "car")
        assert main[0]["structure"] == "car" and first == 1, "the car is the quickest here and is not auto-selected"
        assert [c["pressed"] for c in got].count("true") == 1 and got[first]["pressed"] == "true"
        # Fastest sits on the lowest non-car, non-dominated option (first on a tie); Drive on the car
        best = min(o["minutes"] for o in main if o["structure"] != "car")
        fast_i = next(i for i, o in enumerate(main) if o["structure"] != "car" and o["minutes"] == best)
        for i, (c, o) in enumerate(zip(got, main)):
            assert ("Fastest" in c["badges"]) == (i == fast_i), (c, o["structure"])
            assert ("Drive" in c["badges"]) == (o["structure"] == "car")
            if o["structure"] == "car":
                assert "no traffic or parking data" in c["text"]
        assert sum("Fastest" in c["badges"] for c in got) == 1
        word = {"walk": "walk", "walk-bike-walk": "bike"}.get(main[fast_i]["structure"], "bus")
        top = s.page.inner_text("#tripResults .tp-top")
        assert top == f"Fastest without a car: {word}, {res['bestMinutes']} min", top
        # semantics: a labelled group of real buttons, steps in an ordered list, one li per leg
        sem = s.page.evaluate("""() => { const g = document.querySelector('#tripList');
            return {role: g.getAttribute('role'), label: g.getAttribute('aria-label'), tags: [...g.querySelectorAll('.tp-card')].map(b => b.tagName),
                steps: [...document.querySelectorAll('#tripResults ol.tp-steps')].map(o => [o.hidden, [...o.children].filter(c => !c.classList.contains('tp-round')).length])}; }""")
        assert sem["role"] == "group" and sem["label"] == "Trip options" and set(sem["tags"]) == {"BUTTON"}
        legs = [len(o["legs"]) for o in res["options"]]
        assert [n for h, n in sem["steps"]] == legs
        assert [h for h, n in sem["steps"]].count(False) == 1
        no_errors(s)


def test_a_step_wording_for_walk_bike_and_bus(root):
    with session() as s:
        boot(s)
        plan_ui(s)
        res = oracle(s)
        bike = next(o for o in res["options"] if o["structure"] == "walk-bike-walk")
        steps = s.page.evaluate("[...document.querySelectorAll('#tripSteps%d li')].map(l => l.textContent)" % [o["structure"] for o in res["options"]].index("walk-bike-walk"))
        w1, b, w2 = bike["legs"]
        assert steps[0].startswith(f"Walk {w1['minutes']} min, ") and f" from {w1['from']['name']} to {w1['to']['name']}" in steps[0]
        assert steps[1].startswith(f"Bike {b['minutes']} min, ") and " bikes (" in steps[1] and " free docks at " in steps[1]
        assert "min ago" in steps[1] or "under 1 min ago" in steps[1] or " h ago" in steps[1], steps[1]
        assert "mi from" in steps[0]
        st = b["stations"]
        assert re.search(r"Indego counts as of [^:]+: %d bikes \(%d electric\) at %s, %d free docks at %s\." % (
            st["from"]["bikes"], st["from"]["ebikes"], re.escape(st["from"]["name"]), st["to"]["docks"], re.escape(st["to"]["name"])), steps[1]), (steps[1], st)
    # bus legs: live wait wording, then typical wording when no bus is upstream
    with session() as s:
        boot(s, bikes=0)
        plan_ui(s)
        card_for(s, "Bus X47").click()
        txt = s.page.inner_text("#tripResults ol.tp-steps:not([hidden])")
        assert "Bus X47 toward North Terminal" in txt and "stops" in txt
        assert "next bus tracked live, about" in txt and "Ride: " in txt and "scheduled" in txt
    with session() as s:
        boot(s, bikes=0)
        s.worker.data["TransitView"]["bus"][-1]["next_stop_id"] = "S13"   # downstream of the boarding stop
        s.page.reload(); s.wait_live()
        plan_ui(s)
        card_for(s, "Bus X47").click()
        txt = s.page.inner_text("#tripResults ol.tp-steps:not([hidden])")
        assert "waits about 5 min on average (schedule frequency, no bus tracked)" in txt, txt


# ------------------------------------------------------------------ (b) map drawing
def test_b_selection_draws_legs_markers_and_clear_removes(root):
    with session() as s:
        boot(s)
        s.settle()
        veh_before = s.markers()
        assert veh_before > 0 and lines(s) == [] and pins(s) == []
        plan_ui(s)
        s.settle()
        # auto-selected: the quickest non-car option, a walk-bus-walk trip
        assert sorted(lines(s)) == ["tp-bus", "tp-walk", "tp-walk"], lines(s)
        p = pins(s)
        assert sorted(p) == ["Board X47", "End", "Exit X47", "Start"], p
        # a bike option: walk, bike, walk and both Indego stations with their counts
        card_for(s, "Bike ").click()
        assert sorted(lines(s)) == ["tp-bike", "tp-walk", "tp-walk"], lines(s)
        stn = [x["name"] for x in s.mocks.stations()]
        p = pins(s)
        assert "Start" in p and "End" in p and len(p) == 4, p
        assert sum("5 bikes" in x for x in p) == 1 and sum("5 docks" in x for x in p) == 1, p
        assert all(any(n in x for n in stn) for x in p if "bike" in x or "dock" in x)
        assert s.page.evaluate("document.querySelectorAll('.tp-mk').length === document.querySelectorAll('.tp-pin').length")
        # bus again: redrawn, nothing left over from the bike option
        card_for(s, "Bus X47").click()
        assert sorted(lines(s)) == ["tp-bus", "tp-walk", "tp-walk"] and len(pins(s)) == 4
        # car: a single dashed line, only the two end pins
        card_for(s, "Drive").first.click()
        assert lines(s) == ["tp-car"] and sorted(pins(s)) == ["End", "Start"]
        # walk only
        card_like(s, r"^Walk \d+$").click()
        assert lines(s) == ["tp-walk"]
        # a dominated option can be drawn too (bus + bike)
        s.page.locator("#tripMore").click()
        s.page.locator("#tripMoreList .tp-card").first.click()
        assert "tp-bike" in lines(s) and "tp-bus" in lines(s)
        # the vehicle markers are untouched by drawing; Clear removes everything
        assert s.markers() == veh_before
        assert s.page.locator("#tripClear").is_visible()
        s.page.click("#tripClear")
        assert lines(s) == [] and pins(s) == []
        assert s.page.locator("#tripResults").is_hidden() and s.page.locator("#tripResults .tp-card").count() == 0
        assert s.markers() == veh_before
        no_errors(s)


def test_b_line_styles_are_distinct(root):
    with session() as s:
        boot(s)
        plan_ui(s)
        js = """(c) => { const cs = getComputedStyle(document.querySelector('#map path.tp-' + c));
            return [cs.stroke, parseFloat(cs.strokeWidth), cs.strokeDasharray, cs.fill]; }"""
        bus, walk = s.page.evaluate(js, "bus"), s.page.evaluate(js, "walk")
        card_for(s, "Bike ").click()
        bike = s.page.evaluate(js, "bike")
        card_for(s, "Drive").first.click()
        car = s.page.evaluate(js, "car")
        assert len({bus[0], walk[0], bike[0], car[0]}) == 4, (bus, walk, bike, car)
        assert walk[2] != "none" and bike[2] == "none" and bus[2] == "none" and car[2] != "none"
        assert bus[1] > bike[1] >= car[1] > walk[1] - 1
        assert all(v[3] == "none" for v in (bus, walk, bike, car))
        pal = s.page.evaluate("[...['--subway', '--trolley']].map(k => getComputedStyle(document.documentElement).getPropertyValue(k).trim().toLowerCase())")
        assert not ({walk[0], bike[0], bus[0], car[0]} & set(pal))


# ------------------------------------------------------------------ (c) refresh behaviour
def test_c_refresh_keeps_plan_selection_and_markers(root):
    with session() as s:
        boot(s)
        plan_ui(s)
        card_for(s, "Bike ").click()
        s.settle()
        s.page.evaluate("document.querySelectorAll('.veh-wrap').forEach((e, i) => { e.dataset.mark = i })")
        before = (lines(s), pins(s), [c["pressed"] for c in cards(s)])
        routing = len(s.mocks.routing_hits)
        s.page.evaluate("window.__lineEl = document.querySelector('#map path.tp-line')")
        pane = s.page.evaluate("document.querySelector('.leaflet-map-pane').style.transform")
        hits = len(s.worker.hits)
        for b in s.worker.data["TransitView"]["bus"]:
            b["timestamp"] = int(b["timestamp"]) + 15
        s.tick(15500)
        assert len(s.worker.hits) > hits, "the refresh ran"
        assert (lines(s), pins(s), [c["pressed"] for c in cards(s)]) == before
        assert s.page.evaluate("window.__lineEl === document.querySelector('#map path.tp-line') && window.__lineEl.isConnected"), "plan layers are not rebuilt by a refresh"
        assert s.page.evaluate("document.querySelectorAll('.veh-wrap[data-mark]').length") >= 0.95 * s.markers()
        assert s.page.evaluate("document.querySelector('.leaflet-map-pane').style.transform") == pane, "the view did not move"
        assert len(s.mocks.routing_hits) == routing, "no automatic re-plan"
        assert s.page.locator("#replan").is_visible()
        no_errors(s)


# ------------------------------------------------------------------ (d) disclosure
def test_d_more_options_collapsed_by_default(root):
    with session() as s:
        boot(s)
        plan_ui(s)
        res = oracle(s)
        assert res["hiddenCount"] > 0
        btn = s.page.locator("#tripMore")
        assert btn.inner_text() == f"More options ({res['hiddenCount']} slower)"
        assert btn.get_attribute("aria-expanded") == "false"
        dom = [o for o in res["options"] if o["dominated"]]
        hidden_cards = [c for c in cards(s) if not c["visible"]]
        assert len(hidden_cards) == len(dom) and all("slower than" in c["text"] for c in hidden_cards)
        btn.click()
        assert btn.get_attribute("aria-expanded") == "true"
        shown = [c for c in cards(s) if c["visible"]]
        assert len(shown) == len(res["options"])
        assert all(o["dominatedReason"] in c["text"] for o, c in zip(dom, shown[-len(dom):]))
        btn.click()
        assert btn.get_attribute("aria-expanded") == "false" and s.page.locator("#tripMoreList").is_hidden()
    # no dominated options: no disclosure at all
    with session() as s:
        boot(s, bikes=0)
        plan_ui(s)
        assert s.page.locator("#tripMore").count() == 0


# ------------------------------------------------------------------ (e) map center
def test_e_empty_from_uses_map_center_without_touching_prefs(root):
    with session() as s:
        boot(s)
        prefs_before = s.page.evaluate("localStorage.getItem('septa.prefs.v1')")
        keys_before = s.page.evaluate("JSON.stringify(Object.entries(localStorage))")
        s.page.fill("#tripTo", "Dest Ave")
        s.page.click("#tripGo")
        wait_cards(s)
        assert s.page.input_value("#tripFrom") == "Map center"
        walk = next(h for h in s.mocks.routing_hits if h["profile"] == "foot")
        assert abs(walk["from"][0] - CENTER["lat"]) < 1e-4 and abs(walk["from"][1] - CENTER["lng"]) < 1e-4, walk
        assert s.page.evaluate("localStorage.getItem('septa.prefs.v1')") == prefs_before
        assert s.page.evaluate("JSON.stringify(Object.entries(localStorage))") == keys_before
        assert "Map center" in s.page.inner_text("#tripResults ol.tp-steps:not([hidden])")
        # typing replaces the marker: the text is geocoded again
        s.page.fill("#tripFrom", "Origin St")
        s.page.click("#tripGo")
        s.page.wait_for_function("document.querySelector('#tripResults .tp-card') && !document.querySelector('#tripGo').disabled")
        assert s.page.input_value("#tripFrom") == "Origin St"


# ------------------------------------------------------------------ (f) failures
def test_f_geocode_miss_message_next_to_field(root):
    with session() as s:
        boot(s)
        fill(s, "Origin St", "Nowhere Rd")
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripToErr:not([hidden])")
        err = s.page.locator("#tripToErr")
        assert err.inner_text() == "Couldn't find that address." and err.get_attribute("role") == "alert"
        assert s.page.get_attribute("#tripTo", "aria-describedby") == "tripToErr"
        assert s.page.locator("#tripFromErr").is_hidden() and s.page.get_attribute("#tripFrom", "aria-describedby") is None
        assert not s.page.locator("#tripGo").is_disabled() and s.page.locator("#tripResults .tp-card").count() == 0
        assert s.page.locator("#tripResults").is_hidden()
        # editing the field clears the message; a good address then plans
        s.page.fill("#tripTo", "Dest Ave")
        assert s.page.locator("#tripToErr").is_hidden()
        s.page.click("#tripGo")
        wait_cards(s)
        no_errors(s)


def test_f_routing_failure_message_and_retry(root):
    with session() as s:
        boot(s)
        s.mocks.routing_mode = "abort"
        fill(s)
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripRetry", timeout=15000)
        assert "Couldn't reach the routing service. Try again." in s.page.inner_text("#tripResults")
        assert not s.page.locator("#tripGo").is_disabled(), "the button is never left disabled after a failure"
        assert s.page.locator("#tripResults .tp-card").count() == 0 and lines(s) == []
        s.mocks.routing_mode = "ok"
        s.page.click("#tripRetry")
        wait_cards(s)
        assert s.page.locator("#tripRetry").count() == 0 and s.page.locator("#replan").is_visible()


def test_f_network_unavailable_degrades_with_note(root):
    with session() as s:
        boot(s)
        s.mocks.network_mode = "http500"
        plan_ui(s)
        assert "Bus schedule data unavailable, bus options hidden." in s.page.inner_text("#tripResults")
        assert not [c for c in cards(s) if "Bus" in c["sum"]]


def test_f_late_response_of_superseded_request_is_ignored(root):
    with session() as s:
        boot(s)
        held = []

        def gate(route):
            if "/route/foot" in route.request.url and "from=39.94000,-75.15824&to=39.95750,-75.15824" in route.request.url:     # plan 1's walking route (via the Worker); plan 2 goes to D2
                held.append(route)
            else:
                route.fallback()
        s.page.route("**/septa-proxy.tpgordon8.workers.dev/route/**", gate)
        fill(s, "Origin St", "Dest Ave")
        s.page.click("#tripGo")
        for _ in range(100):
            if held:
                break
            s.page.wait_for_timeout(50)
        assert len(held) == 1 and s.page.locator("#tripGo").is_disabled()
        assert s.page.get_attribute("#tripResults", "aria-busy") == "true" and "Planning..." in s.page.inner_text("#tripResults")
        # while busy the form cannot be submitted again (wait until the paced routing queue has drained: its calls are 250 ms apart)
        s.page.wait_for_timeout(5000)
        n = len(s.mocks.routing_hits)
        s.page.evaluate("document.querySelector('#tripForm').requestSubmit()")
        s.page.wait_for_timeout(200)
        assert len(s.mocks.routing_hits) == n and len(held) == 1
        # supersede: clear, then plan somewhere else
        s.page.click("#tripClear")
        assert not s.page.locator("#tripGo").is_disabled()
        fill(s, "Origin St", "Other Ave")
        s.page.click("#tripGo")
        wait_cards(s)
        shown = s.page.inner_text("#tripResults")
        for r in held:          # now the first request finally gets its answer
            r.fallback()
        s.page.wait_for_timeout(1500)
        assert s.page.inner_text("#tripResults") == shown, "the late answer of the superseded request must not replace the new results"
        assert s.page.get_attribute("#tripResults", "aria-busy") == "false" and not s.page.locator("#tripGo").is_disabled()
        ends = s.page.evaluate("[...document.querySelectorAll('#tripResults ol.tp-steps:not([hidden]) li')].map(l => l.textContent)")
        assert any("Other Ave" in x for x in ends) or any("End" in x for x in pins(s))
        no_errors(s)


# ------------------------------------------------------------------ (g) saved places
def test_g_home_and_saved_place_shortcuts(root):
    places = {"home": {"name": "Home Base", "lat": D2["lat"], "lng": D2["lng"]},
              "list": [{"id": f"p{i}", "name": f"Place {i}", "lat": 39.95 + i / 1000, "lng": -75.16} for i in range(8)]}
    seed = f"try {{ localStorage.setItem('septa.places.v1', {json.dumps(json.dumps(places))}); }} catch (e) {{}}"
    with session(init_scripts=[HOOK, SEED_PREFS, seed]) as s:
        boot(s)
        reqs = []
        s.page.on("request", lambda r: reqs.append(r.url) if "nominatim" in r.url else None)
        assert s.page.locator("#tripFromHome").is_visible() and s.page.locator("#tripToHome").is_visible()
        chips = s.page.locator("#tripChips button")
        assert chips.count() == 6 and chips.nth(0).inner_text() == "Home" and chips.nth(1).inner_text() == "Place 0"
        s.page.click("#tripToHome")
        assert s.page.input_value("#tripTo") == "Home Base"
        chips.nth(2).click()
        assert s.page.input_value("#tripTo") == "Place 1"
        s.page.click("#tripFromHome")
        assert s.page.input_value("#tripFrom") == "Home Base"
        s.page.click("#tripGo")
        wait_cards(s)
        assert reqs == [], "saved places are used by coordinates, not geocoded"
        walk = next(h for h in s.mocks.routing_hits if h["profile"] == "foot")
        assert abs(walk["from"][0] - D2["lat"]) < 1e-4 and abs(walk["to"][0] - 39.951) < 1e-4
        # swap exchanges text and points
        s.page.click("#tripSwap")
        assert (s.page.input_value("#tripFrom"), s.page.input_value("#tripTo")) == ("Place 1", "Home Base")
        # editing a filled field drops the stored point and geocodes the text
        s.page.fill("#tripTo", "Dest Ave")
        s.page.click("#tripGo")
        s.page.wait_for_function("!document.querySelector('#tripGo').disabled")
        assert len(reqs) == 1
    with session() as s:
        boot(s)
        assert s.page.locator("#tripFromHome").is_hidden() and s.page.locator("#tripToHome").is_hidden() and s.page.locator("#tripChips").is_hidden()


def test_g_use_my_location_and_denial(root):
    with session(geolocation={"latitude": 39.9420, "longitude": -75.1590}) as s:
        boot(s)
        s.page.click("#tripLocate")
        s.page.wait_for_function("document.querySelector('#tripFrom').value === 'Your location'")
        s.page.fill("#tripTo", "Dest Ave")
        s.page.click("#tripGo")
        wait_cards(s)
        walk = next(h for h in s.mocks.routing_hits if h["profile"] == "foot")
        assert abs(walk["from"][0] - 39.9420) < 1e-4
    with session() as s:      # no permission granted: a clear message beside the field
        boot(s)
        s.page.evaluate("Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition: (ok, bad) => bad({code: 1})}, configurable: true})")
        s.page.click("#tripLocate")
        s.page.wait_for_selector("#tripFromErr:not([hidden])")
        assert "Location isn't available here" in s.page.inner_text("#tripFromErr")
        assert not s.page.locator("#tripLocate").is_disabled()


# ------------------------------------------------------------------ (h) nothing stored, nothing injected
def test_h_no_storage_and_names_render_as_text(root):
    evil = "<img src=x onerror=window.__pwn=1>"
    net = copy.deepcopy(NET)
    for sid in ("S5", "S12"):
        net["stops"][sid][2] = evil + " " + sid
    with session() as s:
        boot(s, net=net)
        for i, st in enumerate(s.mocks.stations()):
            st["name"] = f"{evil} stn{i}"
        keys = s.page.evaluate("JSON.stringify(Object.entries(localStorage))")
        plan_ui(s, "Origin St", "Dest Ave")
        s.page.locator("#tripMore").click()
        for i in range(len(cards(s))):
            s.page.locator(f"#tripResults .tp-card[data-i='{i}']").click()
        s.page.wait_for_timeout(200)
        r = s.page.evaluate("""() => ({imgs: document.querySelectorAll('#tripResults img, #map .tp-mk img, #map .tp-mk *[onerror]').length,
            pwn: window.__pwn === undefined, text: document.querySelector('#tripResults').textContent})""")
        assert r["imgs"] == 0 and r["pwn"]
        assert evil in r["text"], "the name is shown literally"
        card_for(s, "Bike ").click()
        assert any(evil in x for x in pins(s)), "station names appear in the map labels as literal text"
        card_for(s, "Bus X47").click()
        assert s.page.evaluate("document.querySelectorAll('.tp-mk img, .tp-mk *[onerror]').length") == 0
        assert s.page.evaluate("JSON.stringify(Object.entries(localStorage))") == keys, "no storage key gains trip data"
        assert s.page.evaluate("JSON.stringify(Object.entries(sessionStorage))") == "[]"
        s.page.click("#tripClear")
        assert s.page.evaluate("JSON.stringify(Object.entries(localStorage))") == keys
        assert "Origin St" in s.page.input_value("#tripFrom"), "the text stays in the form only"
        assert "Origin St" not in s.page.evaluate("JSON.stringify(Object.entries(localStorage))")
        no_errors(s)


# ------------------------------------------------------------------ (i) phone
def test_i_phone_no_horizontal_scroll_touch_targets_and_show_map(root):
    with session(viewport=(390, 844), init_scripts=[HOOK, SEED_PREFS, SV_SPY]) as s:
        boot(s)
        assert s.page.locator("#showMap").count() == 0
        plan_ui(s)
        s.page.locator("#tripMore").click()
        card_for(s, "Bus X47").click()
        m = s.page.evaluate("""() => ({doc: document.documentElement.scrollWidth - innerWidth, body: document.body.scrollWidth - innerWidth,
            panel: document.querySelector('#panel').scrollWidth - document.querySelector('#panel').clientWidth,
            small: [...document.querySelectorAll('#tripSec button, #tripSec input')].filter(e => e.offsetParent !== null).map(e => [e.id || e.textContent, e.getBoundingClientRect().height]).filter(x => x[1] < 39.5)})""")
        assert m["doc"] <= 0 and m["body"] <= 0 and m["panel"] <= 0, m
        assert m["small"] == [], m["small"]
        sv = s.page.evaluate("window.__sv")
        assert len(sv) == 1 and sv[0]["id"] == "map", "shown automatically once after the first plan on a phone"
        s.page.click("#replan")
        s.page.wait_for_function("document.querySelector('#tripResults .tp-card') && !document.querySelector('#tripGo').disabled")
        assert len(s.page.evaluate("window.__sv")) == 1, "not repeated after the next plan"
        s.page.click("#showMap")
        sv = s.page.evaluate("window.__sv")
        assert len(sv) == 2 and sv[1]["id"] == "map" and sv[1]["a"]["behavior"] == "smooth"
        s.page.emulate_media(reduced_motion="reduce")
        s.page.click("#showMap")
        assert s.page.evaluate("window.__sv")[2]["a"]["behavior"] == "auto", "no smooth scroll under prefers-reduced-motion"
        # the plan is on the map, inside the visible map box
        box = s.page.evaluate("(() => { const r = document.querySelector('#map').getBoundingClientRect(); return [r.top, r.bottom, r.width]; })()")
        assert box[2] == 390 and box[0] >= 0 and box[1] <= 844
        assert s.page.evaluate("[...document.querySelectorAll('#map .tp-mk')].every(e => { const r = e.getBoundingClientRect(); return r.right > 0 && r.left < 390; })")
        no_errors(s)


def test_i_desktop_does_not_auto_scroll(root):
    with session(init_scripts=[HOOK, SEED_PREFS, SV_SPY]) as s:
        boot(s)
        plan_ui(s)
        assert s.page.evaluate("window.__sv") == []


# ------------------------------------------------------------------ (j) focus and live region
def test_j_focus_moves_to_heading_once_and_summary_announced_once(root):
    with session() as s:
        boot(s)
        s.page.evaluate("""() => { window.__live = 0; window.__focusH = 0;
            new MutationObserver(m => { window.__live += m.length; }).observe(document.querySelector('#tripLive'), {childList: true, characterData: true, subtree: true});
            document.addEventListener('focusin', e => { if (e.target.id === 'tripHeading') window.__focusH++; }); }""")
        a = s.page.evaluate("document.querySelector('#tripLive')")
        assert s.page.get_attribute("#tripLive", "aria-live") == "polite" and s.page.get_attribute("#tripLive", "role") == "status"
        assert "sr-only" in s.page.get_attribute("#tripLive", "class") and not s.page.evaluate("document.querySelector('#tripResults').contains(document.querySelector('#tripLive'))")
        plan_ui(s)
        res = oracle(s)
        assert s.page.evaluate("document.activeElement.id") == "tripHeading" and s.page.get_attribute("#tripHeading", "tabindex") == "-1"
        n = len(res["options"])
        assert s.page.inner_text("#tripLive") == f"{n} trip options, fastest {res['bestMinutes']} minutes", s.page.inner_text("#tripLive")
        assert s.page.evaluate("[window.__live, window.__focusH]") == [2, 1], "one 'Planning your trip', then one summary"
        card_for(s, "Drive").first.click()
        s.page.locator("#tripMore").click()
        for b in s.worker.data["TransitView"]["bus"]:
            b["timestamp"] = int(b["timestamp"]) + 15
        s.tick(15500)
        s.page.keyboard.press("Escape")
        assert s.page.evaluate("[window.__live, window.__focusH]") == [2, 1], "selection, refresh and Escape neither re-announce nor move focus"
        assert s.page.locator("#tripResults .tp-card[aria-pressed=true]").count() == 1
        # a new plan announces and focuses once more
        s.page.click("#replan")
        s.page.wait_for_function("document.activeElement.id === 'tripHeading'")
        assert s.page.evaluate("[window.__live, window.__focusH]") == [4, 2]


# ------------------------------------------------------------------ (k) idle pause
def test_k_plans_while_idle_paused_without_resuming_refresh(root):
    with session() as s:
        boot(s)
        s.page.clock.fast_forward(61 * 60000)
        s.tick(15000)
        assert s.page.locator("#idleBar").is_visible()
        # a poll that was already in flight when the page went idle can land just after the fast-forward and leave the feed
        # fresh; let it land, then age the feed past the drop threshold so "bus feed unavailable" below is deterministic
        s.settle()
        s.page.clock.fast_forward(5 * 60000)
        assert s.page.locator("#idleBar").is_visible()
        hits = len(s.worker.hits)
        s.page.evaluate("""() => { tripFrom.value = 'Origin St'; tripTo.value = 'Dest Ave'; document.querySelector('#tripForm').requestSubmit(); }""")
        wait_cards(s)
        assert s.page.locator("#idleBar").is_visible(), "planning is not a user interaction that resumes the refresh"
        s.page.evaluate("document.querySelector('#replan').click()")
        s.page.wait_for_function("!document.querySelector('#tripGo').disabled && document.querySelector('#tripResults .tp-card')")
        s.tick(15000)
        assert len(s.worker.hits) == hits, "planning itself makes no Worker request"
        text = s.page.inner_text("#tripResults")
        assert "Live bus data unavailable, bus options hidden." in text, text
        assert [c for c in cards(s) if c["visible"]], "walk and car options are still there"
        assert s.page.locator("#idleBar").is_visible()
        # a real interaction resumes it as usual
        s.page.click("#resumeBtn")
        assert s.page.locator("#idleBar").is_hidden()


# ------------------------------------------------------------------ staleness
def test_staleness_line_and_replan_uses_fresh_data(root):
    with session() as s:
        boot(s)
        plan_ui(s)
        txt = s.page.inner_text("#tripResults")
        import re
        assert re.search(r"Planned at \d{1,2}:\d{2}", txt) and "Bike counts and bus waits change quickly; re-plan before you leave." in txt
        n_status = s.mocks.indego_hits.count("station_status")
        s.mocks.set_all(bikes=0, docks=0)
        s.page.click("#replan")
        s.page.wait_for_function("document.querySelector('#tripResults').getAttribute('aria-busy') === 'false' && document.querySelector('#replan') && !document.querySelector('#tripGo').disabled")
        assert s.mocks.indego_hits.count("station_status") == n_status + 1, "fresh Indego status for the re-plan"
        assert not [c for c in cards(s) if "Bike" in c["sum"]], "the new counts removed the bike option"
        assert s.page.input_value("#tripTo") == "Dest Ave"
        # nothing re-plans on its own
        n = len(s.mocks.routing_hits)
        s.tick(60000)
        assert len(s.mocks.routing_hits) == n
        # the previous map view is not restored and the center is not moved
        assert s.page.evaluate("JSON.parse(localStorage.getItem('septa.prefs.v1')).center.lat") == CENTER["lat"]


# ------------------------------------------------------------------ (l) smoke with the real data file
def test_l_real_network_smoke_center_city(root):
    with session() as s:
        s.mocks.set_all(bikes=4, docks=4)
        s.open()
        s.wait_live()
        assert s.mocks.network is None
        nom = {"q=City": geo(39.9526, -75.1652, "City Hall"), "q=Independence": geo(39.9496, -75.1503, "Independence Hall")}
        s.extra_routes.update(nom)
        plan_ui(s, "City Hall", "Independence Hall")
        got = cards(s)
        txt = " ".join(c["sum"] for c in got)
        assert any("Drive" in c["badges"] for c in got)
        assert "Walk" in txt or "Bike" in txt
        assert s.mocks.network_hits == 1
        assert lines(s) and "Start" in pins(s)
        no_errors(s)


# ------------------------------------------------------------------ (k) WP2: planner notes, schedule line, view restore, phone
FAIL_S12 = """() => { const f = window.fetch; window.fetch = function (u, o) {
    if (String(u).includes('route/v1/driving/-75.15800,39.95750;') || String(u).includes('/route/') && String(u).includes('from=39.95750,-75.15800&')) return Promise.resolve(new Response('{}', {status: 500}));
    return f.call(window, u, o); }; }"""
NO_ROUTE_FOOT = """() => { const f = window.fetch; window.fetch = function (u, o) {
    if (String(u).includes('routed-foot')) window.__direct = (window.__direct || 0) + 1;
    if (String(u).includes('/route/foot') || String(u).includes('routed-foot')) return Promise.resolve(new Response('{"code":"NoRoute","message":"Impossible route between points"}', {status: String(u).includes('/route/foot') ? 422 : 400, headers: {'content-type': 'application/json'}}));
    return f.call(window, u, o); }; }"""


def set_today(s, ymd):
    s.page.evaluate("(d) => { window.__SEPTA_TEST__.TP.today = d; }", ymd)


def note_texts(s):
    return s.page.evaluate("Object.fromEntries([...document.querySelectorAll('#tripResults [data-code]')].map(p => [p.dataset.code, p.textContent]))")


def test_k_each_planner_note_has_its_own_sentence(root):
    got = {}
    with session() as s:                                        # routing_limit
        boot(s, bikes=0)
        set_today(s, "20260601")
        s.page.evaluate("window.__SEPTA_TEST__.TP.MAX_CALLS = 3")
        plan_ui(s)
        got["routing_limit"] = note_texts(s)
        no_errors(s)
    with session() as s:                                        # routing_failed
        boot(s, bikes=0)
        set_today(s, "20260601")
        s.page.evaluate(FAIL_S12)
        plan_ui(s)
        got["routing_failed"] = note_texts(s)
        no_errors(s)
    with session() as s:                                        # no_live_bus
        boot(s, bikes=0, bus_route="ZZ9")
        set_today(s, "20260601")
        plan_ui(s)
        got["no_live_bus"] = note_texts(s)
        assert s.page.locator("#tripResults .tp-card").count() >= 2
        no_errors(s)
    with session() as s:                                        # no_bus_beats_baseline
        boot(s, bikes=0)
        set_today(s, "20260601")
        plan_ui(s, "Origin St", "Near St")
        got["no_bus_beats_baseline"] = note_texts(s)
        no_errors(s)
    with session() as s:                                        # schedule_stale (expired)
        boot(s, bikes=0)
        set_today(s, "20270301")
        plan_ui(s)
        got["schedule_stale"] = note_texts(s)
        no_errors(s)
    want = {
        "routing_limit": "To stay within the free routing service's limits, the planner checked only the most promising bus options, so a slower-looking bus trip may be missing.",
        "routing_failed": "Directions for one bus option could not be loaded, so it was left out. Re-plan to try again.",
        "no_live_bus": "No bus is being tracked right now on route",
        "no_bus_beats_baseline": "Buses run between these points, but none is faster than walking the whole way.",
        "schedule_stale": "The bus schedule data ended on Dec 31, 2026, so bus ride times may be out of date.",
    }
    texts = []
    for code, w in want.items():
        t = got[code].get(code)
        assert t is not None, (code, got[code])
        if code == "routing_failed":
            assert t.startswith("Directions for ") and t.endswith(" left out. Re-plan to try again.") and "could not be loaded" in t, t
        elif code == "no_live_bus":
            assert t.startswith(w) and t.endswith(", so there is no live wait to show for them.") and "X47" in t, t
        else:
            assert t == w, (code, t)
        texts.append(t)
        assert "could not be completed" not in " ".join(got[code].values()), "the generic sentence is gone"
    assert len(set(texts)) == 5, "five distinct sentences"


def test_k_schedule_line_under_options_and_validity_warning(root):
    with session() as s:
        boot(s, bikes=0)
        for today, state in (("20261001", None), ("20261217", "ends"), ("20261231", "ends"), ("20270101", "ended")):
            set_today(s, today)
            plan_ui(s) if s.page.locator("#tripResults .tp-card").count() == 0 else (s.page.click("#replan"), wait_cards(s))
            s.page.wait_for_function("!document.querySelector('#tripGo').disabled")
            line = s.page.locator("#tripSched")
            assert line.inner_text() == "Bus schedule data as of Jan 1, 2026", line.inner_text()
            order = s.page.evaluate("""() => { const kids = [...document.querySelector('#tripResults').children];
                return [kids.indexOf(document.querySelector('#tripSched')), kids.indexOf(document.querySelector('#tripList'))]; }""")
            assert order[0] > order[1] >= 0, "the schedule line sits under the options"
            warn = s.page.locator("#tripResults .tp-warn")
            if state is None:
                assert warn.count() == 0, today
            else:
                assert warn.count() == 1 and warn.is_visible(), today
                txt = warn.inner_text()
                assert "Dec 31, 2026" in txt and ("ended on" in txt if state == "ended" else "ends on" in txt), txt
                if today == "20261217":
                    assert "(in 14 days)" in txt, txt
                if today == "20261231":
                    assert "(today)" in txt, txt
        no_errors(s)


def view(s):
    return s.page.evaluate("(() => { const m = window.__SEPTA_TEST__.tripMap, c = m.getCenter(); return {lat: c.lat, lng: c.lng, z: m.getZoom()}; })()")


def same_view(a, b):
    return abs(a["lat"] - b["lat"]) < 1e-6 and abs(a["lng"] - b["lng"]) < 1e-6 and a["z"] == b["z"]


def test_k_clear_trip_restores_the_map_view_from_before_the_plan(root):
    with session() as s:
        boot(s)
        s.page.emulate_media(reduced_motion="reduce")
        s.page.evaluate("window.__SEPTA_TEST__.tripMap.setView([39.97, -75.19], 12, {animate: false})")
        s.settle()
        before = view(s)
        plan_ui(s)
        s.settle()
        planned = view(s)
        assert not same_view(before, planned), "the plan was fitted to the map"
        # picking another option refits, but Clear still returns to the view from before the plan
        card_for(s, "Bike ").click()
        s.settle()
        card_for(s, "Bus X47").click()
        s.settle()
        s.page.click("#replan")
        s.page.wait_for_function("document.querySelector('#tripResults .tp-card') && !document.querySelector('#tripGo').disabled")
        s.settle()
        s.page.evaluate("window.__SEPTA_TEST__.tripMap.setView([39.9, -75.1], 15, {animate: false})")
        s.page.click("#tripClear")
        s.settle()
        assert same_view(view(s), before), (view(s), before)
        # a second plan and clear starts from wherever the map is then
        s.page.evaluate("window.__SEPTA_TEST__.tripMap.setView([39.95, -75.17], 13, {animate: false})")
        mid = view(s)
        plan_ui(s)
        s.page.click("#tripClear")
        s.settle()
        assert same_view(view(s), mid)
        # clearing with nothing drawn leaves the map alone
        s.page.evaluate("window.__SEPTA_TEST__.tripMap.setView([39.96, -75.2], 11, {animate: false})")
        no_errors(s)


def test_k_no_trip_found_state(root):
    with session() as s:
        boot(s, bikes=0)
        s.page.emulate_media(reduced_motion="reduce")
        s.page.evaluate(NO_ROUTE_FOOT)
        s.settle()
        before = view(s)
        fill(s)
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripNone", timeout=15000)
        msg = s.page.locator("#tripNone")
        assert msg.inner_text() == "No trip found. Try different points." and msg.get_attribute("role") == "alert"
        assert not s.page.evaluate("window.__direct"), "the Worker's 422 NoRoute answer is final: nothing is re-sent to the provider"
        assert s.page.evaluate("document.activeElement.id") == "tripNone"
        assert s.page.locator("#tripResults .tp-card").count() == 0 and s.page.locator("#tripRetry").count() == 0
        assert lines(s) == [] and pins(s) == [] and not s.page.locator("#tripGo").is_disabled()
        assert s.page.get_attribute("#tripResults", "aria-busy") == "false"
        assert same_view(view(s), before)
        # an unreachable routing service is the other failure, with Retry
        s.page.evaluate("() => { const f = window.fetch; window.fetch = function (u, o) { if (String(u).includes('routing.openstreetmap.de') || String(u).includes('/route/')) return Promise.resolve(new Response('{}', {status: 500})); return f.call(window, u, o); }; window.__SEPTA_TEST__.resetPlannerCaches(); }")
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripRetry", timeout=20000)
        assert s.page.locator("#tripNone").count() == 0 and "routing service" in s.page.inner_text("#tripResults")


def test_k_phone_map_size_and_show_on_map(root):
    for size in ((390, 844), (360, 640), (320, 568), (480, 800)):
        with session(viewport=size, init_scripts=[HOOK, SEED_PREFS, SV_SPY]) as s:
            boot(s)
            s.page.emulate_media(reduced_motion="reduce")
            plan_ui(s)
            s.settle()
            h = s.page.evaluate("document.querySelector('#map').getBoundingClientRect().height")
            assert h >= 0.45 * size[1], (size, h)
            assert h >= 0.49 * size[1], ("the map gets half the phone screen while planning", size, h)
            sv0 = len(s.page.evaluate("window.__sv"))
            # pan the map far away, then Show on map: it scrolls to the map and refits the plan
            planned = view(s)
            s.page.evaluate("window.__SEPTA_TEST__.tripMap.setView([39.6, -75.6], 9, {animate: false})")
            s.page.click("#showMap")
            s.settle()
            sv = s.page.evaluate("window.__sv")
            assert len(sv) == sv0 + 1 and sv[-1]["id"] == "map" and sv[-1]["a"]["block"] == "start", sv[-1]
            assert same_view(view(s), planned), (view(s), planned)
            if size == (390, 844):
                s.shot("wp2_phone_after")
    with session(viewport=(700, 900), init_scripts=[HOOK, SEED_PREFS, SV_SPY]) as s:
        boot(s)
        plan_ui(s)
        s.page.click("#showMap")
        assert s.page.evaluate("window.__sv")[-1]["a"]["block"] == "nearest", "between 481 and 820 px behaviour is unchanged"


# ------------------------------------------------------------------ (s) WP5: region check, geocode pacing, a11y, cancel, rounding
OUT_MSG = "That place is outside the area this planner covers (Philadelphia region)."


def no_network_calls(s):
    m = s.mocks
    return m.worker_route_hits == [] and m.direct_routing_hits == [] and m.worker_indego_hits == [] and m.direct_indego_hits == []


def test_s_out_of_region_is_refused_before_any_call(root):
    places = {"home": {"name": "Far Home", "lat": 40.7357, "lng": -74.1724}, "list": []}
    seed = f"try {{ localStorage.setItem('septa.places.v1', {json.dumps(json.dumps(places))}); }} catch (e) {{}}"
    with session(init_scripts=[HOOK, SEED_PREFS, seed]) as s:
        boot(s)
        s.mocks.worker_route_hits.clear(); s.mocks.worker_indego_hits.clear(); s.mocks.direct_routing_hits.clear(); s.mocks.direct_indego_hits.clear()
        # a typed place outside the box
        fill(s, "Origin St", "Newark")
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripToErr:not([hidden])", timeout=15000)
        assert s.page.inner_text("#tripToErr") == OUT_MSG and s.page.locator("#tripFromErr").is_hidden()
        assert s.page.locator("#tripRetry").count() == 0 and s.page.locator("#tripResults").is_hidden()
        assert s.page.evaluate("document.activeElement.id") == "tripTo", "focus goes to the field with the problem"
        assert not s.page.locator("#tripGo").is_disabled() and s.page.evaluate("document.querySelector('#tripLive').textContent") == ""
        assert no_network_calls(s), "no routing or Indego call for a place outside the region"
        # a saved Home outside the box (used by coordinates, never geocoded)
        s.page.click("#tripFromHome")
        s.page.fill("#tripTo", "Dest Ave")
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripFromErr:not([hidden])", timeout=15000)
        assert s.page.inner_text("#tripFromErr") == OUT_MSG and s.page.locator("#tripToErr").is_hidden()
        assert s.page.locator("#tripRetry").count() == 0 and no_network_calls(s)
        # an inside place still plans
        s.page.fill("#tripFrom", "Origin St")
        s.page.click("#tripGo")
        wait_cards(s)
        no_errors(s)


def test_s_geocode_is_sequential_and_cached(root):
    import time
    with session() as s:
        boot(s)
        t = []
        s.page.on("request", lambda r: t.append(time.monotonic()) if "nominatim" in r.url else None)
        plan_ui(s, "Origin St", "Dest Ave")
        assert len(t) == 2 and t[1] - t[0] >= 1.0, ("From, then To, at least a second apart", t)
        s.page.click("#tripClear")
        plan_ui(s, "  origin   ST ", "dest ave")
        assert len(t) == 2, "answers are cached for the session, case and spacing ignored"
        # a miss is cached too; failures are not
        fill(s, "Origin St", "Nowhere Rd")
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripToErr:not([hidden])")
        n = len(t)
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripToErr:not([hidden])")
        assert len(t) == n, "the miss is remembered"


def test_s_announce_planning_and_move_focus(root):
    with session() as s:
        boot(s)
        s.page.evaluate("""() => { const f = window.fetch; window.fetch = function (u, o) {
            if (String(u).includes('/route/')) return new Promise(r => setTimeout(r, 1500)).then(() => f.call(window, u, o));
            return f.call(window, u, o); }; }""")
        fill(s)
        s.page.click("#tripGo")
        s.page.wait_for_function("document.querySelector('#tripLive').textContent === 'Planning your trip'", timeout=5000)
        assert s.page.get_attribute("#tripLive", "aria-live") == "polite" and s.page.get_attribute("#tripLive", "role") == "status"
        wait_cards(s)
        assert s.page.evaluate("document.activeElement.id") == "tripHeading", "focus moves to the results heading"
        assert "trip option" in s.page.inner_text("#tripLive") and "Planning" not in s.page.inner_text("#tripLive")
        # failure: focus goes to the error message, whose Retry control follows it
        s.page.evaluate("""() => { window.fetch = function (u, o) { if (String(u).includes('/route/')) return Promise.resolve(new Response('{}', {status: 500})); return Promise.reject(new Error('x')); };
            window.__SEPTA_TEST__.resetPlannerCaches(); }""")
        s.page.click("#replan")
        s.page.wait_for_selector("#tripRetry", timeout=20000)
        assert s.page.evaluate("document.activeElement.getAttribute('role') + '|' + document.activeElement.className") == "alert|tp-msg"
        assert s.page.evaluate("document.activeElement.nextElementSibling.id") == "tripRetry"
        assert s.page.inner_text("#tripLive") == ""


def test_s_clear_and_replan_cancel_the_abandoned_plan(root):
    with session() as s:
        boot(s)
        s.page.evaluate("""() => { window.__hang = true; window.__st = {started: 0, aborted: 0}; const f = window.fetch;
            window.fetch = function (u, o) {
                if (window.__hang && String(u).includes('/route/')) { window.__st.started++;
                    return new Promise((res, rej) => o.signal.addEventListener('abort', () => { window.__st.aborted++; rej(new DOMException('x', 'AbortError')); })); }
                return f.call(window, u, o); }; }""")
        fill(s)
        s.page.click("#tripGo")
        s.page.wait_for_function("window.__st.started >= 2", timeout=15000)
        s.page.click("#tripClear")
        s.page.wait_for_function("window.__st.aborted >= 2", timeout=5000)
        n = s.page.evaluate("window.__st.started")
        s.page.wait_for_timeout(1200)
        assert s.page.evaluate("window.__st.started") == n, "queued calls of the cleared plan are dropped, not started later"
        assert not s.page.locator("#tripGo").is_disabled() and s.page.locator("#tripResults").is_hidden()
        # the next plan is not held up by the dead one
        s.page.evaluate("window.__hang = false")
        s.page.click("#tripGo")
        wait_cards(s, timeout=10000)
        no_errors(s)


def test_s_leg_rounding_note_and_total_from_exact_sum(root):
    import math
    with session() as s:
        boot(s)
        plan_ui(s)
        res = oracle(s)
        opts = res["options"]
        for o in opts:
            exact = sum(l["raw"] for l in o["legs"])
            assert o["minutes"] == math.ceil(exact - 1e-9) and abs(o["raw"] - exact) < 1e-9, o["structure"]
        raws = [o["raw"] for o in opts if not o.get("dominated")]
        assert raws == sorted(raws), "options are ranked on the exact sum"
        assert res["bestMinutes"] == math.ceil(min(o["raw"] for o in opts if o["structure"] != "car") - 1e-9)
        assert any(sum(l["minutes"] for l in o["legs"]) != o["minutes"] for o in opts), "scenario must contain a rounding mismatch"
        notes = s.page.evaluate("[...document.querySelectorAll('#tripResults .tp-card')].map(b => { const ol = document.querySelector('#' + b.getAttribute('aria-controls')); const n = ol.querySelector('li.tp-round'); return n ? n.textContent : null; })")
        cards_ = s.page.evaluate("[...document.querySelectorAll('#tripResults .tp-card .tp-min')].map(x => x.textContent)")
        assert len(notes) == len(opts)
        for o, note, shown in zip(opts, notes, cards_):
            leg_sum = sum(l["minutes"] for l in o["legs"])
            assert shown == f"{o['minutes']} min"
            if leg_sum != o["minutes"]:
                assert note and f"add up to {leg_sum} min" in note and f"total of {o['minutes']} min" in note, (o["structure"], note)
            else:
                assert note is None, (o["structure"], note)
        no_errors(s)
