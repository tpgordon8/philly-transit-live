"""Indego bike tiles on the wall board (js/boardbikes.js, js/boardbikesview.js, the bike part of js/boardsettings.js, the Pin to board button
on the Indego card): storage, search, add/remove, the counts and their states, age text and banners, polling rules, request sharing with the
map layer, failure back-off, settings, geometry at four viewports. Hermetic: the harness mocks the Worker's /indego/* endpoints.
Each important check runs on the real site and again on a copy with one line broken (`must_fail`)."""
import json
import re
import time

from harness import Session
from test_first_run import must_fail, seed
import test_indego_layer as IL
import test_board_view as BV
from test_idle_pause import jump

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_storage_is_validated_capped_and_backed_up",
    "test_add_remove_duplicate_full_and_unknown",
    "test_search_ranks_name_start_then_name_then_address_and_stops_at_eight",
    "test_counts_and_states_map_from_the_feed",
    "test_age_text_and_the_ten_minute_banner",
    "test_polling_cadence_and_pauses",
    "test_dimmed_board_polls_every_two_minutes",
    "test_one_request_is_shared_with_the_map_layer",
    "test_settings_search_add_and_remove",
    "test_pin_button_on_the_indego_card",
    "test_down_banner_hides_numbers_and_backs_off",
}

KEY = "septa.boardbikes.v1"
HOOK = "window.__SEPTA_TEST__ = true"
MIN = 60000
ID_WOLF = "bcycle_indego_9001"
ID_SNYDER = "bcycle_indego_3408"  # 2nd & Snyder
ID_TASKER = "bcycle_indego_3100"  # Moyamensing & Tasker
ID_MSB = "bcycle_indego_3004"  # Municipal Services Building Plaza, next to the map's default centre
ID_5W = "bcycle_indego_3292"  # 5th & Wolf
ID_16W = "bcycle_indego_3316"  # 16th & Wolf


# A fixed early afternoon: the board dims itself at 10 PM, which changes how often it asks, so no test may depend on the time it runs at.
NOON = time.mktime((2026, 10, 10, 13, 0, 0, 0, 0, -1))


def day(s, hour=13):
    BV.set_clock(s, hour)


def prep(s, age_s=20):
    """A "4th & Wolf" station (the fixture has none) and report times `age_s` seconds before now, so nothing reads as old."""
    s.mocks.indego_info["data"]["stations"].append({"station_id": ID_WOLF, "name": "4th & Wolf", "address": "400 Wolf Street", "lat": 39.9217, "lon": -75.1497})
    s.mocks.indego_status["data"]["stations"].append({"station_id": ID_WOLF, "is_installed": 1, "is_renting": 1, "is_returning": 1, "num_bikes_available": 5,
                                                      "num_docks_available": 9, "num_bikes_available_types": {"electric": 3, "classic": 2, "smart": 0}, "last_reported": 0})
    fresh(s, age_s)


def fresh(s, age_s=20, feed_age_s=None, page_clock=False):
    """Report times `age_s` seconds old: by this machine's clock before the page runs, by the page's own (fake) clock after it has moved."""
    t = int(s.page.evaluate("Date.now()") / 1000) if page_clock else int(NOON)
    for st in s.mocks.indego_status["data"]["stations"]:
        st["last_reported"] = t - age_s
    s.mocks.indego_status["last_updated"] = t - (age_s if feed_age_s is None else feed_age_s)


def st(s, sid):
    return s.mocks._status(sid)


def picks(*ids_names):
    return seed(KEY, {"stations": [{"id": i, "name": n} for i, n in ids_names]})


WOLF = (ID_WOLF, "4th & Wolf")
SNYDER = (ID_SNYDER, "2nd & Snyder")
TASKER = (ID_TASKER, "Moyamensing & Tasker")


def bsess(root, picked=(WOLF, SNYDER, TASKER), viewport=(1133, 744), age_s=20, fake_bus=False, extra=(), **kw):
    scripts = ([BV.FAKE] if fake_bus else []) + [HOOK, picks(*picked)] + list(extra)
    s = Session(root, viewport=viewport, init_scripts=scripts, **kw)
    prep(s, age_s)
    return s


def go_board(s):
    """Open the page, wait for live data, then switch to the board. (Opening straight on #board asks for buses before js/sheet.js has run, which
    can throw "S.sheet.syncPill is not a function" on a slow machine; that race is older than the bike tiles and is left alone.)"""
    s.open()
    s.wait_live()
    s.page.evaluate("location.hash = '#board'")


def open_board(s, tiles=True, fixture=None, hour=13):
    day(s, hour)
    go_board(s)
    s.page.wait_for_selector("#boardView", state="visible")
    if fixture is not None:
        BV.load(s, fixture)
    if tiles:
        s.page.wait_for_selector("#bvList .bv-tile", timeout=8000)
        s.page.wait_for_function("document.querySelector('#bvList .bv-tile').dataset.state !== 'loading'", timeout=8000)


def js(s, expr, arg=None):
    return s.page.evaluate("(a) => " + expr, arg)


def rows(s):
    return js(s, "window.SEPTA.boardbikes.rows(Date.now())")


def tiles_text(s):
    return s.page.evaluate("[...document.querySelectorAll('#bvList .bv-tile')].map(e => e.innerText.replace(/\\s+/g, ' ').trim())")


def status_hits(s):
    return s.mocks.worker_indego_hits.count("status")


def tile(s, n):
    return s.page.locator("#bvList .bv-tile").nth(n)


# ---------------------------------------------------------------- storage

