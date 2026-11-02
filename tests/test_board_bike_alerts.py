"""Low-bikes and no-free-docks warnings on the wall board's Indego tiles (js/boardbikes.js, js/boardbikesview.js, js/boardsettings.js;
ARCHITECTURE.md 16.3): the extended septa.boardbikes.v1 schema (old data still loads and is cleaned), the rows() warnings, the text badge on the
tile, one polite announcement per change, no warning on stale or failed data, no new requests or storage keys, and the settings controls."""
import json

from harness import Session
from test_first_run import must_fail, seed
from test_board_bikes import (HOOK, KEY, MIN, NOON, ID_WOLF, ID_SNYDER, WOLF, SNYDER, bsess, open_board, js, rows, tile, tiles_text, set_types,
                              status_hits, fresh, prep)

FAST = {
    "test_old_data_loads_and_new_fields_are_cleaned",
    "test_set_alert_validates_and_saves",
    "test_warning_badges_and_one_announcement_per_change",
    "test_no_warning_on_stale_or_failed_data",
    "test_settings_controls_set_and_clear_the_warnings",
}


def picks_with(*items):
    return seed(KEY, {"stations": [dict(id=i, name=n, **extra) for i, n, extra in items]})


def say_text(s):
    return s.page.inner_text("#bvLive").strip()


def clear_say(s):
    s.page.evaluate("document.getElementById('bvLive').textContent = ''")


# ---------------------------------------------------------------- schema

def check_schema(root):
    # data saved before the warnings existed: unchanged, no backup, warnings off
    old = {"stations": [{"id": ID_WOLF, "name": "4th & Wolf"}]}
    with Session(root, init_scripts=[HOOK, seed(KEY, old)]) as s:
        s.open()
        s.wait_live()
        assert js(s, "window.SEPTA.boardbikes.stations()") == old["stations"]
        assert s.page.evaluate("localStorage.getItem('septa.boardbikes.v1.bak')") is None
        r = rows(s)[0]
        assert r["lowBikes"] is None and r["noDocks"] is False and r["warn"] == [], r
    # good values round-trip and leave no backup
    good = {"stations": [{"id": "a1", "name": "A", "lowBikes": 0}, {"id": "b2", "name": "B", "lowBikes": 5, "noDocks": True},
                         {"id": "c3", "name": "C", "noDocks": True}]}
    with Session(root, init_scripts=[HOOK, seed(KEY, good)]) as s:
        s.open()
        s.wait_live()
        assert js(s, "window.SEPTA.boardbikes.stations()") == good["stations"]
        assert s.page.evaluate("localStorage.getItem('septa.boardbikes.v1.bak')") is None
    # bad values read as off, and the original is copied to .bak first (each field on its own, so each check has to notice it)
    bad_low = {"stations": [{"id": "a1", "name": "A", "lowBikes": 6}, {"id": "b2", "name": "B", "lowBikes": "2"}, {"id": "c3", "name": "C", "lowBikes": 1.5},
                            {"id": "d4", "name": "D", "lowBikes": -1}]}
    bad_docks = {"stations": [{"id": "a1", "name": "A", "noDocks": "yes"}, {"id": "b2", "name": "B", "noDocks": 1}]}
    for bad in (bad_low, bad_docks):
        with Session(root, init_scripts=[HOOK, seed(KEY, bad)]) as s:
            s.open()
            s.wait_live()
            assert js(s, "window.SEPTA.boardbikes.stations()") == [{"id": x["id"], "name": x["name"]} for x in bad["stations"]]
            bak = s.page.evaluate("localStorage.getItem('septa.boardbikes.v1.bak')")
            assert bak and json.loads(bak) == bad, "the lossy original is kept before a save"
            assert not s.console_errors, s.console_errors


def test_old_data_loads_and_new_fields_are_cleaned(root):
    check_schema(root)
    must_fail(check_schema, root, ("js/boardbikes.js", "n >= 0 && n <= MAX_LOW", "n >= 0 && n <= 99"))
    must_fail(check_schema, root, ("js/boardbikes.js", "(o.lowBikes != null && o.lowBikes !== s.lowBikes) ||", ""))
    must_fail(check_schema, root, ("js/boardbikes.js", "(o.noDocks != null && o.noDocks !== s.noDocks)", "false"))


