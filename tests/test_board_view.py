"""The "My stops board" view (js/boardview.js, css/board.css): station-sign rendering of every state, the ticking countdown, settings,
hash/Escape mode switching with focus return, the feed staying awake, the wake lock, night dimming, the nightly refresh, geometry at
four viewports, and the empty/stale/down states.

The logic module (js/board.js) is written elsewhere, so every test installs a fake S.board from an init script (FAKE below). It follows
the shared contract: rows(nowMs) subtracts elapsed minutes from the ETAs captured when a fixture is loaded, and leave states use the
documented thresholds. Each check runs on the real site and again on a copy with one line of the view broken (`must_fail`)."""
import json

from harness import Session
from test_first_run import must_fail, seed
from test_idle_pause import jump

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_every_state_renders_with_words_and_icons",
    "test_settings_call_the_board",
    "test_hash_escape_close_and_focus_return",
    "test_feed_keeps_polling_in_board_mode",
    "test_wake_lock_is_requested_and_requested_again",
    "test_night_dimming_follows_the_clock",
    "test_empty_state_and_missing_board",
    "test_down_and_stale_banners",
}

KEY = "septa.boardview.v1"
BV = "#boardView"
# Installs the fake before the inline script that creates window.SEPTA runs (it is assigned to the namespace as it appears).
FAKE = r"""(function () {
  var fb = window.__fb = { pins: [], arr: {}, pending: {}, buf: 2, bad: false, source: 'live', t0: Date.now(), calls: [], cbs: [], refuse: false,
    options: [{ placeId: 'home', name: 'Home' }, { placeId: 'w1', name: 'Work' }, { placeId: null, name: 'No place' }] };
  function fire() { fb.cbs.forEach(function (f) { f(); }); }
  function walk(p) { return p.walkMin != null ? p.walkMin : (p.auto || 4); }
  fb.load = function (d) {
    fb.pins = d.pins; fb.arr = d.arr || {}; fb.pending = d.pending || {}; fb.buf = d.buf == null ? 2 : d.buf; fb.bad = !!d.bad; fb.source = d.source || 'live';
    fb.t0 = Date.now(); fire();
  };
  fb.api = {
    pins: function () { return fb.pins.map(function (p) { return JSON.parse(JSON.stringify(p)); }); },
    settings: function () { return { bufferMin: fb.buf, bad: fb.bad }; },
    setSettings: function (patch) { fb.calls.push(['setSettings', patch]); if ('bufferMin' in patch) fb.buf = patch.bufferMin; if ('bad' in patch) fb.bad = patch.bad; fire(); return true; },
    updatePin: function (id, patch) { fb.calls.push(['updatePin', id, patch]); if (fb.refuse) return { ok: false, reason: 'invalid' }; fb.pins.forEach(function (p) { if (p.id === id) for (var k in patch) p[k] = patch[k]; }); fire(); return { ok: true }; },
    pinOptions: function () { return fb.options.slice(); },
    MAX_WALK_MIN: 60, MAX_BUFFER_MIN: 15, BAD_EXTRA_MIN: 4,
    removePin: function (id) { fb.calls.push(['removePin', id]); fb.pins = fb.pins.filter(function (p) { return p.id !== id; }); fire(); return true; },
    walkMin: walk,
    placeFor: function (p) { return p.placeName ? { name: p.placeName, lat: 0, lng: 0 } : null; },
    addPin: function () { return { ok: false, reason: 'invalid' }; },
    onChange: function (f) { fb.cbs.push(f); },
    rows: function (now) {
      var el = (now - fb.t0) / 60000, extra = fb.buf + (fb.bad ? fb.api.BAD_EXTRA_MIN : 0);
      return fb.pins.map(function (p) {
        var w = walk(p), down = fb.source === 'down';
        var a = down ? [] : (fb.arr[p.id] || []).map(function (x) { var m = x.etaMin - el, o = { key: x.key, etaMin: m, rough: !!x.rough }; if (m > 45) o.far = true; return o; }).filter(function (x) { return x.etaMin > -1; });
        var leave = null;
        if (a.length && !a[0].far) {
          for (var i = 0; i < a.length && !leave; i++) {
            if (a[i].etaMin < w) continue;
            var li = a[i].etaMin - w - extra;
            leave = { inMin: Math.max(0, Math.floor(li)), state: li > 3 ? 'later' : li >= 1 ? 'soon' : 'now', forKey: a[i].key };
          }
          if (!leave) leave = { inMin: 0, state: 'missed', forKey: a[0].key };
        }
        return { pin: p, placeName: p.placeName || '', walkMin: w, source: fb.source, arrivals: a, leave: leave, pending: fb.pending[p.id] || 0, note: p.note || '' };
      });
    }
  };
  /* js/board.js (the real module) assigns onto S.board when it loads; the fake ignores those writes so the view is tested alone. */
  var locked = {};
  Object.keys(fb.api).forEach(function (k) { Object.defineProperty(locked, k, { enumerable: true, get: function () { return fb.api[k]; }, set: function () {} }); });
  var ns;
  Object.defineProperty(window, 'SEPTA', { configurable: true, get: function () { return ns; }, set: function (v) { ns = v; v.board = locked; } });
})();"""
# The real js/board.js would fill S.board, so "no board" is a namespace slot that swallows its writes.
NOBOARD = """(function () { var ns; Object.defineProperty(window, 'SEPTA', { configurable: true, get: function () { return ns; },
  set: function (v) { ns = v; v.board = new Proxy({}, { set: function () { return true; }, get: function () { return undefined; } }); } }); })();"""

# walk 4 + buffer 2 = 6 minutes of lead time; ETA minus 6 is the leave-in value.
FIXTURE = {
    "pins": [
        {"id": "p1", "placeId": "home", "route": "57", "stopName": "Moyamensing Av & Snyder Av", "placeName": "Home", "walkMin": None, "auto": 4},
        {"id": "p2", "placeId": "home", "route": "47", "stopName": "9th St & Washington Av", "placeName": "Home", "walkMin": 5},
        {"id": "p3", "placeId": "w1", "route": "21", "stopName": "Chestnut St & 17th St", "placeName": "Work", "walkMin": 3},
        {"id": "p4", "placeId": "home", "route": "23", "stopName": "Germantown Av & Chestnut Hill", "placeName": "Home", "walkMin": 8},
        {"id": "p5", "placeId": "home", "route": "42", "stopName": "Walnut St & 10th St", "placeName": "Home", "walkMin": 6},
    ],
    "arr": {
        "p1": [{"key": "a1", "etaMin": 13.4}, {"key": "a2", "etaMin": 21.2}],     # later: leave in 7 (7.4 rounded down)
        "p2": [{"key": "b1", "etaMin": 9.1, "rough": True}],                       # soon, rough ETA: leave in 2 (2.1 rounded down)
        "p3": [{"key": "c1", "etaMin": 4.6}, {"key": "c2", "etaMin": 17.0}],       # now (3 + 2 = 5 needed, 4.6 left, still makeable)
        "p4": [{"key": "d1", "etaMin": 5.0}],                                      # missed (walk is 8)
    },                                                                              # p5: nothing heading there
    "buf": 2,
}
PORTRAIT, LANDSCAPE, PHONE, SMALL = (744, 1133), (1133, 744), (390, 844), (320, 640)


def sess(root, viewport=(1133, 744), extra=(), board=True, **kw):
    scripts = [FAKE if board else NOBOARD] + list(extra)
    return Session(root, viewport=viewport, init_scripts=scripts, **kw)


def board_open(s, fixture=FIXTURE, hash_="#board"):
    s.open(hash_=hash_)
    s.wait_live()
    s.page.wait_for_selector(BV, state="visible")
    if fixture is not None:
        load(s, fixture)


def load(s, fixture):
    s.page.evaluate("(d) => { window.__fb.load(d); window.SEPTA.boardview.render(); }", fixture)


def txt(s, sel):
    return s.page.inner_text(sel).strip()


def row(s, n):
    return s.page.locator("#bvList > li").nth(n)


def set_clock(s, h, m=0):
    """The page's local time (Playwright takes seconds since the epoch)."""
    s.page.clock.set_system_time(s.page.evaluate(f"new Date(2026, 9, 10, {h}, {m}, 0).getTime()") / 1000)