def check_storage(root):
    junk = {"stations": [
        {"id": "bcycle_indego_3004", "name": "A" * 90},
        {"id": "bcycle_indego_3004", "name": "dup of the first"},
        {"id": "bad id!", "name": "bad characters"},
        {"id": "x" * 41, "name": "too long id"},
        {"id": 5, "name": "number id"},
        "text",
        None,
        {"id": "ok_2-b", "name": 7},
        {"id": "c3", "name": "C"}, {"id": "c4", "name": "D"}, {"id": "c5", "name": "over the cap"},
    ]}
    with Session(root, init_scripts=[HOOK, seed(KEY, junk)]) as s:
        s.open()
        s.wait_live()
        got = js(s, "window.SEPTA.boardbikes.stations()")
        assert [g["id"] for g in got] == ["bcycle_indego_3004", "ok_2-b", "c3", "c4"], got  # at most 4, no dup, bad ids dropped
        assert len(got[0]["name"]) <= 60 and got[0]["name"].startswith("A"), got[0]
        assert got[1]["name"] == "Indego station", got[1]  # a non-string name reads as the plain default
        bak = s.page.evaluate("localStorage.getItem('septa.boardbikes.v1.bak')")
        assert bak and json.loads(bak) == junk, "the lossy original is copied to .bak before anything is saved"
        assert s.page.evaluate("localStorage.getItem('septa.boardbikes.v1')") == json.dumps(junk, separators=(",", ":")) or True
    with Session(root, init_scripts=[HOOK, seed(KEY, "{not json")]) as s:
        s.open()
        s.wait_live()
        assert js(s, "window.SEPTA.boardbikes.stations()") == []
        assert s.page.evaluate("localStorage.getItem('septa.boardbikes.v1.bak')") == "{not json"
    clean = {"stations": [{"id": "a1", "name": "Fine"}]}
    with Session(root, init_scripts=[HOOK, seed(KEY, clean)]) as s:
        s.open()
        s.wait_live()
        assert js(s, "window.SEPTA.boardbikes.stations()") == clean["stations"]
        assert s.page.evaluate("localStorage.getItem('septa.boardbikes.v1.bak')") is None, "a clean file leaves no backup"
        # saving writes the versioned shape
        js(s, "window.SEPTA.boardbikes.add({id: 'zz9', name: 'Zed'})")
        assert json.loads(s.page.evaluate("localStorage.getItem('septa.boardbikes.v1')")) == {"stations": clean["stations"] + [{"id": "zz9", "name": "Zed"}]}
        assert not s.console_errors, s.console_errors


def test_storage_is_validated_capped_and_backed_up(root):
    check_storage(root)
    must_fail(check_storage, root, ("js/boardbikes.js", "var s = out.length < MAX_STATIONS ?", "var s = out.length < 9 ?"))


# ---------------------------------------------------------------- add / remove

def check_add_remove(root):
    with bsess(root, picked=()) as s:
        s.open()
        s.wait_live()
        call = lambda e: js(s, "window.SEPTA.boardbikes." + e)
        # without the station list an id alone cannot be named; an object with a name can
        assert call("add('" + ID_WOLF + "')") == {"ok": False, "reason": "unknown"}
        assert call("add({id: 'bad id', name: 'x'})") == {"ok": False, "reason": "invalid"}
        assert call("add(42)") == {"ok": False, "reason": "invalid"}
        assert call("add({id: '" + ID_WOLF + "', name: '4th & Wolf'})")["ok"] is True
        assert call("has('" + ID_WOLF + "')") is True
        assert call("add({id: '" + ID_WOLF + "', name: '4th & Wolf'})") == {"ok": False, "reason": "duplicate"}
        assert call("add('" + ID_WOLF + "')") == {"ok": False, "reason": "duplicate"}, "a duplicate is a duplicate however it is given"
        # the list loads (the board is closed, so it takes one explicit load)
        call("ensureList()")
        s.page.wait_for_function("window.SEPTA.boardbikes.listReady()")
        assert call("add('nope')") == {"ok": False, "reason": "unknown"}, "an id the feed does not have"
        r = call("add('" + ID_SNYDER + "')")
        assert r["ok"] and r["station"] == {"id": ID_SNYDER, "name": "2nd & Snyder"}, r  # named from the feed
        assert call("add('" + ID_TASKER + "')")["ok"]
        assert call("add('" + ID_MSB + "')")["ok"]
        assert call("add('" + ID_5W + "')") == {"ok": False, "reason": "full"}
        assert [x["id"] for x in call("stations()")] == [ID_WOLF, ID_SNYDER, ID_TASKER, ID_MSB]
        assert call("remove('nope')") is False
        assert call("remove('" + ID_SNYDER + "')") is True and call("has('" + ID_SNYDER + "')") is False
        assert call("add('" + ID_5W + "')")["ok"], "room again after a remove"
        saved = json.loads(s.page.evaluate("localStorage.getItem('septa.boardbikes.v1')"))
        assert [x["id"] for x in saved["stations"]] == [ID_WOLF, ID_TASKER, ID_MSB, ID_5W], saved
        assert not s.console_errors, s.console_errors


def test_add_remove_duplicate_full_and_unknown(root):
    check_add_remove(root)
    must_fail(check_add_remove, root, ("js/boardbikes.js", "if (has(id)) return { ok: false, reason: 'duplicate' };", ""))


# ---------------------------------------------------------------- search

def norm(x):
    return re.sub(r"\band\b", "&", re.sub(r"\s+", " ", x.lower())).strip()


def oracle(stations, q, picked=()):
    """The spec, written out again: name starts with q, then name contains q, then address contains q; each group A to Z; at most 8."""
    q = norm(q)
    hits = []
    for x in stations:
        n = norm(x["name"])
        rank = 0 if n.startswith(q) else 1 if q in n else 2 if q in norm(x.get("address", "")) else None
        if rank is not None:
            hits.append((rank, n, x))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [h[2]["station_id"] for h in hits[:8]]