# ---------------------------------------------------------------- setAlert

def check_set_alert(root):
    with bsess(root, picked=(WOLF, SNYDER)) as s:
        s.open()
        s.wait_live()
        call = lambda e: js(s, "window.SEPTA.boardbikes." + e)
        keys_before = s.page.evaluate("Object.keys(localStorage).sort()")
        assert call("setAlert('nope', {lowBikes: 1})") is False
        assert call("setAlert('" + ID_WOLF + "', {lowBikes: 6})") is False
        assert call("setAlert('" + ID_WOLF + "', {lowBikes: 1.5})") is False
        assert call("setAlert('" + ID_WOLF + "', {noDocks: 'yes'})") is False
        assert call("setAlert('" + ID_WOLF + "', 7)") is False
        assert call("stations()")[0] == {"id": ID_WOLF, "name": "4th & Wolf"}, "a refused change changes nothing"
        assert call("setAlert('" + ID_WOLF + "', {lowBikes: 0, noDocks: true})") is True
        assert call("stations()")[0] == {"id": ID_WOLF, "name": "4th & Wolf", "lowBikes": 0, "noDocks": True}
        assert call("setAlert('" + ID_WOLF + "', {lowBikes: 3})") is True
        assert call("stations()")[0] == {"id": ID_WOLF, "name": "4th & Wolf", "lowBikes": 3, "noDocks": True}, "a key left out is kept"
        assert json.loads(s.page.evaluate("localStorage.getItem('septa.boardbikes.v1')"))["stations"][0] == {"id": ID_WOLF, "name": "4th & Wolf", "lowBikes": 3, "noDocks": True}
        assert call("setAlert('" + ID_WOLF + "', {lowBikes: null, noDocks: false})") is True
        assert call("stations()")[0] == {"id": ID_WOLF, "name": "4th & Wolf"}, "off is stored as absent"
        assert s.page.evaluate("Object.keys(localStorage).sort()") == keys_before, "no new storage key"


def test_set_alert_validates_and_saves(root):
    check_set_alert(root)
    must_fail(check_set_alert, root, ("js/boardbikes.js", "!isLow(o.lowBikes)) return false;", "false) return false;"))


# ---------------------------------------------------------------- badges and announcements