def with_fixture(**patch):
    d = json.loads(json.dumps(FIXTURE))
    d.update(patch)
    return d


# ---------------------------------------------------------------- rendering
def _every_state(root):
    with sess(root) as s:
        board_open(s)
        assert s.page.locator("#bvList > li").count() == 5
        assert s.page.get_attribute(BV, "role") == "region" and s.page.get_attribute(BV, "aria-label") == "My stops board"
        r = [row(s, i) for i in range(5)]
        assert r[0].get_attribute("data-state") == "later" and r[1].get_attribute("data-state") == "soon"
        assert r[2].get_attribute("data-state") == "now" and r[3].get_attribute("data-state") == "missed"
        # the route badge, stop name and "from <place> · <walk> min walk"
        assert r[0].locator(".rbadge").inner_text() == "57"
        assert r[0].locator(".bv-stop").inner_text() == "Moyamensing Av & Snyder Av"
        assert r[0].locator(".bv-from").inner_text() == "from Home · 4 min walk"
        assert r[2].locator(".bv-from").inner_text() == "from Work · 3 min walk"
        # the two big numbers, and the second arrival
        assert r[0].locator(".bv-bus .bv-v").inner_text() == "13 min" and r[0].locator(".bv-bus .bv-x").inner_text() == "then 21 min"
        assert r[0].locator(".bv-leave .bv-v").inner_text() == "7 min", "7.4 minutes is shown rounded down"
        assert r[0].locator(".bv-bus .bv-k").inner_text() == "Bus in (estimate)" and r[0].locator(".bv-leave .bv-k").inner_text() == "Leave in"
        # a rough ETA says "about" and carries the estimate tag
        assert r[1].locator(".bv-bus .bv-v").inner_text() == "about 9 min"
        assert r[1].locator(".bv-bus .bv-tag").inner_text().lower() == "estimate"
        assert r[0].locator(".bv-tag").count() == 0
        # every state has a word AND an icon (never colour alone)
        words = {0: "later", 1: "SOON", 2: "LEAVE NOW", 3: "MISSED"}
        for i, w in words.items():
            st = r[i].locator(".bv-state")
            assert st.inner_text().strip().lower() == w.lower(), (i, st.inner_text())
            assert st.locator("svg").count() == 1 and st.get_attribute("data-s") == r[i].get_attribute("data-state")
        shapes = {r[i].locator(".bv-state svg").inner_html() for i in words}
        assert len(shapes) == 4, "each state has its own shape"
        assert r[2].locator(".bv-leave .bv-v").inner_text() == "Now" and r[3].locator(".bv-leave .bv-v").inner_text() == "—"
        # no bus on the way
        assert r[4].locator(".bv-none").inner_text() == "No bus heading here right now" and not r[4].locator(".bv-bus").is_visible()
        # accessible names
        assert r[0].get_attribute("aria-label") == "Route 57 at Moyamensing Av & Snyder Av, bus in 13 minutes (estimate), leave in 7 minutes"
        assert "leave now" in r[2].get_attribute("aria-label") and "miss" in r[3].get_attribute("aria-label")
        assert "about 9 minutes" in r[1].get_attribute("aria-label") and "estimate" in r[1].get_attribute("aria-label")
        assert s.page.evaluate("document.querySelector('#bvList').tagName") == "UL"
        assert s.page.get_attribute("#bvClock", "aria-hidden") == "true"
        assert txt(s, ".bv-fine") == "Estimates from each bus's distance and speed, not official SEPTA predictions."
        assert not s.page.locator("#bvBanner").is_visible()
        # the next bus is the main number when the first cannot be made
        d = with_fixture(arr={"p1": [{"key": "a1", "etaMin": 3.0}, {"key": "a2", "etaMin": 15.0}]})
        load(s, d)
        assert row(s, 0).locator(".bv-bus .bv-v").inner_text() == "15 min" and row(s, 0).locator(".bv-bus .bv-x").inner_text() == ""
        assert row(s, 0).locator(".bv-leave .bv-v").inner_text() == "9 min" and row(s, 0).get_attribute("data-state") == "later"
        assert not s.console_errors, s.console_errors


def test_every_state_renders_with_words_and_icons(root):
    _every_state(root)
    must_fail(_every_state, root, ("js/boardview.js", "b.appendChild(el('span', null, STATE_WORD[st]));", ""))


def _countdown(root):
    with sess(root) as s:
        board_open(s)
        assert row(s, 0).locator(".bv-bus .bv-v").inner_text() == "13 min"
        before = txt(s, "#bvClock")
        s.tick(65000)
        assert row(s, 0).locator(".bv-bus .bv-v").inner_text() == "12 min", row(s, 0).inner_text()
        assert row(s, 0).locator(".bv-leave .bv-v").inner_text() == "6 min"
        s.tick(5 * 60000, cap_ms=300)
        assert row(s, 0).locator(".bv-bus .bv-v").inner_text() == "7 min" and row(s, 0).locator(".bv-leave .bv-v").inner_text() == "1 min"
        assert row(s, 0).get_attribute("data-state") == "soon"
        assert txt(s, "#bvClock") != before
        # the row element survives the ticks (nothing is rebuilt each second)
        s.page.evaluate("document.querySelector('#bvList > li').dataset.mark = 'x'")
        s.tick(3000)
        assert s.page.evaluate("document.querySelector('#bvList > li').dataset.mark") == "x"


def test_countdown_ticks_each_second_and_clock_is_12_hour(root):
    _countdown(root)
    must_fail(_countdown, root, ("js/boardview.js", "setInterval(tick, 1000);", "setInterval(tick, 3600000);"))


def test_clock_format_and_updated_age(root):
    with sess(root) as s:
        board_open(s)
        set_clock(s, 15, 7)
        s.tick(1500)
        assert txt(s, "#bvClock") == "3:07 PM", txt(s, "#bvClock")
        set_clock(s, 0, 5)
        s.tick(1500)
        assert txt(s, "#bvClock") == "12:05 AM", txt(s, "#bvClock")
        s.tick(20000)
        assert txt(s, "#bvUpd").startswith("Updated ") and txt(s, "#bvUpd").endswith(" ago"), txt(s, "#bvUpd")
    with sess(root) as s:
        s.open(hash_="#board")
        s.page.evaluate("window.SEPTA.util.state.src.bus.ok = 0")
        s.tick(1500)
        assert txt(s, "#bvUpd") == "Waiting for the first update"


# ---------------------------------------------------------------- the fields added by the review fixes
CONTRACT = {
    "pins": [
        {"id": "c1", "placeId": "home", "route": "21", "stopName": "Chestnut St & 17th St", "placeName": "Home", "walkMin": 4},
        {"id": "c2", "placeId": "home", "route": "17", "stopName": "Broad St & Snyder Av", "placeName": "Home", "walkMin": 6},
        {"id": "c3", "placeId": "gone", "route": "33", "stopName": "23rd St & Market St", "placeName": "", "walkMin": 5, "note": "place-removed"},
        {"id": "c4", "placeId": "home", "route": "42", "stopName": "Walnut St & 10th St", "placeName": "Home", "walkMin": 1},
        {"id": "c5", "placeId": "home", "route": "57", "stopName": "Moyamensing Av & Snyder Av", "placeName": "Home", "walkMin": 5},
    ],
    "arr": {
        "c1": [{"key": "f1", "etaMin": 52.4}],                                 # far: only "45+ min", no leave advice
        "c3": [{"key": "g1", "etaMin": 10.5}],
        "c4": [{"key": "h1", "etaMin": 0.6}],                                  # under a minute: "Due"
        "c5": [{"key": "i1", "etaMin": 12.9}, {"key": "i2", "etaMin": 48.0}],  # then a far one
    },
    "pending": {"c2": 2},                                                       # buses are coming but none can be timed
    "buf": 2,
}