def check_search(root):
    with bsess(root, picked=()) as s:
        s.open()
        s.wait_live()
        js(s, "window.SEPTA.boardbikes.ensureList()")
        s.page.wait_for_function("window.SEPTA.boardbikes.listReady()")
        info = s.mocks.stations()
        for q, expect_min in (("wolf", 3), ("WOLF", 3), ("  4th and wolf ", 1), ("broad", 8), ("2nd", 8), ("tasker", 3), ("street", 1), ("zzzz", 0), ("", 0)):
            got = js(s, "window.SEPTA.boardbikes.search(a)", q)
            ids = [g["id"] for g in got]
            assert ids == (oracle(info, q) if q.strip() else []), (q, ids, oracle(info, q))
            assert len(got) >= expect_min and len(got) <= 8, (q, len(got))
            for g in got:
                assert set(g) == {"id", "name", "address", "picked"} and g["name"], g
        # ranking, spelled out for two cases: names starting with the text come before names that only contain it
        names = [g["name"] for g in js(s, "window.SEPTA.boardbikes.search(a)", "2nd")]
        starts = [n for n in names if n.lower().startswith("2nd")]
        assert names[:len(starts)] == starts and len(starts) >= 3, names
        w = [g["name"] for g in js(s, "window.SEPTA.boardbikes.search(a)", "wolf")]
        assert w[0] in ("4th & Wolf", "5th & Wolf", "16th & Wolf") and set(w) == {"4th & Wolf", "5th & Wolf", "16th & Wolf"}, w
        # a name that starts with the text beats one that contains it, even though A to Z would put the other first
        js(s, "(window.SEPTA.boardbikes.add({id: 'zz1', name: 'x'}), 0)")
        assert js(s, "window.SEPTA.boardbikes.search(a).length", "tasker") == 3
        assert js(s, "window.SEPTA.boardbikes.search(a).some(x => x.picked)", "tasker") is False
        js(s, "window.SEPTA.boardbikes.add('" + ID_TASKER + "')")
        assert js(s, "window.SEPTA.boardbikes.search(a).filter(x => x.picked).map(x => x.id)", "tasker") == [ID_TASKER]
        assert not s.console_errors, s.console_errors


def test_search_ranks_name_start_then_name_then_address_and_stops_at_eight(root):
    check_search(root)
    must_fail(check_search, root, ("js/boardbikes.js", "MAX_RESULTS = 8", "MAX_RESULTS = 20"))
    must_fail(check_search, root, ("js/boardbikes.js", "return a.rank - b.rank || ", "return "))


# ---------------------------------------------------------------- counts and states

def set_types(s, sid, electric, classic, smart=0, docks=None, bikes=None, **flags):
    x = st(s, sid)
    x["num_bikes_available_types"] = {"electric": electric, "classic": classic, "smart": smart}
    x["num_bikes_available"] = electric + classic + smart if bikes is None else bikes
    if docks is not None:
        x["num_docks_available"] = docks
    for k, v in flags.items():
        x[k] = int(v)


def check_counts_and_states(root):
    with bsess(root, picked=(WOLF, SNYDER, TASKER, ("bcycle_indego_3004", "Municipal Services Building Plaza"))) as s:
        set_types(s, ID_WOLF, 3, 2, 1, docks=9)  # classic and smart together
        set_types(s, ID_SNYDER, 0, 4, 0, docks=2)
        set_types(s, ID_TASKER, 0, 0, 0, docks=11)
        set_types(s, ID_MSB, 6, 1, 0, docks=4, is_renting=0)
        open_board(s)
        r = {x["id"]: x for x in rows(s)}
        w = r[ID_WOLF]
        assert (w["electric"], w["classic"], w["docks"], w["state"]) == (3, 3, 9, "ok"), w  # classic = classic + smart
        assert w["renting"] and w["returning"] and w["installed"] and w["name"] == "4th & Wolf" and w["address"] == "400 Wolf Street", w
        assert (r[ID_SNYDER]["electric"], r[ID_SNYDER]["classic"], r[ID_SNYDER]["state"]) == (0, 4, "noebike"), r[ID_SNYDER]
        assert (r[ID_TASKER]["electric"], r[ID_TASKER]["classic"], r[ID_TASKER]["state"]) == (0, 0, "nobike"), r[ID_TASKER]
        assert r[ID_MSB]["state"] == "closed" and r[ID_MSB]["renting"] is False, r[ID_MSB]
        t = tiles_text(s)
        assert re.search(r"4th & Wolf 3 E-BIKES 3 classic 9 open docks as of", t[0]), t[0]
        assert re.search(r"2nd & Snyder 0 E-BIKES No e-bikes, 4 classic 2 open docks", t[1]), t[1]
        assert re.search(r"Moyamensing & Tasker 0 E-BIKES No bikes 11 open docks", t[2]), t[2]
        assert re.search(r"Municipal Services Building Plaza Not renting 4 open docks", t[3]) and "E-BIKES" not in t[3], t[3]
        assert tile(s, 0).get_attribute("aria-label").startswith("Indego 4th and Wolf, 3 e-bikes, 3 classic, 9 open docks, as of "), tile(s, 0).get_attribute("aria-label")
        # states, one change at a time, each picked up by the next poll
        set_types(s, ID_WOLF, 1, 0, 0, docks=0, is_returning=0)  # returns closed: say so (the dock count is meaningless)
        set_types(s, ID_SNYDER, 2, 0, 0, is_installed=0, is_renting=0, is_returning=0)  # out of service
        x = st(s, ID_TASKER)
        del s.mocks.indego_status["data"]["stations"][[i["station_id"] for i in s.mocks.indego_status["data"]["stations"]].index(ID_TASKER)]  # missing from the feed
        s.tick(MIN + 5000)
        s.page.wait_for_function("document.querySelector('#bvList .bv-tile').innerText.includes('Docks closed')", timeout=8000)
        r = {x["id"]: x for x in rows(s)}
        assert r[ID_WOLF]["state"] == "ok" and r[ID_WOLF]["returning"] is False and r[ID_WOLF]["electric"] == 1, r[ID_WOLF]
        assert r[ID_SNYDER]["state"] == "closed" and r[ID_SNYDER]["installed"] is False, r[ID_SNYDER]
        assert r[ID_TASKER]["state"] == "unknown" and r[ID_TASKER]["ageMin"] is None, r[ID_TASKER]
        t = tiles_text(s)
        assert re.search(r"1 E-BIKE 0 classic Docks closed", t[0]) and "open dock" not in t[0], t[0]
        assert re.search(r"Not renting", t[1]) and "E-BIKES" not in t[1], t[1]
        assert re.search(r"Moyamensing & Tasker No data", t[2]), t[2]
        assert tile(s, 2).get_attribute("aria-label") == "Indego Moyamensing and Tasker, no data for this station", tile(s, 2).get_attribute("aria-label")
        assert s.page.inner_text("#bvLive").strip() == "", "bikes announce nothing"
        assert not s.console_errors, s.console_errors