def check_badges(root):
    items = [(ID_WOLF, "4th & Wolf", {"lowBikes": 2, "noDocks": True}), (ID_SNYDER, "2nd & Snyder", {})]
    with Session(root, init_scripts=[HOOK, picks_with(*items)]) as s:
        prep(s)
        set_types(s, ID_WOLF, 1, 0, 0, docks=4)  # 1 bike, at or below 2
        set_types(s, ID_SNYDER, 0, 0, 0, docks=0)  # no thresholds set: nothing
        open_board(s)
        t = tiles_text(s)
        assert "Low: 1 bike left" in t[0] and "No free docks" not in t[0], t[0]
        assert "Low:" not in t[1] and "No free docks" not in t[1], t[1]
        assert tile(s, 0).get_attribute("aria-label").startswith("Indego 4th and Wolf, Low: 1 bike left, "), tile(s, 0).get_attribute("aria-label")
        assert tile(s, 0).get_attribute("data-warn") == "1" and tile(s, 1).get_attribute("data-warn") is None
        s.page.wait_for_function("document.getElementById('bvLive').textContent.includes('Low: 1 bike left')", timeout=4000)
        assert say_text(s) == "Indego 4th and Wolf: Low: 1 bike left", say_text(s)
        # unchanged polls say nothing more
        clear_say(s)
        fresh(s, 10, page_clock=True)
        s.tick(MIN + 5000)
        s.tick(MIN + 5000)
        assert say_text(s) == "", "the same warning is not repeated by a poll"
        # exactly at the threshold still warns; one above does not
        set_types(s, ID_WOLF, 2, 0, 0, docks=4)
        fresh(s, 10, page_clock=True)
        s.tick(MIN + 5000)
        s.page.wait_for_function("document.querySelector('#bvList .bv-tile').innerText.includes('Low: 2 bikes left')", timeout=8000)
        set_types(s, ID_WOLF, 3, 0, 0, docks=4)
        fresh(s, 10, page_clock=True)
        s.tick(MIN + 5000)
        s.page.wait_for_function("!document.querySelector('#bvList .bv-tile').innerText.includes('Low:')", timeout=8000)
        # change: no bikes and no docks
        set_types(s, ID_WOLF, 0, 0, 0, docks=0)
        fresh(s, 10, page_clock=True)
        s.tick(MIN + 5000)
        s.page.wait_for_function("document.querySelector('#bvList .bv-tile').innerText.includes('No free docks')", timeout=8000)
        t0 = tiles_text(s)[0]
        assert "Low: no bikes left" in t0 and "No free docks" in t0, t0
        s.page.wait_for_function("document.getElementById('bvLive').textContent.includes('No free docks')", timeout=4000)
        assert say_text(s) == "Indego 4th and Wolf: Low: no bikes left. No free docks", say_text(s)
        # docks closed (not returning): "no free docks" would be wrong, the tile says "Docks closed"
        set_types(s, ID_WOLF, 5, 0, 0, docks=0, is_returning=0)
        fresh(s, 10, page_clock=True)
        clear_say(s)
        s.tick(MIN + 5000)
        s.page.wait_for_function("!document.querySelector('#bvList .bv-tile').innerText.includes('No free docks')", timeout=8000)
        assert "Low:" not in tiles_text(s)[0] and "Docks closed" in tiles_text(s)[0], tiles_text(s)[0]
        s.page.wait_for_function("document.getElementById('bvLive').textContent.includes('no longer')", timeout=4000)
        # not renting: no bike warning even at 0 bikes
        set_types(s, ID_WOLF, 0, 0, 0, docks=3, is_renting=0)
        fresh(s, 10, page_clock=True)
        s.tick(MIN + 5000)
        s.page.wait_for_function("document.querySelector('#bvList .bv-tile').innerText.includes('Not renting')", timeout=8000)
        assert "Low:" not in tiles_text(s)[0], tiles_text(s)[0]
        assert not s.console_errors, s.console_errors


def test_warning_badges_and_one_announcement_per_change(root):
    check_badges(root)
    must_fail(check_badges, root, ("js/boardbikes.js", "r.bikes <= r.lowBikes", "r.bikes < r.lowBikes"))
    must_fail(check_badges, root, ("js/boardbikes.js", "r.noDocks && r.returning && r.docks <= 0", "r.noDocks && r.docks <= 0"))
    must_fail(check_badges, root, ("js/boardbikesview.js", "if ((warned[r.id] || '') === t) return;", ""))


# ---------------------------------------------------------------- stale and failed data

def check_stale(root):
    items = [(ID_WOLF, "4th & Wolf", {"lowBikes": 3, "noDocks": True})]
    # the feed's newest data is over 10 minutes old: counts show with their ages, but no warning
    with Session(root, init_scripts=[HOOK, picks_with(*items)]) as s:
        prep(s)
        set_types(s, ID_WOLF, 1, 0, 0, docks=0)
        s.mocks.indego_status["last_updated"] = int(NOON) - 11 * 60
        open_board(s)
        assert js(s, "window.SEPTA.boardbikes.source(Date.now())") == "stale"
        assert rows(s)[0]["warn"] == [] and "Low:" not in tiles_text(s)[0] and "No free docks" not in tiles_text(s)[0], tiles_text(s)[0]
        assert say_text(s) == ""
    # a live warning goes quiet when a refresh fails, and stays quiet until fresh data comes back
    with Session(root, init_scripts=[HOOK, picks_with(*items)]) as s:
        prep(s)
        set_types(s, ID_WOLF, 1, 0, 0, docks=0)
        open_board(s)
        assert "Low: 1 bike left" in tiles_text(s)[0]
        s.page.wait_for_function("document.getElementById('bvLive').textContent.includes('Low: 1 bike left')", timeout=4000)
        clear_say(s)
        s.mocks.indego_mode = "http500"
        s.tick(MIN + 5000)
        s.page.wait_for_function("window.SEPTA.boardbikes.source(Date.now()) === 'stale'", timeout=8000)
        assert "Low:" not in tiles_text(s)[0] and "E-BIKE" in tiles_text(s)[0], tiles_text(s)[0]
        s.tick(5 * MIN)
        s.tick(5 * MIN)
        assert js(s, "window.SEPTA.boardbikes.source(Date.now())") == "down"
        assert "Low:" not in tiles_text(s)[0]
        assert say_text(s) == "", ("stale or failed data announces nothing", say_text(s))
        s.mocks.indego_mode = "ok"
        fresh(s, 10, page_clock=True)
        s.tick(5 * MIN)
        s.page.wait_for_function("document.querySelector('#bvList .bv-tile').innerText.includes('Low: 1 bike left')", timeout=8000)
        assert say_text(s) == "", "the same warning coming back after an outage is not announced again"