def _contract_rows(root):
    with sess(root) as s:
        board_open(s, fixture=CONTRACT)
        r = [row(s, i) for i in range(5)]
        # far: the number says 45+ and the leave column gives no advice from such an uncertain time
        assert r[0].locator(".bv-bus .bv-v").inner_text() == "45+ min", r[0].inner_text()
        assert r[0].locator(".bv-leave .bv-v").inner_text() == "\u2014" and "Too far ahead to say" in r[0].locator(".bv-leave").inner_text()
        assert r[0].get_attribute("data-state") == "" and "more than 45 minutes (estimate)" in r[0].get_attribute("aria-label")
        # pending: a bus is on its way but cannot be timed
        assert r[1].locator(".bv-none").inner_text() == "Bus nearby, time not known yet" and not r[1].locator(".bv-bus").is_visible()
        assert "a bus is nearby, time not known yet" in r[1].get_attribute("aria-label")
        # a removed place is named on the row, with the walk time that is used instead
        assert r[2].locator(".bv-from").inner_text() == "Place removed, walk set to 5 min", r[2].locator(".bv-from").inner_text()
        assert "place removed, walk set to 5 minutes" in r[2].get_attribute("aria-label")
        assert r[2].locator(".bv-bus .bv-v").inner_text() == "10 min"
        # under a minute: Due, never "0 min" or "1 min"
        assert r[3].locator(".bv-bus .bv-v").inner_text() == "Due", r[3].locator(".bv-bus .bv-v").inner_text()
        assert "less than a minute" in r[3].get_attribute("aria-label")
        # 12.9 minutes is 12, not 13; the second bus is far
        assert r[4].locator(".bv-bus .bv-v").inner_text() == "12 min" and r[4].locator(".bv-bus .bv-x").inner_text() == "then 45+ min", r[4].inner_text()
        assert r[4].locator(".bv-leave .bv-v").inner_text() == "5 min"  # 12.9 - 5 - 2 = 5.9, rounded down
        # every bus time on the board is marked as an estimate
        assert r[0].locator(".bv-bus .bv-k").inner_text() == "Bus in (estimate)"
        assert "(estimate)" in r[4].get_attribute("aria-label")
        assert not s.console_errors, s.console_errors


def test_pending_far_removed_and_rounded_rows(root):
    _contract_rows(root)
    must_fail(_contract_rows, root, ("js/boardview.js", "if (a.far) setValue(node, pre, FAR_MIN + '+', 'min');", "if (a.far) setValue(node, pre, String(whole(a.etaMin)), 'min');"))
    must_fail(_contract_rows, root, ("js/boardview.js", "        : r.pending > 0\n", "        : false\n"))
    must_fail(_contract_rows, root, ("js/boardview.js", "      r.note === 'place-removed'\n        ? 'Place", "      false\n        ? 'Place"))
    must_fail(_contract_rows, root, ("js/boardview.js", "return Math.max(0, Math.floor(m));", "return Math.max(0, Math.round(m));"))
    must_fail(_contract_rows, root, ("js/boardview.js", "else if (whole(a.etaMin) < 1) setValue(node, pre, 'Due', '');", "else if (whole(a.etaMin) < 1) setValue(node, pre, '0', 'min');"))
    must_fail(_contract_rows, root, ("js/boardview.js", "t += ' (estimate)';", ""))


def _checking(root):
    with sess(root) as s:
        board_open(s, fixture=with_fixture(source="down"))
        s.page.evaluate("window.SEPTA.util.state.src.bus.ok = 0")
        s.tick(1500)
        assert txt(s, "#bvBanner") == "Checking live data", txt(s, "#bvBanner")
        assert row(s, 0).locator(".bv-none").inner_text() == "Checking live data"
        assert "checking live data" in row(s, 0).get_attribute("aria-label")
        s.tick(7000)
        s.page.evaluate("window.SEPTA.util.state.src.bus.ok = 0")
        s.tick(1500)
        assert txt(s, "#bvBanner") == "Live data unavailable. Times hidden.", txt(s, "#bvBanner")
        assert row(s, 0).locator(".bv-none").inner_text() == "Times hidden"


def test_checking_live_data_before_unavailable(root):
    _checking(root)
    must_fail(_checking, root, ("js/boardview.js", "CHECK_MS = 8000", "CHECK_MS = 0"))
    must_fail(_checking, root, ("js/boardview.js", "checking = !state.src.bus.ok && Date.now() - openedAt < CHECK_MS", "checking = false"))


# ---------------------------------------------------------------- settings
def _settings(root):
    with sess(root) as s:
        board_open(s)
        assert not s.page.locator("#bvSettings").is_visible()
        s.page.click("#bvSet")
        assert s.page.get_attribute("#bvSet", "aria-expanded") == "true" and s.page.locator("#bvSettings").is_visible()
        calls = lambda: s.page.evaluate("window.__fb.calls")  # noqa: E731
        last = lambda: (calls() or [None])[-1]  # noqa: E731
        s.page.click('[aria-label="More minutes to get ready"]')
        assert last() == ["setSettings", {"bufferMin": 3}], calls()
        s.page.click('[aria-label="Less minutes to get ready"]')
        s.page.click('[aria-label="Less minutes to get ready"]')
        assert last() == ["setSettings", {"bufferMin": 1}], calls()
        # the countdown behind the sheet follows the setting
        assert row(s, 0).locator(".bv-leave .bv-v").inner_text() == "8 min"
        s.page.click('[aria-label="Less minutes to get ready"]')
        assert s.page.locator('[aria-label="Less minutes to get ready"]').is_disabled(), "buffer stops at 0"
        s.page.evaluate("window.__fb.buf = 15; window.__fb.cbs[0]()")
        s.page.click("#bvSet"); s.page.click("#bvSet")
        assert s.page.locator('[aria-label="More minutes to get ready"]').is_disabled(), "buffer stops at 15"
        s.page.check('[data-fk="bad"]')
        assert last() == ["setSettings", {"bad": True}], calls()
        # per-pin walk time: stepper, "Automatic", Remove
        s.page.click('[aria-label="More walk minutes for Route 47 at 9th St & Washington Av from Home"]')
        assert last() == ["updatePin", "p2", {"walkMin": 6}], calls()
        # the place picker lists the stop-card choices and saves the choice
        sel = '[aria-label="Place for Route 47 at 9th St & Washington Av from Home"]'
        assert s.page.eval_on_selector(sel, "e => [...e.options].map(o => o.text)") == ["Home", "Work", "No place"]
        assert s.page.input_value(sel) == "home"
        s.page.select_option(sel, "w1")
        assert last() == ["updatePin", "p2", {"placeId": "w1"}], calls()
        s.page.select_option(sel, "")
        assert last() == ["updatePin", "p2", {"placeId": None}], calls()
        s.page.uncheck('[data-fk="a0"]')
        assert last() == ["updatePin", "p1", {"walkMin": 4}], calls()
        s.page.check('[data-fk="a0"]')
        assert last() == ["updatePin", "p1", {"walkMin": None}], calls()
        assert "Automatic, 4 min" in txt(s, "#bvSettings")
        s.page.click('[aria-label="Remove Route 47 at 9th St & Washington Av from Home"]')
        assert last() == ["removePin", "p2"], calls()
        assert s.page.locator("#bvList > li").count() == 4
        # night dimming is its own saved choice
        assert s.page.is_checked('[data-fk="dim"]') and json.loads(s.page.evaluate(f"localStorage.getItem('{KEY}')") or "null") in (None, {"dim": True})
        s.page.uncheck('[data-fk="dim"]')
        assert json.loads(s.page.evaluate(f"localStorage.getItem('{KEY}')")) == {"dim": False}
        s.page.keyboard.press("Escape")
        assert not s.page.locator("#bvSettings").is_visible() and s.page.locator(BV).is_visible(), "Escape closes the sheet first"
        assert s.page.evaluate("document.activeElement.id") == "bvSet"
        assert not s.console_errors, s.console_errors


def test_settings_call_the_board(root):
    _settings(root)
    must_fail(_settings, root, ("js/boardsettings.js", "saved(b.setSettings({ bufferMin: Math.min(bufMax, cfg.bufferMin + 1) }));", ""))
    must_fail(_settings, root, ("js/boardsettings.js", "saved(b.updatePin(p.id, { placeId: sel.value || null }));", ""))