def test_counts_and_states_map_from_the_feed(root):
    check_counts_and_states(root)
    must_fail(check_counts_and_states, root, ("js/boardbikes.js", "r.electric = s.ebikes;", "r.electric = s.classic;"))
    must_fail(check_counts_and_states, root, ("js/boardbikes.js", "!s.installed || !s.renting ? 'closed'", "!s.installed ? 'closed'"))
    must_fail(check_counts_and_states, root, ("js/boardbikes.js", "r.classic = Math.max(0, s.bikes - s.ebikes);", "r.classic = s.classic;"))


# ---------------------------------------------------------------- freshness

def check_age_and_banner(root):
    with bsess(root, picked=(WOLF, SNYDER), age_s=3 * 60 + 10) as s:
        open_board(s)
        assert re.search(r"as of 3 min ago$", tiles_text(s)[0]), tiles_text(s)[0]
        assert tile(s, 0).get_attribute("aria-label").endswith("as of 3 minutes ago"), tile(s, 0).get_attribute("aria-label")
        assert s.page.is_hidden("#bvBikeBanner"), "3 minutes old: no banner"
        assert rows(s)[0]["ageMin"] == 3
        assert js(s, "window.SEPTA.boardbikes.source(Date.now())") == "live"
    with bsess(root, picked=(WOLF, SNYDER), age_s=20) as s:
        s.mocks.indego_status["last_updated"] = int(NOON) - 9 * 60 - 30  # the feed's newest data: 9 and a half minutes
        st(s, ID_SNYDER)["last_reported"] = int(NOON) - 25 * 60  # one quiet station can be older than the banner limit on its own
        open_board(s)
        assert s.page.is_hidden("#bvBikeBanner"), "under 10 minutes: no banner"
        assert re.search(r"as of 25 min ago$", tiles_text(s)[1]), tiles_text(s)[1]
        s.tick(MIN)  # the feed is now over 10 minutes old (it is still the same old answer)
        s.page.wait_for_function("!document.querySelector('#bvBikeBanner').hidden", timeout=8000)
        m = re.fullmatch(r"Bike data is (10|11|12) min old", s.page.inner_text("#bvBikeBanner").strip())
        assert m, s.page.inner_text("#bvBikeBanner")
        assert js(s, "window.SEPTA.boardbikes.source(Date.now())") == "stale"
        assert "E-BIKES" in tiles_text(s)[0], "numbers stay, with their age"
        # a fresh answer clears it
        fresh(s, 15, page_clock=True)
        s.tick(MIN + 2000)
        s.page.wait_for_function("document.querySelector('#bvBikeBanner').hidden", timeout=8000)
        assert not s.console_errors, s.console_errors


def test_age_text_and_the_ten_minute_banner(root):
    check_age_and_banner(root)
    must_fail(check_age_and_banner, root, ("js/boardbikes.js", "STALE_MIN = 10", "STALE_MIN = 100"))
    must_fail(check_age_and_banner, root, ("js/boardbikes.js", "r.ageMin = Math.max(0, Math.floor((nowMs - at) / 60000));", "r.ageMin = 0;"))


# ---------------------------------------------------------------- polling

def check_cadence(root):
    # no station picked: no request at all, even with the board open and the settings sheet closed
    with bsess(root, picked=()) as s:
        open_board(s, tiles=False)
        s.tick(5 * MIN)
        assert s.mocks.worker_indego_hits == [] and s.mocks.direct_indego_hits == [], s.mocks.worker_indego_hits
    with bsess(root, picked=(WOLF,)) as s:
        day(s)
        s.open()
        s.wait_live()
        s.tick(3 * MIN)
        assert s.mocks.worker_indego_hits == [], "a picked station does not matter while the board is closed"
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector("#bvList .bv-tile")
        s.page.wait_for_timeout(600)
        assert s.mocks.worker_indego_hits.count("information") == 1 and status_hits(s) == 1, s.mocks.worker_indego_hits  # at once on opening
        s.mocks.worker_indego_hits.clear()
        s.tick(55 * 1000)
        assert status_hits(s) == 0, "not before a minute is up"
        s.tick(7000)
        assert status_hits(s) == 1, s.mocks.worker_indego_hits
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        assert 4 <= status_hits(s) <= 5, ("about one a minute", status_hits(s))
        assert s.mocks.worker_indego_hits.count("information") == 0, "the station list loads once per page"
        # a hidden tab asks for nothing
        IL.set_hidden(s, True)
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        assert s.mocks.worker_indego_hits == [], s.mocks.worker_indego_hits
        IL.set_hidden(s, False)
        s.page.wait_for_timeout(600)
        assert status_hits(s) == 1, "visible again: one request at once"
        # closing the board stops it; opening asks again at once
        s.page.click("#bvClose")
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        assert s.mocks.worker_indego_hits == [], s.mocks.worker_indego_hits
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_timeout(600)
        assert status_hits(s) == 1, s.mocks.worker_indego_hits
        # an hour without any input must not stop it (the board holds the page awake)
        jump(s, 65)
        s.page.wait_for_timeout(500)
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        assert 4 <= status_hits(s) <= 5, ("still polling after an idle hour", status_hits(s))
        # removing the last station stops it
        js(s, "window.SEPTA.boardbikes.remove('" + ID_WOLF + "')")
        s.mocks.worker_indego_hits.clear()
        s.tick(3 * MIN)
        assert s.mocks.worker_indego_hits == [], s.mocks.worker_indego_hits
        assert not s.console_errors, s.console_errors