def test_no_warning_on_stale_or_failed_data(root):
    check_stale(root)
    must_fail(check_stale, root, ("js/boardbikes.js", "live = src === 'live';", "live = src !== 'down';"))


# ---------------------------------------------------------------- settings sheet

def check_settings(root):
    with bsess(root, picked=(WOLF, SNYDER)) as s:
        open_board(s)
        n0 = status_hits(s)
        keys = s.page.evaluate("Object.keys(localStorage).sort()")
        s.page.click("#bvSet")
        s.page.wait_for_selector("#bvSettings [data-fk='bl0i']", state="visible")
        vals = s.page.evaluate("[...document.querySelectorAll('#bvSettings .bv-stepper output')].map(o => o.getAttribute('aria-label') + '=' + o.textContent)")
        assert any(v.startswith("low-bike warning for 4th & Wolf=Off") for v in vals), vals
        assert s.page.is_disabled("#bvSettings [data-fk='bl0d']"), "Off is the lowest step"
        assert not s.page.is_checked("#bvSettings [data-fk='bn0']")
        s.page.click("#bvSettings [data-fk='bl0i']")  # Off -> 0
        assert js(s, "window.SEPTA.boardbikes.stations()[0].lowBikes") == 0
        s.page.click("#bvSettings [data-fk='bl0i']")  # 1
        s.page.click("#bvSettings [data-fk='bl0i']")  # 2
        assert js(s, "window.SEPTA.boardbikes.stations()[0].lowBikes") == 2
        s.page.check("#bvSettings [data-fk='bn0']")
        assert js(s, "window.SEPTA.boardbikes.stations()[0].noDocks") is True
        for _ in range(8):
            if s.page.is_enabled("#bvSettings [data-fk='bl0i']"):
                s.page.click("#bvSettings [data-fk='bl0i']")
        assert js(s, "window.SEPTA.boardbikes.stations()[0].lowBikes") == 5, "capped at 5"
        assert s.page.is_disabled("#bvSettings [data-fk='bl0i']")
        assert js(s, "window.SEPTA.boardbikes.stations()[1]") == {"id": ID_SNYDER, "name": "2nd & Snyder"}, "the other station is untouched"
        for _ in range(8):
            if s.page.is_enabled("#bvSettings [data-fk='bl0d']"):
                s.page.click("#bvSettings [data-fk='bl0d']")
        s.page.uncheck("#bvSettings [data-fk='bn0']")
        assert js(s, "window.SEPTA.boardbikes.stations()[0]") == {"id": ID_WOLF, "name": "4th & Wolf"}, "back to off"
        assert s.page.evaluate("Object.keys(localStorage).sort()") == keys, "no new storage key"
        assert status_hits(s) == n0, "changing a warning makes no request"
        assert not s.console_errors, s.console_errors


def test_settings_controls_set_and_clear_the_warnings(root):
    check_settings(root)
    must_fail(check_settings, root, ("js/boardsettings.js", "saved(bb.setAlert(s.id, { noDocks: v }));", ""))