def _limits(root):
    two = with_fixture(pins=[
        {"id": "q1", "placeId": "home", "route": "47", "stopName": "9th St & Washington Av", "placeName": "Home", "walkMin": 20},
        {"id": "q2", "placeId": "w1", "route": "47", "stopName": "9th St & Washington Av", "placeName": "Work", "walkMin": 5},
    ], arr={})
    with sess(root) as s:
        board_open(s, fixture=two)
        s.page.evaluate("Object.assign(window.__fb.api, { MAX_WALK_MIN: 20, MAX_BUFFER_MIN: 5, BAD_EXTRA_MIN: 6 }); window.__fb.buf = 5")
        s.page.click("#bvSet")
        t = txt(s, "#bvSettings")
        assert "Snow or ice: add 6 min" in t, t
        assert s.page.locator('[aria-label="More minutes to get ready"]').is_disabled(), "buffer stops at the board's limit"
        assert s.page.locator('[aria-label="More walk minutes for Route 47 at 9th St & Washington Av from Home"]').is_disabled(), "walk stops at the board's limit"
        assert s.page.locator('[aria-label="More walk minutes for Route 47 at 9th St & Washington Av from Work"]').is_enabled()
        # every control in the sheet has its own accessible name, even for the same stop reached from two places
        names = s.page.evaluate("[...document.querySelectorAll('#bvSettings button, #bvSettings input, #bvSettings select')].map(e => e.getAttribute('aria-label') || (e.closest('label') || {}).textContent || e.textContent)")
        dup = {n for n in names if names.count(n) > 1 and n != "−" and n != "+"}
        assert not dup, dup
        assert len([n for n in names if n.startswith("Automatic walk time for")]) == 2, names


def test_settings_limits_come_from_the_board_and_names_are_unique(root):
    _limits(root)
    must_fail(_limits, root, ("js/boardsettings.js", "walkMax = lim('MAX_WALK_MIN', 60)", "walkMax = 60"))
    must_fail(_limits, root, ("js/boardsettings.js", "bufMax = lim('MAX_BUFFER_MIN', 15)", "bufMax = 15"))
    must_fail(_limits, root, ("js/boardsettings.js", "extra = lim('BAD_EXTRA_MIN', 4)", "extra = 4"))
    must_fail(_limits, root, ("js/boardsettings.js", "auto2.querySelector('input').setAttribute('aria-label', 'Automatic walk time for ' + nm);", ""))


def _refused(root):
    with sess(root) as s:
        board_open(s)
        s.page.click("#bvSet")
        s.page.evaluate("window.__fb.refuse = true")
        s.page.click('[aria-label="More walk minutes for Route 47 at 9th St & Washington Av from Home"]')
        s.tick(200)
        assert txt(s, "#bvLive") == "Could not save that change", txt(s, "#bvLive")
        assert "5 min" in s.page.inner_text('#bvSettings output[aria-label^="walk minutes for Route 47"]'), "the sheet shows the saved value again"
        s.page.evaluate("window.__fb.refuse = false")
        s.page.click('[aria-label="More walk minutes for Route 47 at 9th St & Washington Av from Home"]')
        s.tick(200)
        assert "6 min" in s.page.inner_text('#bvSettings output[aria-label^="walk minutes for Route 47"]')


def test_a_refused_change_is_announced(root):
    _refused(root)
    must_fail(_refused, root, ("js/boardsettings.js", "if (res === false || (res && res.ok === false)) say('Could not save that change');", ""))


def test_view_storage_is_validated_and_backed_up(root):
    for raw, dim in (("{not json", True), ('{"dim":"no"}', True), ('{"dim":false}', False), ("[1]", True), ('{"dim":true}', True)):
        with sess(root, extra=[seed(KEY, raw)]) as s:
            board_open(s)
            assert s.page.evaluate("document.querySelector('#bvSettings')") is not None
            s.page.click("#bvSet")
            assert s.page.is_checked('[data-fk="dim"]') is dim, (raw, dim)
            bak = s.page.evaluate(f"localStorage.getItem('{KEY}.bak')")
            assert (bak == raw) is (raw not in ('{"dim":false}', '{"dim":true}')), (raw, bak)


# ---------------------------------------------------------------- mode switching
def _switching(root):
    with sess(root) as s:
        s.open()
        s.wait_live()
        assert not s.page.locator(BV).is_visible()
        s.page.click("#btnBoard")
        s.page.wait_for_selector(BV, state="visible")
        assert s.page.evaluate("location.hash") == "#board"
        assert s.page.evaluate("document.querySelector('#app').inert") is True
        assert s.page.evaluate("getComputedStyle(document.querySelector('#app')).visibility") == "hidden"
        assert s.page.evaluate("document.activeElement.id") == "boardView"
        s.page.keyboard.press("Escape")
        assert not s.page.locator(BV).is_visible()
        assert s.page.evaluate("document.querySelector('#app').inert") is False
        assert s.page.evaluate("document.activeElement.id") == "btnBoard", s.page.evaluate("document.activeElement.outerHTML")
        assert s.page.evaluate("location.hash") in ("", "#")
        assert s.page.evaluate("document.body.classList.contains('board-on')") is False
        # Close button; the app is usable again
        s.page.click("#btnBoard")
        s.page.wait_for_selector(BV, state="visible")
        s.page.click("#bvClose")
        assert not s.page.locator(BV).is_visible() and s.page.evaluate("document.activeElement.id") == "btnBoard"
        s.page.fill("#addr", "x")
        assert s.page.input_value("#addr") == "x"
        assert s.page.evaluate("(() => { const m = window.SEPTA.map.map, s = m.getSize(), c = m.getContainer(); return s.x === c.clientWidth && s.y === c.clientHeight; })()")
        # browser Back (hash change) leaves too
        s.page.click("#btnBoard")
        s.page.wait_for_selector(BV, state="visible")
        s.page.evaluate("history.back()")
        s.page.wait_for_selector(BV, state="hidden")
        # the hash opened directly: no opener, focus goes to the Board button (a button: no keyboard rises on an iPad)
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector(BV, state="visible")
        s.page.click("#bvClose")
        assert s.page.evaluate("document.activeElement.id") == "btnBoard"
        assert not s.console_errors, s.console_errors
    with sess(root) as s:
        s.open(path="index.html?board=1")
        s.page.wait_for_selector(BV, state="visible")
        s.page.click("#bvClose")
        assert not s.page.locator(BV).is_visible() and "board" not in s.page.evaluate("location.search")
        assert s.page.evaluate("document.activeElement.id") == "btnBoard", "opened from the URL: focus must not land in the address box"
        assert s.page.evaluate("document.activeElement.tagName") == "BUTTON"
    with sess(root) as s:  # Escape in board mode does not also close the stop card underneath
        s.open(hash_="#stop=14880&route=21")
        s.wait_live()
        s.page.wait_for_selector("#stopCard", state="visible")
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector(BV, state="visible")
        s.page.keyboard.press("Escape")
        assert not s.page.locator(BV).is_visible() and s.page.locator("#stopCard").is_visible(), "the stop card was not closed by the same Escape"


def test_hash_escape_close_and_focus_return(root):
    _switching(root)
    must_fail(_switching, root, ("js/boardview.js", "app.inert = false;", "app.inert = true;"))
    must_fail(_switching, root, ("js/boardview.js", "        ? opener\n", "        ? null\n"))
    must_fail(_switching, root, ("js/boardview.js", "        : $('#btnBoard');", "        : $('#addr');"))


# ---------------------------------------------------------------- the feed stays awake
def _awake(root):
    from test_idle_pause import window_hits
    with sess(root) as s:
        board_open(s)
        jump(s, 61)
        assert not s.page.locator("#idleBar").is_visible(), "no idle pause while the board shows"
        hits = [h for h in window_hits(s, 3) if h.startswith("TransitView")]
        assert len(hits) >= 3, hits
        # the bus feed is wanted even when every bus mode is off
        s.page.evaluate("const f = window.SEPTA.util.state.filters; f.bus = f.trolley = f.subway = false")
        assert s.page.evaluate("window.SEPTA.feed.wantedSources().bus") is True
        s.page.evaluate("location.hash = ''")
        s.page.wait_for_selector(BV, state="hidden")
        assert s.page.evaluate("window.SEPTA.feed.wantedSources().bus") is False
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector(BV, state="visible")
        # the board shows buses only: the train feed stays off however the chips are set, and comes back with the app
        s.page.evaluate("window.SEPTA.util.state.filters.train = true")
        assert s.page.evaluate("window.SEPTA.feed.wantedSources().train") is False
        s.page.evaluate("location.hash = ''")
        s.page.wait_for_selector(BV, state="hidden")
        assert s.page.evaluate("window.SEPTA.feed.wantedSources().train") is True
    with sess(root) as s:  # control: the same idle hour without the board does pause
        s.open()
        s.wait_live()
        jump(s, 61)
        assert s.page.locator("#idleBar").is_visible()
        # slow cadence after 10 quiet minutes applies without the board only
    with sess(root) as s:
        set_clock(s, 12)  # by day: the dimmed cadence does not apply
        board_open(s)
        for _ in range(14):
            s.tick(60000)
        s.worker.hits.clear()
        for _ in range(4):
            s.tick(60000)
        n = len([h for h in s.worker.hits if h.startswith("TransitView")])
        assert n >= 12, n  # 15 s cadence (16 in 4 minutes); the quiet cadence would give 8