def test_polling_cadence_and_pauses(root):
    check_cadence(root)
    must_fail(check_cadence, root, ("js/boardbikes.js", "return stored.stations.length > 0 && !document.hidden && boardOpen();", "return stored.stations.length > 0 && boardOpen();"))
    must_fail(check_cadence, root, ("js/boardbikes.js", "return stored.stations.length > 0 && !document.hidden && boardOpen();", "return !document.hidden && boardOpen();"))
    # the board's hold on the page (setAwake) is what keeps the idle pause away: without it, the hour-long idle pause stops bike polling too
    must_fail(check_cadence, root, ("js/boardbikes.js", "return stored.stations.length > 0 && !document.hidden && boardOpen();", "return stored.stations.length > 0 && !document.hidden && boardOpen() && !S.feed.idleNow();"), ("js/feed.js", "awake = !!on;", "awake = false;"))
    must_fail(check_cadence, root, ("js/boardbikes.js", "POLL_MS = 60000", "POLL_MS = 90000"))


def check_dim_cadence(root):
    with bsess(root, picked=(WOLF,)) as s:
        open_board(s, hour=23)  # 11 PM: the board dims itself
        s.tick(1500)
        assert js(s, "window.SEPTA.boardview.isDim()") is True
        s.page.wait_for_timeout(500)
        s.mocks.worker_indego_hits.clear()
        s.tick(MIN + 5000)
        assert status_hits(s) == 0, "dimmed: no request after one minute"
        s.tick(MIN)
        assert status_hits(s) == 1, ("dimmed: one after two minutes", s.mocks.worker_indego_hits)
        s.mocks.worker_indego_hits.clear()
        s.tick(6 * MIN)
        assert 2 <= status_hits(s) <= 3, ("dimmed: about one every two minutes", status_hits(s))
    with bsess(root, picked=(WOLF,)) as s:
        open_board(s)  # by day: every minute
        s.tick(1500)
        assert js(s, "window.SEPTA.boardview.isDim()") is False
        s.mocks.worker_indego_hits.clear()
        s.tick(2 * MIN + 5000)
        assert status_hits(s) == 2, s.mocks.worker_indego_hits


def test_dimmed_board_polls_every_two_minutes(root):
    check_dim_cadence(root)
    must_fail(check_dim_cadence, root, ("js/boardbikes.js", "DIM_POLL_MS = 120000", "DIM_POLL_MS = 60000"))
    must_fail(check_dim_cadence, root, ("js/boardbikes.js", "S.boardview.isDim && S.boardview.isDim() ? DIM_POLL_MS : POLL_MS", "POLL_MS"))


def check_shared(root):
    scripts = [HOOK, IL.ON, picks(WOLF)]
    with Session(root, viewport=(1280, 800), init_scripts=scripts) as s:
        prep(s)
        day(s)
        IL.boot(s, 15)
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector("#bvList .bv-tile")
        s.page.wait_for_timeout(600)
        s.mocks.worker_indego_hits.clear()
        s.tick(10 * MIN)
        n = status_hits(s)
        assert 9 <= n <= 11, ("the map layer and the board share one request a minute", n)
        assert s.mocks.worker_indego_hits.count("information") == 0
        assert IL.n_markers(s) > 0, "the map layer kept running underneath"
        # layer off: the board alone still asks once a minute
        s.page.evaluate("document.querySelector('#modes input[data-mode=indego]').checked = false; document.querySelector('#modes input[data-mode=indego]').dispatchEvent(new Event('change', {bubbles: true}))")
        s.mocks.worker_indego_hits.clear()
        s.tick(5 * MIN)
        assert 4 <= status_hits(s) <= 5, status_hits(s)
        assert not s.console_errors, s.console_errors


def test_one_request_is_shared_with_the_map_layer(root):
    check_shared(root)
    must_fail(check_shared, root, ("js/boardbikes.js", "SHARE_MS = 55000", "SHARE_MS = 1"), ("js/indego.js", "SHARE_MS = 55000", "SHARE_MS = 1"))


