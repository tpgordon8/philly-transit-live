"""Saved Work place beside Home: storage (old data without a work key), the Saved places UI, the Get me to work pill and the trip
planner's Work choices. Hermetic; uses the trip planner helpers."""
import json

from harness import Session
from test_trip_ui import HOOK, SEED_PREFS, boot, nominatim, session, wait_cards

FAST = {
    "test_work_save_rename_clear_ui",
    "test_get_me_to_work_plans_like_home",
    "test_work_in_trip_planner_choices",
    "test_old_places_without_work_load_unchanged",
}

HOME = {"name": "Home", "lat": 39.9300, "lng": -75.1900}
WORK = {"name": "Office", "lat": 39.9570, "lng": -75.1640}
GEO = {"latitude": 39.9560, "longitude": -75.1700}


def seed_places(places):
    return f"try {{ localStorage.setItem('septa.places.v1', {json.dumps(json.dumps(places))}); }} catch (e) {{}}"


def work_session(places, **kw):
    kw.setdefault("extra_routes", nominatim())
    kw["init_scripts"] = [HOOK, SEED_PREFS, seed_places(places)]
    return Session(**kw)


def stored(s):
    return s.page.evaluate("JSON.parse(localStorage.getItem('septa.places.v1'))")


def test_old_places_without_work_load_unchanged(root):
    raw = json.dumps({"home": HOME, "list": [{"id": "p1", "name": "Gym", "lat": 39.95, "lng": -75.16}]})
    with Session(root, init_scripts=[f"try {{ localStorage.setItem('septa.places.v1', {json.dumps(raw)}); }} catch (e) {{}}"]) as s:
        s.open()
        s.wait_live()
        assert s.page.evaluate("localStorage.getItem('septa.places.v1')") == raw, "loading must not rewrite the stored text"
        assert s.page.evaluate("localStorage.getItem('septa.places.v1.bak')") is None, "no backup: nothing was dropped"
        assert s.page.evaluate("[...document.querySelectorAll('#places li .tag, #places li .nm')].map(e => e.textContent)") == ["Home", "Home", "Gym"]
        assert s.page.locator("#btnWork").is_visible() and s.page.get_attribute("#btnWork", "aria-disabled") == "true"
        assert not s.console_errors, s.console_errors


def test_work_save_rename_clear_ui(root):
    with session() as s:
        boot(s)
        assert s.page.get_attribute("#btnWork", "aria-disabled") == "true"
        assert s.page.get_attribute("#btnWork", "title") == "Set a Work place in More first"
        assert s.page.inner_text("#workHelp") == "Set a Work place to use Get me to work" and s.page.locator("#workHelp").is_visible()
        s.page.evaluate("window.SEPTA.sheet.reveal(document.querySelector('#placeName'))")
        s.page.wait_for_selector("#saveForm:not([hidden])")
        s.page.fill("#placeName", "Office")
        s.page.click("#btnSaveWork")
        w = stored(s)["work"]
        assert w["name"] == "Office" and abs(w["lat"] - 39.94) < 1e-6 and abs(w["lng"] + 75.15) < 1e-6
        assert s.page.get_attribute("#btnWork", "aria-disabled") is None and s.page.locator("#workHelp").is_hidden()
        assert s.page.locator("#places li .tag").all_text_contents() == ["Work"]
        # saving again under another name renames it
        s.page.fill("#placeName", "HQ")
        s.page.click("#btnSaveWork")
        assert stored(s)["work"]["name"] == "HQ" and s.page.locator("#places li").count() == 1
        # a saved place can be promoted to Work, and Home stays separate
        s.page.click("#btnSave")
        s.page.click("#places button[aria-label^='Set as Work: ']")
        assert stored(s)["work"]["name"] == "HQ" and stored(s).get("home") is None
        s.page.click("#places button[aria-label='Remove Work']")
        assert stored(s)["work"] is None and s.page.get_attribute("#btnWork", "aria-disabled") == "true"
        assert s.page.locator("#workHelp").is_visible()
        assert not s.console_errors, s.console_errors


def test_get_me_to_work_plans_like_home(root):
    places = {"home": HOME, "work": WORK, "list": []}
    with work_session(places, geolocation=GEO) as s:
        boot(s)
        btn = s.page.locator("#btnWork")
        assert btn.inner_text() == "Get me to work" and btn.is_visible()
        assert s.page.evaluate("document.querySelector('#btnHome').nextElementSibling.id") == "btnWork", "beside Get me home"
        assert btn.bounding_box()["height"] >= 44
        btn.click()
        wait_cards(s)
        assert s.page.input_value("#tripFrom") == "Your location" and s.page.input_value("#tripTo") == "Office"
        assert any(abs(h["to"][0] - WORK["lat"]) < 1e-3 and abs(h["to"][1] - WORK["lng"]) < 1e-3 for h in s.mocks.routing_hits)
        assert not s.page.locator("#btnWork").is_disabled()


def test_get_me_to_work_unset_and_no_location(root):
    with session() as s:
        boot(s)
        s.page.click("#btnWork", force=True)  # aria-disabled only: Playwright treats it as not enabled, a person can still tap it
        assert s.page.inner_text("#note") == "Set a Work place in More to use this." and s.mocks.routing_hits == []
        assert s.page.evaluate("getComputedStyle(document.querySelector('#btnWork')).opacity") != "1", "dimmed"
    with work_session({"home": None, "work": WORK, "list": []}) as s:  # no geolocation granted
        boot(s)
        s.page.click("#btnWork")
        s.page.wait_for_selector("#tripFromErr:not([hidden])")
        assert s.page.inner_text("#tripFromErr") == "Add a start to get to work"
        assert s.page.input_value("#tripTo") == "Office" and s.page.input_value("#tripFrom") == ""
        assert s.mocks.routing_hits == []


def test_work_in_trip_planner_choices(root):
    places = {"home": HOME, "work": WORK, "list": [{"id": f"p{i}", "name": f"Place {i}", "lat": 39.95 + i / 1000, "lng": -75.16} for i in range(8)]}
    with work_session(places) as s:
        boot(s)
        s.page.evaluate("window.SEPTA.sheet.reveal(document.querySelector('#tripFrom'))")
        assert s.page.locator("#tripFromWork").is_visible() and s.page.locator("#tripToWork").is_visible()
        chips = s.page.locator("#tripChips button")
        assert chips.count() == 6 and chips.nth(0).inner_text() == "Home" and chips.nth(1).inner_text() == "Work" and chips.nth(2).inner_text() == "Place 0"
        s.page.click("#tripToWork")
        assert s.page.input_value("#tripTo") == "Office"
        s.page.click("#tripFromWork")
        assert s.page.input_value("#tripFrom") == "Office"
        chips.nth(1).click()
        assert s.page.input_value("#tripTo") == "Office"
    with session() as s:
        boot(s)
        assert s.page.locator("#tripFromWork").is_hidden() and s.page.locator("#tripToWork").is_hidden()