def test_feed_keeps_polling_in_board_mode(root):
    _awake(root)
    must_fail(_awake, root, ("js/feed.js", "return !awake && Date.now() - lastUse >= IDLE_MS;", "return Date.now() - lastUse >= IDLE_MS;"))
    must_fail(_awake, root, ("js/feed.js", "return !awake && Date.now() - lastUse >= QUIET_MS", "return Date.now() - lastUse >= QUIET_MS"))
    must_fail(_awake, root, ("js/feed.js", "train: !awake && !!f.train", "train: !!f.train"))
    must_fail(_awake, root, ("js/feed.js", "|| hasActiveRule() || state.stop || awake),", "|| hasActiveRule() || state.stop),"))


def hits_over(s, minutes):
    s.worker.hits.clear()
    for _ in range(minutes):
        s.tick(60000)
    return len([h for h in s.worker.hits if h.startswith("TransitView")])


def _dim_cadence(root):
    with sess(root) as s:  # dimmed at 11 PM: every 30 s
        set_clock(s, 23)
        board_open(s)
        s.tick(5000)
        assert s.page.evaluate("document.querySelector('#boardView').classList.contains('dim')")
        n = hits_over(s, 4)
        assert 5 <= n <= 10, n
        s.page.click("#bvSet")
        s.page.uncheck('[data-fk="dim"]')  # dimming off: back to every 15 s
        s.tick(2000)
        n = hits_over(s, 4)
        assert n >= 12, n
    with sess(root) as s:  # by day the board polls every 15 s
        set_clock(s, 12)
        board_open(s)
        s.tick(5000)
        assert hits_over(s, 4) >= 12


def test_dimmed_board_refreshes_every_30_seconds(root):
    _dim_cadence(root)
    must_fail(_dim_cadence, root, ("js/feed.js", "if ((isQuiet() || awakeDim) &&", "if ((isQuiet()) &&"))
    must_fail(_dim_cadence, root, ("js/boardview.js", "S.feed.setAwake(true, (dimmed = dim));", "S.feed.setAwake(true, (dimmed = false));"))


# ---------------------------------------------------------------- wake lock
WAKE = r"""(function () {
  var w = window.__wake = { requests: 0, released: 0, sentinels: [], fail: false, args: [] };
  Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: function (t) {
    w.requests++; w.args.push(t);
    if (w.fail) return Promise.reject(new Error('NotAllowedError'));
    var ls = [], s = { released: false, addEventListener: function (n, f) { ls.push(f); },
      release: function () { s.released = true; w.released++; return Promise.resolve(); }, fire: function () { s.released = true; ls.forEach(function (f) { f(); }); } };
    w.sentinels.push(s); return Promise.resolve(s);
  } } });
  window.__hidden = false;
  Object.defineProperty(document, 'hidden', { configurable: true, get: function () { return window.__hidden; } });
})();"""
HIDE = "(h) => { window.__hidden = h; if (h) window.__wake.sentinels.forEach((s) => s.fire()); document.dispatchEvent(new Event('visibilitychange')); }"


def _wake(root):
    with sess(root, extra=[WAKE]) as s:
        s.open()
        s.wait_live()
        assert s.page.evaluate("window.__wake.requests") == 0, "no wake lock outside board mode"
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector(BV, state="visible")
        s.page.wait_for_function("window.__wake.requests === 1")
        assert s.page.evaluate("window.__wake.args") == ["screen"]
        s.page.evaluate(HIDE, True)   # the browser drops the lock when the page is hidden
        s.page.evaluate(HIDE, False)
        s.page.wait_for_function("window.__wake.requests === 2")
        s.page.evaluate(HIDE, False)  # visible again with a live lock: no duplicate request
        assert s.page.evaluate("window.__wake.requests") == 2
        s.page.click("#bvClose")
        assert s.page.evaluate("window.__wake.released") >= 1, "the lock is released when the board closes"
        s.page.evaluate(HIDE, True)
        s.page.evaluate(HIDE, False)
        assert s.page.evaluate("window.__wake.requests") == 2, "no request while the board is closed"
    with sess(root, extra=[WAKE]) as s:  # a refusal is swallowed
        s.page.add_init_script("window.__wake.fail = true")
        s.open(hash_="#board")
        s.page.wait_for_function("window.__wake.requests >= 1")
        s.page.wait_for_selector(BV, state="visible")
        assert not s.console_errors, s.console_errors
    with sess(root, extra=["Object.defineProperty(navigator, 'wakeLock', {value: undefined, configurable: true})"]) as s:  # unsupported
        s.open(hash_="#board")
        s.page.wait_for_selector(BV, state="visible")
        assert not s.console_errors, s.console_errors


def test_wake_lock_is_requested_and_requested_again(root):
    _wake(root)
    must_fail(_wake, root, ("js/boardview.js", "navigator.wakeLock.request('screen')", "navigator.wakeLock.request('none')"))
    must_fail(_wake, root, ("js/boardview.js", "if (!document.hidden) wake();", ""))


# ---------------------------------------------------------------- night dimming
def at(s, h, m=0):
    set_clock(s, h, m)
    s.tick(1500)


def opacity(s):
    s.page.wait_for_timeout(500)
    return float(s.page.evaluate("getComputedStyle(document.querySelector('#boardView')).opacity"))


def _dimming(root):
    with sess(root, reduced_motion="reduce") as s:
        board_open(s)
        for h, m, dim in ((23, 0, True), (12, 0, False), (22, 0, True), (21, 59, False), (3, 30, True), (5, 59, True), (6, 0, False)):
            at(s, h, m)
            on = s.page.evaluate("document.querySelector('#boardView').classList.contains('dim')")
            assert on is dim, (h, m, on)
            assert opacity(s) == (0.8 if dim else 1.0), (h, m)
        s.page.click("#bvSet")
        s.page.uncheck('[data-fk="dim"]')
        at(s, 23, 0)
        assert opacity(s) == 1.0, "dimming off"
    with sess(root, extra=[seed(KEY, {"dim": False})], reduced_motion="reduce") as s:
        board_open(s)
        at(s, 23, 30)
        assert opacity(s) == 1.0, "the saved choice is used"


def test_night_dimming_follows_the_clock(root):
    _dimming(root)
    must_fail(_dimming, root, ("js/boardview.js", "return h >= DIM_FROM || h < DIM_TO;", "return h >= DIM_FROM && h < DIM_TO;"))