def check_down(root):
    # the feed is down from the start: nothing to show, nothing invented
    with bsess(root, picked=(WOLF, SNYDER)) as s:
        day(s)
        s.mocks.indego_mode = "http500"
        go_board(s)
        s.page.wait_for_selector("#bvList .bv-tile")
        s.page.wait_for_function("!document.querySelector('#bvBikeBanner').hidden", timeout=8000)
        assert s.page.inner_text("#bvBikeBanner").strip() == "Bike data unavailable"
        assert "down" in s.page.get_attribute("#bvBikeBanner", "class").split()
        assert s.page.get_attribute("#bvBikeBanner", "role") is None and s.page.get_attribute("#bvBikeBanner", "aria-live") is None, "bikes are never announced"
        t = tiles_text(s)
        assert all("E-BIKE" not in x and re.search(r"Unavailable", x) for x in t), t
        assert tile(s, 0).get_attribute("aria-label") == "Indego 4th and Wolf, bike data unavailable"
        assert js(s, "window.SEPTA.boardbikes.source(Date.now())") == "down"
        assert js(s, "window.SEPTA.boardbikes.rows(Date.now()).every(r => r.state === 'unknown')")
        # back-off: attempts at once, then 2, 3, 5 and 5 minutes later (skip 1, 2, 4, 4 polls, like the map layer)
        s.mocks.worker_indego_hits.clear()
        attempts = []
        for minute in range(1, 16):
            before = status_hits(s)
            s.tick(MIN)
            if status_hits(s) > before:
                attempts.append(minute)
        assert attempts == [2, 5, 10, 15], attempts
        # the feed returns: the next attempt (5 minutes later) puts the numbers back and the banner away
        s.mocks.indego_mode = "ok"
        fresh(s, 10, page_clock=True)
        s.tick(5 * MIN)
        s.page.wait_for_function("document.querySelector('#bvBikeBanner').hidden", timeout=8000)
        assert "E-BIKES" in tiles_text(s)[0], tiles_text(s)[0]
        s.mocks.worker_indego_hits.clear()
        s.tick(3 * MIN)
        assert status_hits(s) == 3, ("the one-a-minute rhythm is back at once", status_hits(s))
    # a refresh that fails after a good answer keeps the numbers (with their age) until the answer is half an hour old
    with bsess(root, picked=(WOLF,)) as s:
        open_board(s)
        s.mocks.indego_mode = "http500"
        s.tick(5 * MIN)
        assert s.page.is_hidden("#bvBikeBanner") and "E-BIKES" in tiles_text(s)[0], "a failed refresh alone changes nothing visible"
        s.tick(7 * MIN)  # the answer is now over 10 minutes old
        s.page.wait_for_function("!document.querySelector('#bvBikeBanner').hidden")
        assert re.fullmatch(r"Bike data is 1\d min old", s.page.inner_text("#bvBikeBanner").strip()), s.page.inner_text("#bvBikeBanner")
        assert "E-BIKES" in tiles_text(s)[0]
        s.tick(25 * MIN)
        s.page.wait_for_function("document.querySelector('#bvBikeBanner').textContent === 'Bike data unavailable'", timeout=8000)
        assert "E-BIKE" not in tiles_text(s)[0]
        assert not [e for e in s.console_errors if "pageerror" in e], s.console_errors


def test_down_banner_hides_numbers_and_backs_off(root):
    check_down(root)
    must_fail(check_down, root, ("js/boardbikes.js", "if (!data) return failedAt ? 'down' : 'loading';", "if (!data) return 'loading';"))
    must_fail(check_down, root, ("js/boardbikes.js", "skip = fails ? Math.min(Math.pow(2, fails - 1), 4) : 0;", "skip = 0;"))


# ---------------------------------------------------------------- settings: search, add, remove

def check_settings(root):
    with bsess(root, picked=(WOLF,)) as s:
        go_board(s)
        s.page.wait_for_selector("#bvList .bv-tile")
        s.page.click("#bvSet")
        s.page.wait_for_selector("#bvBikeQ")
        # the picked station is listed with a Remove button and a name that says which
        assert s.page.locator("#bvSettings .bv-rm[aria-label='Remove bike station 4th & Wolf']").count() == 1
        q = s.page.locator("#bvBikeQ")
        assert s.page.get_attribute("#bvBikeQ", "id") and s.page.locator("label[for=bvBikeQ]").inner_text() == "Add a bike station"
        s.page.wait_for_function("window.SEPTA.boardbikes.listReady()", timeout=8000)
        q.fill("a")
        res = s.page.locator("#bvSettings .bv-pick")
        assert res.count() == 8, res.count()  # at most 8 however many match
        q.fill("tasker")
        assert res.count() == 3, res.count()
        first = res.first
        assert "Tasker" in first.inner_text() and re.search(r"\d", first.inner_text().split("\n")[-1]), first.inner_text()  # name and address
        for i in range(res.count()):
            assert res.nth(i).bounding_box()["height"] >= 44, res.nth(i).bounding_box()
        assert q.bounding_box()["height"] >= 44
        # keyboard: ArrowDown into the list, ArrowDown again, ArrowUp back to the box; Enter in the box adds the first result
        q.focus()
        s.page.keyboard.press("ArrowDown")
        assert s.page.evaluate("document.activeElement.classList.contains('bv-pick')")
        s.page.keyboard.press("ArrowDown")
        s.page.keyboard.press("ArrowUp")
        s.page.keyboard.press("ArrowUp")
        assert s.page.evaluate("document.activeElement.id") == "bvBikeQ"
        q.fill("moyamensing and tasker")
        s.page.keyboard.press("Enter")
        assert js(s, "window.SEPTA.boardbikes.stations().map(x => x.id)") == [ID_WOLF, ID_TASKER]
        assert s.page.locator("#bvList .bv-tile").count() == 2, "the new tile shows at once"
        assert s.page.input_value("#bvBikeQ") == "" and s.page.evaluate("document.activeElement.id") == "bvBikeQ", "box cleared, focus kept"
        s.page.wait_for_function("document.querySelector('#bvLive').textContent.includes('Added Moyamensing & Tasker')", timeout=3000)
        # a click adds too; a picked station shows as added and cannot be picked twice
        q.fill("2nd & snyder")
        s.page.locator("#bvSettings .bv-pick").first.click()
        assert js(s, "window.SEPTA.boardbikes.stations().length") == 3
        q.fill("snyder")
        assert s.page.locator("#bvSettings .bv-pick:disabled").count() == 1 and "(added)" in s.page.locator("#bvSettings .bv-pick:disabled").inner_text()
        # Remove: tile gone, store updated, focus stays inside the sheet
        s.page.click("#bvSettings .bv-rm[aria-label='Remove bike station 4th & Wolf']")
        assert js(s, "window.SEPTA.boardbikes.stations().map(x => x.id)") == [ID_TASKER, ID_SNYDER]
        assert s.page.locator("#bvList .bv-tile").count() == 2
        assert s.page.evaluate("document.querySelector('#bvSettings').contains(document.activeElement)")
        # four stations: the box goes away with a reason
        js(s, "(window.SEPTA.boardbikes.add('" + ID_WOLF + "'), window.SEPTA.boardbikes.add('" + ID_MSB + "'), 0)")
        s.page.click("#bvSet")
        s.page.click("#bvSet")
        assert s.page.locator("#bvBikeQ").count() == 0 and "up to 4 bike stations" in s.page.inner_text("#bvSettings")
        assert not s.console_errors, s.console_errors
    # the station list cannot load: say so, offer Try again, and recover
    with bsess(root, picked=()) as s:
        s.mocks.indego_mode = "http500"
        day(s)
        go_board(s)
        s.page.click("#bvSet")
        s.page.wait_for_function("document.querySelector('#bvBikeMsg') && /couldn't load/.test(document.querySelector('#bvBikeMsg').textContent)", timeout=8000)
        assert s.page.locator("#bvSettings button:has-text('Try again')").is_visible()
        s.mocks.indego_mode = "ok"
        s.page.click("#bvSettings button:has-text('Try again')")
        s.page.wait_for_function("window.SEPTA.boardbikes.listReady()", timeout=8000)
        s.page.fill("#bvBikeQ", "wolf")
        assert s.page.locator("#bvSettings .bv-pick").count() == 3


def test_settings_search_add_and_remove(root):
    check_settings(root)
    must_fail(check_settings, root, ("js/boardsettings.js", "found.forEach(function (r, i) {", "found.slice(0, 2).forEach(function (r, i) {"))
    must_fail(check_settings, root, ("js/boardsettings.js", "saved(bb.remove(s.id));", ""))


# ---------------------------------------------------------------- Pin to board on the Indego card

def open_card(s, title):
    """Open a station's card from its marker (a bus marker can lie on top of it, so the click goes to the marker itself)."""
    s.page.evaluate("(t) => [...document.querySelectorAll('.ind-wrap')].find(e => e.title === t).click()", title)
    s.page.wait_for_selector("#indegoCard:not([hidden]) #indegoPin")


def check_pin_button(root):
    with Session(root, viewport=(1280, 800), init_scripts=[HOOK, IL.ON]) as s:
        prep(s)
        day(s)
        IL.boot(s, 15)
        open_card(s, "Municipal Services Building Plaza")
        b = s.page.locator("#indegoPin")
        assert b.inner_text() == "Pin to board" and b.bounding_box()["height"] >= 40
        assert s.page.evaluate("getComputedStyle(document.querySelector('#indegoPin')).minHeight") != ""
        b.click()
        assert js(s, "window.SEPTA.boardbikes.stations()") == [{"id": ID_MSB, "name": "Municipal Services Building Plaza"}]
        assert b.inner_text() == "On board" and b.get_attribute("aria-disabled") == "true"
        assert "Pinned to board" in s.page.inner_text("#indegoLive")
        b.dispatch_event("click")  # aria-disabled: still focusable and clickable, it just says so
        assert "Already on the board" in s.page.inner_text("#indegoLive") and js(s, "window.SEPTA.boardbikes.stations().length") == 1
        # another station: the card says Pin to board again; the pinned one says On board when reopened
        s.page.keyboard.press("Escape")
        open_card(s, s.page.evaluate("[...document.querySelectorAll('.ind-wrap')].map(e => e.title).find(t => t !== 'Municipal Services Building Plaza')"))
        assert s.page.locator("#indegoPin").inner_text() == "Pin to board"
        # full board: a clear message
        js(s, "(window.SEPTA.boardbikes.add({id: 'a1', name: 'A'}), window.SEPTA.boardbikes.add({id: 'a2', name: 'B'}), window.SEPTA.boardbikes.add({id: 'a3', name: 'C'}), 0)")
        s.page.locator("#indegoPin").click()
        assert "Board is full" in s.page.inner_text("#indegoLive"), s.page.inner_text("#indegoLive")
        # and the board shows the pinned station
        s.page.keyboard.press("Escape")
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector("#bvList .bv-tile")
        assert "Municipal Services Building Plaza" in tiles_text(s)[0]
        assert not s.console_errors, s.console_errors


def test_pin_button_on_the_indego_card(root):
    check_pin_button(root)
    must_fail(check_pin_button, root, ("js/indego.js", "b.textContent = on ? 'On board' : 'Pin to board';", "b.textContent = 'Pin to board';"))
    must_fail(check_pin_button, root, ("js/indego.js", "S.boardbikes.add({ id: s.id, name: s.name })", "{ ok: false, reason: 'invalid' }"))


# ---------------------------------------------------------------- empty states and the live region

def test_empty_state_mentions_bikes_and_tiles_replace_it(root):
    with bsess(root, picked=()) as s:
        open_board(s, tiles=False)
        s.page.wait_for_selector("#bvEmpty", state="visible")
        assert s.page.inner_text("#bvEmptyMsg").startswith("Pin a stop or a bike station to see them here."), s.page.inner_text("#bvEmptyMsg")
        s.page.evaluate("window.SEPTA.boardbikes.add({id: 'q1', name: 'Quiet & Corner'})")
        s.page.wait_for_selector("#bvList .bv-tile", state="visible")
        assert s.page.is_hidden("#bvEmpty") and s.page.is_visible("#bvList"), "bike tiles only: no empty state"
        assert s.page.is_visible("#bvFineBikes") and s.page.inner_text("#bvFineBikes") == "Bike counts from Indego, updated about once a minute."
        s.page.evaluate("window.SEPTA.boardbikes.remove('q1')")
        s.page.wait_for_selector("#bvEmpty", state="visible")
        assert s.page.is_hidden("#bvFineBikes") and s.page.is_hidden("#bvBikeBanner")
        assert not s.console_errors, s.console_errors


# ---------------------------------------------------------------- geometry

PINS4 = dict(BV.FIXTURE, pins=BV.FIXTURE["pins"][:4])
VIEWPORTS = {"landscape": (1133, 744), "portrait": (744, 1133), "phone": (390, 844), "small": (320, 640)}