def lum(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def pixels(s, clip=None):
    """The rendered pixels (what the screen really shows, opacity and all) as a PIL image."""
    import io
    from PIL import Image
    kw = {"clip": clip} if clip else {}
    return Image.open(io.BytesIO(s.page.screenshot(**kw))).convert("RGB")


def _dim_pixels(root):
    seen = {}
    for scheme in ("light", "dark"):
        with sess(root, color_scheme=scheme, reduced_motion="reduce") as s:
            board_open(s)
            for h, name in ((12, "noon"), (23, "night")):
                at(s, h, 0)
                load(s, FIXTURE)  # the fake clock jumped: capture the arrivals again
                s.page.wait_for_timeout(200)
                full = pixels(s)
                edge = full.getpixel((1, full.height - 2))  # the page margin: nothing but the board's own background
                seen[scheme, name] = lum(edge)
                for sel in ("#bvList > li:nth-child(1) .bv-from", "#bvList > li:nth-child(1) .bv-stop", "#bvList > li:nth-child(4) .bv-state"):
                    r = s.page.evaluate("(q) => { const b = document.querySelector(q).getBoundingClientRect(); return {x: b.x, y: b.y, width: b.width, height: b.height}; }", sel)
                    crop = pixels(s, clip=r)
                    px = list(crop.getdata())
                    bg = max(set(px), key=px.count)
                    fg = max(px, key=lum)
                    assert contrast(fg, bg) >= 4.5, (scheme, name, sel, fg, bg, contrast(fg, bg))
            assert seen[scheme, "night"] <= seen[scheme, "noon"] + 1e-6, (scheme, seen)
            assert seen[scheme, "night"] < 0.01, ("the dimmed page is nearly black in the %s colour scheme" % scheme, seen[scheme, "night"])
            s.shot("board_night_" + scheme)


def test_night_dimming_makes_the_page_darker_in_light_and_dark_mode(root):
    _dim_pixels(root)
    must_fail(_dim_pixels, root, ("css/board.css", "body.board-on{background:#000}", "body.board-on{background:var(--paper)}"))
    must_fail(_dim_pixels, root, ("css/board.css", "#boardView.dim{opacity:.8}", "#boardView.dim{opacity:.4}"))


# ---------------------------------------------------------------- nightly refresh
NET = r"""(function () {
  window.__offline = false; window.__page = 'ok'; window.__fetches = 0;
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: function () { return !window.__offline; } });
  var f = window.fetch;
  window.fetch = function (u, o) {
    if (String(u).indexOf('index.html') >= 0) {
      window.__fetches++;
      if (window.__page === 'down') return Promise.reject(new TypeError('Failed to fetch'));
      if (window.__page === '503') return Promise.resolve(new Response('no', { status: 503 }));
    }
    return f.apply(this, arguments);
  };
})();"""


def nightly_start(s, hour):
    """The page loads at `hour` local, the board opens, and reload() is counted instead of performed."""
    set_clock(s, hour, 0)
    s.open()
    s.wait_live()
    s.page.evaluate("window.__reloads = 0; window.SEPTA.boardview.reload = function () { window.__reloads++; }; 0")
    s.page.clock.pause_at((s.page.evaluate("Date.now()") + 1000) / 1000)
    s.page.evaluate("location.hash = '#board'")
    s.page.wait_for_selector(BV, state="visible")


def reloads(s):
    return s.page.evaluate("window.__reloads")


def later(s, minutes):
    s.page.clock.fast_forward(minutes * 60 * 1000)
    s.tick(2000)


def _nightly(root):
    with sess(root, extra=[NET]) as s:
        nightly_start(s, 15)  # loaded at 15:00; 12 h later is 03:00, so the first 4 AM after that is 04:00 next day
        later(s, 11 * 60)     # 02:00: not yet 12 h
        assert reloads(s) == 0
        later(s, 105)         # 03:45: past 12 h, before 4 AM
        assert reloads(s) == 0, "waits for 4 AM"
        later(s, 14)          # 03:59
        assert reloads(s) == 0
        s.page.mouse.click(300, 300)  # a tap just before 4 AM
        later(s, 6)           # 04:05: past 4 AM but only 6 quiet minutes
        assert reloads(s) == 0, "not while someone is using it"
        later(s, 5)           # 04:10: 11 quiet minutes
        s.page.wait_for_function("window.__reloads >= 1")
        assert s.page.evaluate("window.__fetches") >= 1, "the page is fetched before it is reloaded"
    with sess(root, extra=[NET]) as s:  # open for only 5 hours at 04:10: too early
        nightly_start(s, 23)
        later(s, 5 * 60 + 10)
        s.page.wait_for_timeout(300)
        assert reloads(s) == 0, "not before the page has been open 12 hours"


def test_nightly_reload_waits_for_four_am_and_quiet(root):
    _nightly(root)
    q = "if (reloadBusy || now < reloadAt() || now - lastInput < RELOAD_QUIET_MS) return;"
    must_fail(_nightly, root, ("js/boardview.js", q, "if (reloadBusy || now - lastInput < RELOAD_QUIET_MS) return;"))
    must_fail(_nightly, root, ("js/boardview.js", q, "if (reloadBusy || now < reloadAt()) return;"))


def _offline_retry(root):
    with sess(root, extra=[NET]) as s:
        nightly_start(s, 15)
        later(s, 12 * 60 + 50)                        # 03:50, nobody around
        s.page.evaluate("window.__offline = true")
        later(s, 21)                                  # 04:11 first try: offline
        s.page.wait_for_timeout(300)
        assert reloads(s) == 0 and s.page.evaluate("window.__fetches") == 0, "offline: no reload and no fetch"
        s.page.evaluate("window.__offline = false; window.__page = '503'")
        later(s, 5)                                   # 04:16: online again but the next try is not due
        assert reloads(s) == 0 and s.page.evaluate("window.__fetches") == 0, "retries wait 10 minutes"
        later(s, 6)                                   # 04:22: the retry fetches, gets an error page
        s.page.wait_for_function("window.__fetches === 1")
        s.page.wait_for_timeout(300)
        assert reloads(s) == 0, "an error page is not a reason to reload"
        s.page.evaluate("window.__page = 'down'")
        later(s, 10)                                  # 04:32: the request fails
        s.page.wait_for_function("window.__fetches === 2")
        s.page.wait_for_timeout(300)
        assert reloads(s) == 0
        s.page.evaluate("window.__page = 'ok'")
        later(s, 10)                                  # 04:42: the page is there
        s.page.wait_for_function("window.__reloads >= 1")


def test_nightly_reload_checks_the_network_and_retries(root):
    _offline_retry(root)
    must_fail(_offline_retry, root, ("js/boardview.js", "if (navigator.onLine === false || typeof fetch !== 'function') return;", "if (typeof fetch !== 'function') return;"))
    must_fail(_offline_retry, root, ("js/boardview.js", "RELOAD_RETRY_MS = 10 * 60000", "RELOAD_RETRY_MS = 1000"))
    must_fail(_offline_retry, root, ("js/boardview.js", "if (r && r.ok) api.reload();", "api.reload();"))
    must_fail(_offline_retry, root, ("js/boardview.js", "    fetch(location.href.split('#')[0], { cache: 'no-store' }).then(", "    Promise.resolve({ ok: true }).then("))


def _not_by_day(root):
    with sess(root, extra=[NET]) as s:
        nightly_start(s, 15)
        later(s, 48 * 60)                             # two days later, 15:00 and nobody has touched it
        s.page.wait_for_timeout(300)
        assert reloads(s) == 0 and s.page.evaluate("window.__fetches") == 0, "never reloads at 3 PM"
    with sess(root, extra=[NET]) as s:
        nightly_start(s, 15)
        later(s, 12 * 60 + 50)                        # 03:50
        s.page.evaluate("window.__offline = true")
        later(s, 21)                                  # 04:11: offline, so no try
        later(s, 100)                                 # 05:51 and again 06:31: the window is over
        later(s, 40)
        s.page.evaluate("window.__offline = false")
        later(s, 30)                                  # 07:00
        s.page.wait_for_timeout(300)
        assert reloads(s) == 0 and s.page.evaluate("window.__fetches") == 0, "after 6 AM it waits for tomorrow"


def test_nightly_reload_never_happens_by_day(root):
    _not_by_day(root)
    gate = "if (h < RELOAD_HOUR || h >= RELOAD_END || now < reloadTry) return;"
    must_fail(_not_by_day, root, ("js/boardview.js", gate, "if (now < reloadTry) return;"))
    must_fail(_not_by_day, root, ("js/boardview.js", gate, "if (h < RELOAD_HOUR || now < reloadTry) return;"))


def test_nightly_reload_only_in_board_mode(root):
    with sess(root) as s:
        s.open()
        s.wait_live()
        s.page.evaluate("window.__reloads = 0; window.SEPTA.boardview.reload = function () { window.__reloads++; }; 0")
        s.page.clock.pause_at((s.page.evaluate("Date.now()") + 1000) / 1000)
        s.page.clock.fast_forward(40 * 3600 * 1000)
        s.tick(2000)
        assert s.page.evaluate("window.__reloads") == 0, "the normal app is never reloaded under the rider"


# ---------------------------------------------------------------- geometry
def geometry(s, label, big_min=0, stacked=None):
    g = s.page.evaluate("""() => {
      const W = innerWidth, H = innerHeight, out = {W, H, bad: [], clip: [], small: [], tap: [], over: document.documentElement.scrollWidth > W || document.body.scrollWidth > W};
      const root = document.querySelector('#boardView');
      out.rootOver = root.scrollWidth > root.clientWidth + 1;
      for (const e of root.querySelectorAll('*')) {
        const r = e.getBoundingClientRect(); if (!r.width || !e.offsetParent && getComputedStyle(e).position !== 'fixed') continue;
        if (e.closest('[hidden]')) continue;
        if (r.right > W + 1 || r.left < -1) out.bad.push((e.className || e.tagName) + ':' + Math.round(r.left) + '-' + Math.round(r.right));
        if (e.children.length === 0 && e.textContent.trim() && (e.scrollWidth > e.clientWidth + 1) && getComputedStyle(e).display !== 'inline') out.clip.push((e.className || e.tagName) + ':' + e.textContent.trim().slice(0, 20));
        if (e.matches('button, input')) { if (r.height < 43.5 || r.width < 43.5) out.tap.push((e.id || e.className || e.tagName) + ':' + Math.round(r.width) + 'x' + Math.round(r.height)); }
      }
      out.bigMin = Math.min(...[...root.querySelectorAll('.bv-v')].filter(e => e.offsetParent).map(e => parseFloat(getComputedStyle(e).fontSize)));
      const li = root.querySelector('#bvList > li');
      out.badgeH = li.querySelector('.rbadge').getBoundingClientRect().height;
      const w = li.querySelector('.bv-where').getBoundingClientRect(), b = li.querySelector('.bv-bus').getBoundingClientRect(), l = li.querySelector('.bv-leave').getBoundingClientRect();
      out.below = b.top >= w.bottom - 1 && l.top >= w.bottom - 1; out.beside = b.left >= w.right - 1 && l.left >= b.right - 1;
      out.rows = [...root.querySelectorAll('#bvList > li')].map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.bottom)]; });
      out.listH = root.querySelector('#bvList').clientHeight; out.listScroll = root.querySelector('#bvList').scrollHeight;
      out.kWrap = [...root.querySelectorAll('.bv-k')].filter(e => e.offsetParent && e.getBoundingClientRect().height > parseFloat(getComputedStyle(e).fontSize) * 1.5).length;
      out.fineBottom = root.querySelector('.bv-fine').getBoundingClientRect().bottom;
      return out;
    }""")
    assert not g["over"] and not g["rootOver"], (label, "horizontal scroll", g)
    assert not g["bad"], (label, "outside the screen", g["bad"][:6])
    assert not g["clip"], (label, "clipped text", g["clip"][:6])
    assert not g["tap"], (label, "tap targets under 44 px", g["tap"])
    assert g["badgeH"] >= 63.5, (label, g["badgeH"])
    assert g["bigMin"] >= big_min, (label, g["bigMin"])
    assert g["fineBottom"] <= g["H"] + 1, (label, "fine print off screen")
    assert g["kWrap"] == 0, (label, "the column headers (\"Bus in (estimate)\") must stay on one line")
    if stacked is not None:
        assert (g["below"] if stacked else g["beside"]), (label, "layout", g)
    return g


def _geometry(root):
    for vp, kw, stacked, big in (
        (LANDSCAPE, {}, False, 40), (PORTRAIT, {}, True, 40),
        (PHONE, dict(mobile=True, touch=True), True, 40), (SMALL, dict(mobile=True, touch=True), True, 40),
    ):
        with sess(root, viewport=vp, **kw) as s:
            board_open(s)
            g = geometry(s, vp, big_min=big, stacked=stacked)
            if vp == LANDSCAPE:
                assert g["listScroll"] <= g["listH"] + 1, ("five rows fit without scrolling", g)
                s.shot("board_landscape")
            s.page.click("#bvSet")
            geometry(s, (vp, "settings"))
            s.page.click("#bvSet")
            load(s, CONTRACT)  # pending, far, removed-place and due rows
            g2 = geometry(s, (vp, "contract rows"), big_min=big, stacked=stacked)
            if vp == LANDSCAPE:
                assert g2["listScroll"] <= g2["listH"] + 1, ("five rows fit without scrolling", g2)
                s.shot("board_landscape_contract")
            else:
                s.shot("board_" + str(vp[0]))
            load(s, FIXTURE)
            # eight pins: the list scrolls, nothing spills sideways
            many = json.loads(json.dumps(FIXTURE))
            for i in range(5, 8):
                p = {"id": f"p{i+1}", "route": "G1", "stopName": "A very long stop name at Broad Street and Pennsylvania Boulevard", "placeName": "Home", "walkMin": 12}
                many["pins"].append(p)
                many["arr"][p["id"]] = [{"key": f"z{i}", "etaMin": 38.0, "rough": True}, {"key": f"y{i}", "etaMin": 59.0}]
            load(s, many)
            geometry(s, (vp, "eight rows"), big_min=big)
            assert s.page.locator("#bvList > li").count() == 8


def test_geometry_at_four_viewports(root):
    _geometry(root)


def _big(root):
    with sess(root, viewport=LANDSCAPE) as s:
        board_open(s)
        sizes = s.page.evaluate("[...document.querySelectorAll('.bv-v')].filter(e => e.offsetParent).map(e => parseFloat(getComputedStyle(e).fontSize))")
        assert min(sizes) >= 40, sizes
        assert s.page.evaluate("parseFloat(getComputedStyle(document.querySelector('.bv-fine')).fontSize)") >= 13


def test_numbers_are_big_enough_at_station_size(root):
    _big(root)
    must_fail(_big, root, ("css/board.css", "--num:clamp(40px,6.9vh,72px)", "--num:clamp(20px,3vh,72px)"))


# ---------------------------------------------------------------- empty, stale, down, announcements
def _empty(root):
    with sess(root) as s:
        board_open(s, fixture=with_fixture(pins=[], arr={}))
        assert s.page.locator("#bvEmpty").is_visible() and not s.page.locator("#bvList").is_visible()
        assert txt(s, "#bvEmptyMsg") == "Pin a stop to see when to leave. Open any bus stop on the map and tap Pin to board."
        s.page.click("#bvCloseEmpty")
        assert not s.page.locator(BV).is_visible() and s.page.evaluate("document.querySelector('#app').inert") is False
    with sess(root, board=False) as s:  # the logic module is not there at all
        s.open(hash_="#board")
        s.page.wait_for_selector(BV, state="visible")
        assert txt(s, "#bvEmptyMsg") == "Board is not available."
        s.page.keyboard.press("Escape")
        assert not s.page.locator(BV).is_visible()
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector(BV, state="visible")
        s.page.click("#bvClose")
        assert not s.page.locator(BV).is_visible()
        assert not s.console_errors, s.console_errors
    for vp, kw in ((LANDSCAPE, {}), (SMALL, dict(mobile=True, touch=True))):
        with sess(root, viewport=vp, **kw) as s:
            board_open(s, fixture=with_fixture(pins=[], arr={}))
            assert s.page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_empty_state_and_missing_board(root):
    _empty(root)
    must_fail(_empty, root, ("js/boardview.js", "emptyBox.hidden = rows.length > 0;", "emptyBox.hidden = true;"))


def _banners(root):
    with sess(root) as s:
        board_open(s, fixture=with_fixture(source="stale"))
        assert txt(s, "#bvBanner") == "Positions may be out of date" and s.page.locator("#bvBanner").is_visible()
        assert row(s, 0).locator(".bv-bus .bv-v").is_visible(), "stale times stay"
        load(s, with_fixture(source="down"))
        assert txt(s, "#bvBanner") == "Live data unavailable. Times hidden."
        assert s.page.locator("#bvList .bv-v:visible").count() == 0, "no numbers while down"
        assert row(s, 0).locator(".bv-none").inner_text() == "Times hidden"
        assert "times hidden" in row(s, 0).get_attribute("aria-label")
        assert txt(s, ".bv-fine").startswith("Estimates from each bus's distance")
        load(s, with_fixture(source="live"))
        assert not s.page.locator("#bvBanner").is_visible() and row(s, 0).locator(".bv-bus .bv-v").is_visible()
        assert s.page.locator("#bvList > li").count() == 5


def test_down_and_stale_banners(root):
    _banners(root)
    must_fail(_banners, root, ("js/boardview.js", "bus.hidden = lvEl.hidden = !hasNums;", "bus.hidden = lvEl.hidden = false;"))


def _announce(root):
    with sess(root) as s:
        board_open(s)
        live = lambda: s.page.inner_text("#bvLive").strip()  # noqa: E731
        assert live() == "", "nothing is announced for the first draw"
        s.tick(3000)
        assert live() == "", "the countdown is not announced"
        # p2 is soon (leave in 3); three more minutes make it "now"
        s.tick(3 * 60000)
        assert row(s, 1).get_attribute("data-state") == "now"
        assert live() == "Route 47: leave now", live()
        s.page.evaluate("document.querySelector('#bvLive').textContent = ''")
        s.tick(30000)
        assert live() == "", "announced once per change"


def test_live_region_announces_only_new_leave_now(root):
    _announce(root)
    must_fail(_announce, root, ("js/boardview.js", "if (!(key in spoken) && prevState[id] !== undefined)", "if (prevState[id] !== undefined)"))


def _announce_once(root):
    one = with_fixture(pins=[{"id": "p", "placeId": "home", "route": "21", "stopName": "Chestnut St & 17th St", "placeName": "Home", "walkMin": 3}],
                       arr={"p": [{"key": "k1", "etaMin": 20.0}]})
    live = lambda: s.page.inner_text("#bvLive").strip()  # noqa: E731
    with sess(root) as s:
        board_open(s, fixture=one)
        s.tick(15 * 60000)  # 20 - 15 = 5 minutes left, 3 to walk, 2 to get ready: leave now
        assert row(s, 0).get_attribute("data-state") == "now" and live() == "Route 21: leave now", (live(), row(s, 0).get_attribute("data-state"))
        s.page.evaluate("document.querySelector('#bvLive').textContent = ''")
        s.page.evaluate("window.__fb.buf = 0; window.SEPTA.boardview.render()")  # a flicker out of "now" ...
        s.tick(30000)
        s.page.evaluate("window.__fb.buf = 2")
        s.tick(3000)
        assert row(s, 0).get_attribute("data-state") == "now" and live() == "", "the same bus is not announced again after a flicker: " + live()
        load(s, with_fixture(pins=one["pins"], arr={}))  # ... then the bus is gone from the feed for over 2 minutes
        s.tick(130000)
        load(s, with_fixture(pins=one["pins"], arr={"p": [{"key": "k1", "etaMin": 5.0}]}))  # the feed re-measured the same bus key
        s.tick(2000)
        assert row(s, 0).get_attribute("data-state") == "now"
        assert live() == "Route 21: leave now", "announced again after 2 minutes out of leave-now: " + live()


def test_a_bus_is_announced_once_until_it_has_been_away_two_minutes(root):
    _announce_once(root)
    must_fail(_announce_once, root, ("js/boardview.js", "if (!(key in spoken) && prevState[id] !== undefined)", "if (prevState[id] !== undefined && prevState[id] !== 'now')"))
    must_fail(_announce_once, root, ("js/boardview.js", "SPOKEN_MS = 2 * 60000", "SPOKEN_MS = 1e12"))


def _escape_and_toast(root):
    with sess(root) as s:
        board_open(s)
        s.page.evaluate("window.SEPTA.util.toastOnce('t', 'Test notice')")
        s.page.wait_for_selector("#toasts .toast")
        s.page.focus("#toasts .toast button")
        s.page.keyboard.press("Escape")
        assert s.page.locator("#toasts .toast").count() == 0, "Escape closed the toast first"
        assert s.page.locator(BV).is_visible(), "and left the board open"
        s.page.focus(BV)
        s.page.keyboard.press("Escape")
        assert not s.page.locator(BV).is_visible(), "the next Escape closes the board"


def test_escape_closes_a_toast_before_the_board(root):
    _escape_and_toast(root)
    must_fail(_escape_and_toast, root, ("js/boardview.js", "!open || document.querySelector('#toasts .toast')", "!open"))


def _wake_token(root):
    with sess(root, extra=[WAKE_LATE]) as s:
        s.open()
        s.wait_live()
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_function("window.__wake.requests === 1")
        s.page.click("#bvClose")                         # closed while the first answer is still on its way
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_function("window.__wake.requests === 2")
        s.page.evaluate("window.__wake.answer(0)")       # the old answer arrives: it must be let go at once
        s.page.wait_for_function("window.__wake.released === 1")
        assert s.page.evaluate("window.__wake.sentinels[0].released") is True
        s.page.evaluate("window.__wake.answer(1)")       # the current one is kept
        s.page.wait_for_timeout(200)
        assert s.page.evaluate("window.__wake.sentinels[1].released") is False and s.page.evaluate("window.__wake.released") == 1
        s.page.click("#bvClose")
        assert s.page.evaluate("window.__wake.sentinels[1].released") is True, "closing releases the current lock"


WAKE_LATE = r"""(function () {
  var w = window.__wake = { requests: 0, released: 0, sentinels: [], pend: [] };
  w.answer = function (i) { w.pend[i](); };
  Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: function () {
    w.requests++;
    var s = { released: false, addEventListener: function () {}, release: function () { s.released = true; w.released++; return Promise.resolve(); } };
    w.sentinels.push(s);
    return new Promise(function (res) { w.pend.push(function () { res(s); }); });
  } } });
})();"""


def test_a_late_wake_lock_answer_is_released(root):
    _wake_token(root)
    must_fail(_wake_token, root, ("js/boardview.js", "if (mine !== reqSeq || !open) return drop(l);", "if (!open) return drop(l);"))


def _resize(root):
    with sess(root) as s:
        board_open(s)
        s.page.click("#bvSet")
        top = lambda: s.page.evaluate("parseFloat(document.querySelector('#bvSettings').style.top)")  # noqa: E731
        want = lambda: s.page.evaluate("document.querySelector('.bv-head').getBoundingClientRect().bottom + 6")  # noqa: E731
        before = top()
        s.page.set_viewport_size({"width": 320, "height": 640})
        s.page.wait_for_timeout(300)
        assert abs(top() - want()) < 1 and abs(top() - before) > 5, (before, top(), want())
        s.page.set_viewport_size({"width": 1133, "height": 744})
        s.page.wait_for_timeout(300)
        assert abs(top() - want()) < 1 and abs(top() - before) < 1.5


def test_settings_sheet_follows_a_resize(root):
    _resize(root)
    must_fail(_resize, root, ("js/boardsettings.js", "['resize', 'orientationchange']", "['x-resize', 'x-orientationchange']"))


def test_one_polite_live_region_in_the_board(root):
    with sess(root) as s:
        board_open(s)
        assert s.page.locator(f"{BV} [aria-live]").count() == 1 and s.page.locator(f"{BV} [role=status]").count() == 2  # live region + banner
        assert s.page.get_attribute("#bvLive", "aria-live") == "polite"


def test_phone_entry_button_is_below_the_peek_and_the_sheet_survives(root):
    with sess(root, viewport=PHONE, mobile=True, touch=True) as s:
        s.open()
        s.wait_live()
        assert s.page.get_attribute("#app", "data-sheet") == "peek"
        box = s.page.evaluate("(() => { const b = document.querySelector('#btnBoard').getBoundingClientRect(), p = document.querySelector('#panel').getBoundingClientRect(); return [b.top, p.bottom]; })()")
        assert box[0] >= box[1], "the Board button is in the opened More area, not the peek row"
        before = s.page.evaluate("(() => { const r = document.querySelector('#panel').getBoundingClientRect(); return [r.top, r.height]; })()")
        s.page.click("#sheetHandle")
        s.page.evaluate("document.querySelector('#btnBoard').scrollIntoView()")
        s.page.tap("#btnBoard")
        s.page.wait_for_selector(BV, state="visible")
        s.page.tap("#bvClose")
        assert s.page.evaluate("document.activeElement.id") == "btnBoard"
        assert s.page.get_attribute("#app", "data-sheet") == "open"
        s.page.click("#sheetHandle")
        assert s.page.get_attribute("#app", "data-sheet") == "peek"
        assert s.page.evaluate("(() => { const r = document.querySelector('#panel').getBoundingClientRect(); return [r.top, r.height]; })()") == before
        assert s.page.evaluate("(() => { const m = window.SEPTA.map.map, z = m.getSize(), c = m.getContainer(); return z.x === c.clientWidth && z.y === c.clientHeight; })()")