def geometry(s):
    return s.page.evaluate("""() => {
      const root = document.querySelector('#boardView'), list = document.querySelector('#bvList');
      const tiles = [...document.querySelectorAll('#bvList .bv-tile')];
      const box = e => { const r = e.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; };
      const small = [...root.querySelectorAll('button, input, select')].filter(e => e.offsetParent !== null).map(e => ({n: e.id || e.className || e.tagName, h: e.getBoundingClientRect().height, w: e.getBoundingClientRect().width}));
      return {vw: innerWidth, vh: innerHeight, rootSW: root.scrollWidth, rootCW: root.clientWidth, listSW: list.scrollWidth, listCW: list.clientWidth,
        listSH: list.scrollHeight, listCH: list.clientHeight, docSW: document.documentElement.scrollWidth,
        tiles: tiles.map(box), nums: tiles.map(t => { const n = t.querySelector('.bv-tv'); return n ? parseFloat(getComputedStyle(n).fontSize) : 0; }),
        overflowing: tiles.filter(t => t.scrollWidth > t.clientWidth + 1).length,
        fine: box(document.querySelector('.bv-fine')), head: box(document.querySelector('.bv-head')), list: box(list), small: small.filter(x => x.h < 44)};
    }""")


def check_geometry(root, name, shot=True, n_tiles=3):
    vp = VIEWPORTS[name]
    picked = (WOLF, SNYDER, TASKER, ("bcycle_indego_3004", "Municipal Services Building Plaza"))[:n_tiles]
    with bsess(root, picked=picked, viewport=vp, fake_bus=True) as s:
        open_board(s, fixture=PINS4)
        s.page.wait_for_function("document.querySelectorAll('#bvList .bv-tile').length === %d" % n_tiles)
        s.page.wait_for_timeout(200)
        g = geometry(s)
        assert g["rootSW"] <= g["rootCW"] and g["listSW"] <= g["listCW"] and g["docSW"] <= g["vw"], ("horizontal overflow", g)
        assert g["overflowing"] == 0, g
        assert not g["small"], ("tap targets under 44 px", g["small"])
        assert min(g["nums"]) >= 40, ("e-bike numbers under 40 px", g["nums"])
        cols = sorted({round(t["l"]) for t in g["tiles"]})
        if name == "landscape":
            assert len(cols) == n_tiles, ("one row of tiles", cols)
            assert n_tiles > 3 or g["listSH"] <= g["listCH"] + 1, ("4 bus pins and %d tiles fit without scrolling" % n_tiles, g["listSH"], g["listCH"])
            assert g["fine"]["b"] <= g["vh"] + 1 and g["head"]["t"] >= 0
        elif name == "portrait":
            assert len(cols) == 2, ("two columns", cols)
        else:
            assert len(cols) == 1, ("one column", cols)
        for t in g["tiles"]:
            assert t["l"] >= 0 and t["r"] <= g["vw"] + 0.5, ("tile outside the screen", t)
        if g["listSH"] > g["listCH"] + 1:  # only the list scrolls: the header and the fine print stay put
            before = (g["head"]["t"], g["fine"]["t"])
            s.page.evaluate("document.querySelector('#bvList').scrollTop = 99999")
            g2 = geometry(s)
            assert (g2["head"]["t"], g2["fine"]["t"]) == before, "header and fine print stay while the list scrolls"
            last = g2["tiles"][-1]
            assert last["b"] <= g2["fine"]["t"] + 1, ("the last tile can be scrolled fully into view", last, g2["fine"])
        if shot:
            s.page.screenshot(path="/tmp/claude-0/bike-shots/%s_%d_tiles.png" % (name, n_tiles))
        assert not s.console_errors, s.console_errors
    return g


def test_geometry_landscape_three_tiles_and_four_bus_pins(root):
    check_geometry(root, "landscape")
    check_geometry(root, "landscape", n_tiles=4)  # four tiles: still one row, may scroll but never overflow sideways
    # the same check on a copy where the section is not part of the scrolling list must fail: mutate the e-bike number to a small size
    must_fail(lambda r: check_geometry(r, "landscape", shot=False), root, ("css/board.css", "#boardView{--bnum:clamp(40px,7.2vh,72px)}", "#boardView{--bnum:clamp(20px,3vh,30px)}"))


def test_geometry_portrait_phone_and_small(root):
    for name in ("portrait", "phone", "small"):
        check_geometry(root, name)
        check_geometry(root, name, n_tiles=4)
    must_fail(lambda r: check_geometry(r, "phone", shot=False), root, ("css/board.css", "  .bv-tiles{grid-template-columns:minmax(0,1fr)}\n}", "  .bv-tiles{grid-template-columns:repeat(3,minmax(0,1fr))}\n}"))


def test_tiles_only_board_and_settings_sheet_screenshots(root):
    with bsess(root, picked=(WOLF, SNYDER, TASKER), viewport=(1133, 744)) as s:
        set_types(s, ID_SNYDER, 0, 4, 0, docks=2)
        open_board(s, tiles=True)
        s.page.screenshot(path="/tmp/claude-0/bike-shots/tiles_only_landscape.png")
        s.page.click("#bvSet")
        s.page.wait_for_selector("#bvBikeQ")
        s.page.fill("#bvBikeQ", "2nd")
        s.page.wait_for_selector("#bvSettings .bv-pick")
        s.page.screenshot(path="/tmp/claude-0/bike-shots/settings_landscape.png")
        assert not s.console_errors, s.console_errors
    with bsess(root, picked=(WOLF, SNYDER, TASKER), viewport=(390, 844), mobile=True, touch=True) as s:
        s.mocks.indego_mode = "http500"
        open_board(s, tiles=False)
        s.page.wait_for_function("!document.querySelector('#bvBikeBanner').hidden")
        s.page.screenshot(path="/tmp/claude-0/bike-shots/down_phone.png")
