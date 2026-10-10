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
  var fb = window.__fb = { pins: [], arr: {}, buf: 2, bad: false, source: 'live', t0: Date.now(), calls: [], cbs: [], places: {} };
  function fire() { fb.cbs.forEach(function (f) { f(); }); }
  function walk(p) { return p.walkMin != null ? p.walkMin : (p.auto || 4); }
  fb.load = function (d) {
    fb.pins = d.pins; fb.arr = d.arr || {}; fb.buf = d.buf == null ? 2 : d.buf; fb.bad = !!d.bad; fb.source = d.source || 'live';
    fb.t0 = Date.now(); fire();
  };
  fb.api = {
    pins: function () { return fb.pins.map(function (p) { return JSON.parse(JSON.stringify(p)); }); },
    settings: function () { return { bufferMin: fb.buf, bad: fb.bad }; },
    setSettings: function (patch) { fb.calls.push(['setSettings', patch]); if ('bufferMin' in patch) fb.buf = patch.bufferMin; if ('bad' in patch) fb.bad = patch.bad; fire(); return true; },
    updatePin: function (id, patch) { fb.calls.push(['updatePin', id, patch]); fb.pins.forEach(function (p) { if (p.id === id) for (var k in patch) p[k] = patch[k]; }); fire(); return true; },
    removePin: function (id) { fb.calls.push(['removePin', id]); fb.pins = fb.pins.filter(function (p) { return p.id !== id; }); fire(); return true; },
    walkMin: walk,
    placeFor: function (p) { return p.placeName ? { name: p.placeName, lat: 0, lng: 0 } : null; },
    addPin: function () { return { ok: false, reason: 'invalid' }; },
    onChange: function (f) { fb.cbs.push(f); },
    rows: function (now) {
      var el = (now - fb.t0) / 60000, extra = fb.buf + (fb.bad ? 4 : 0);
      return fb.pins.map(function (p) {
        var w = walk(p), down = fb.source === 'down';
        var a = down ? [] : (fb.arr[p.id] || []).map(function (x) { return { key: x.key, etaMin: x.etaMin - el, rough: !!x.rough }; }).filter(function (x) { return x.etaMin > -1; });
        var leave = null;
        for (var i = 0; i < a.length && !leave; i++) {
          if (a[i].etaMin < w) continue;
          var li = a[i].etaMin - w - extra;
          leave = { inMin: Math.max(0, Math.ceil(li)), state: li <= 0 ? 'now' : li <= 3 ? 'soon' : 'later', forKey: a[i].key };
        }
        if (!leave && a.length) leave = { inMin: 0, state: 'missed', forKey: a[0].key };
        return { pin: p, placeName: p.placeName || '', walkMin: w, source: fb.source, arrivals: a, leave: leave };
      });
    }
  };
  var ns;
  Object.defineProperty(window, 'SEPTA', { configurable: true, get: function () { return ns; }, set: function (v) { ns = v; v.board = fb.api; } });
})();"""
HOOK_NOBOARD = ""

# walk 4 + buffer 2 = 6 minutes of lead time; ETA minus 6 is the leave-in value.
FIXTURE = {
    "pins": [
        {"id": "p1", "route": "57", "stopName": "Moyamensing Av & Snyder Av", "placeName": "Home", "walkMin": None, "auto": 4},
        {"id": "p2", "route": "47", "stopName": "9th St & Washington Av", "placeName": "Home", "walkMin": 5},
        {"id": "p3", "route": "21", "stopName": "Chestnut St & 17th St", "placeName": "Work", "walkMin": 3},
        {"id": "p4", "route": "23", "stopName": "Germantown Av & Chestnut Hill", "placeName": "Home", "walkMin": 8},
        {"id": "p5", "route": "42", "stopName": "Walnut St & 10th St", "placeName": "Home", "walkMin": 6},
    ],
    "arr": {
        "p1": [{"key": "a1", "etaMin": 13.4}, {"key": "a2", "etaMin": 21.2}],     # later: leave in 8
        "p2": [{"key": "b1", "etaMin": 9.1, "rough": True}],                       # soon, rough ETA: leave in 3
        "p3": [{"key": "c1", "etaMin": 4.6}, {"key": "c2", "etaMin": 17.0}],       # now (3 + 2 = 5 needed, 4.6 left, still makeable)
        "p4": [{"key": "d1", "etaMin": 5.0}],                                      # missed (walk is 8)
    },                                                                              # p5: nothing heading there
    "buf": 2,
}
PORTRAIT, LANDSCAPE, PHONE, SMALL = (744, 1133), (1133, 744), (390, 844), (320, 640)


def sess(root, viewport=(1133, 744), extra=(), board=True, **kw):
    scripts = ([FAKE] if board else []) + list(extra)
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
        assert r[0].locator(".bv-leave .bv-v").inner_text() == "8 min"
        assert r[0].locator(".bv-bus .bv-k").inner_text() == "Bus in" and r[0].locator(".bv-leave .bv-k").inner_text() == "Leave in"
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
        assert r[0].get_attribute("aria-label") == "Route 57 at Moyamensing Av & Snyder Av, bus in 13 minutes, leave in 8 minutes"
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
        assert row(s, 0).locator(".bv-leave .bv-v").inner_text() == "7 min"
        s.tick(5 * 60000, cap_ms=300)
        assert row(s, 0).locator(".bv-bus .bv-v").inner_text() == "7 min" and row(s, 0).locator(".bv-leave .bv-v").inner_text() == "2 min"
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
        assert row(s, 0).locator(".bv-leave .bv-v").inner_text() == "9 min"
        s.page.click('[aria-label="Less minutes to get ready"]')
        assert s.page.locator('[aria-label="Less minutes to get ready"]').is_disabled(), "buffer stops at 0"
        s.page.evaluate("window.__fb.buf = 15; window.__fb.cbs[0]()")
        s.page.click("#bvSet"); s.page.click("#bvSet")
        assert s.page.locator('[aria-label="More minutes to get ready"]').is_disabled(), "buffer stops at 15"
        s.page.check('[data-fk="bad"]')
        assert last() == ["setSettings", {"bad": True}], calls()
        # per-pin walk time: stepper, "Automatic", Remove
        s.page.click('[aria-label="More walk minutes for Route 47 at 9th St & Washington Av"]')
        assert last() == ["updatePin", "p2", {"walkMin": 6}], calls()
        s.page.uncheck('[data-fk="a0"]')
        assert last() == ["updatePin", "p1", {"walkMin": 4}], calls()
        s.page.check('[data-fk="a0"]')
        assert last() == ["updatePin", "p1", {"walkMin": None}], calls()
        assert "Automatic, 4 min" in txt(s, "#bvSettings")
        s.page.click('[aria-label="Remove Route 47 at 9th St & Washington Av"]')
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
    must_fail(_settings, root, ("js/boardview.js", "b.setSettings({ bufferMin: Math.min(BUF_MAX, cfg.bufferMin + 1) });", ""))


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
        # the hash opened directly: no opener, focus goes to the address box
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector(BV, state="visible")
        s.page.click("#bvClose")
        assert s.page.evaluate("document.activeElement.id") == "addr"
        assert not s.console_errors, s.console_errors
    with sess(root) as s:
        s.open(path="index.html?board=1")
        s.page.wait_for_selector(BV, state="visible")
        s.page.click("#bvClose")
        assert not s.page.locator(BV).is_visible() and "board" not in s.page.evaluate("location.search")
        assert s.page.evaluate("document.activeElement.id") == "addr"
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
    must_fail(_switching, root, ("js/boardview.js", "var back = opener &&", "var back = null && opener &&"))


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
    with sess(root) as s:  # control: the same idle hour without the board does pause
        s.open()
        s.wait_live()
        jump(s, 61)
        assert s.page.locator("#idleBar").is_visible()
        # slow cadence after 10 quiet minutes applies without the board only
    with sess(root) as s:
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
            assert opacity(s) == (0.55 if dim else 1.0), (h, m)
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


# ---------------------------------------------------------------- nightly refresh
def _nightly(root):
    with sess(root) as s:
        set_clock(s, 15, 0)  # the page loads at 15:00 local; 12 h later is 03:00, so the first 4 AM after that is 04:00 next day
        s.open()
        s.wait_live()
        s.page.evaluate("window.__reloads = 0; window.SEPTA.boardview.reload = function () { window.__reloads++; }; 0")
        s.page.clock.pause_at((s.page.evaluate("Date.now()") + 1000) / 1000)
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector(BV, state="visible")
        reloads = lambda: s.page.evaluate("window.__reloads")  # noqa: E731
        s.page.clock.fast_forward(11 * 3600 * 1000)       # 02:00: not yet 12 h
        s.tick(2000)
        assert reloads() == 0
        s.page.clock.fast_forward(105 * 60 * 1000)        # 03:45: past 12 h, before 4 AM
        s.tick(2000)
        assert reloads() == 0, "waits for 4 AM"
        s.page.clock.fast_forward(14 * 60 * 1000)         # 03:59
        s.tick(2000)
        assert reloads() == 0
        s.page.mouse.click(300, 300)                      # a tap just before 4 AM
        s.page.clock.fast_forward(6 * 60 * 1000)          # 04:05: past 4 AM but only 6 quiet minutes
        s.tick(2000)
        assert reloads() == 0, "not while someone is using it"
        s.page.clock.fast_forward(5 * 60 * 1000)          # 04:10: 11 quiet minutes
        s.tick(2000)
        assert reloads() >= 1, "reloads at 4 AM when quiet"


def test_nightly_reload_waits_for_four_am_and_quiet(root):
    _nightly(root)
    must_fail(_nightly, root, ("js/boardview.js", "if (now >= reloadAt() && now - lastInput >= RELOAD_QUIET_MS) api.reload();", "if (now - lastInput >= RELOAD_QUIET_MS) api.reload();"))
    must_fail(_nightly, root, ("js/boardview.js", "if (now >= reloadAt() && now - lastInput >= RELOAD_QUIET_MS) api.reload();", "if (now >= reloadAt()) api.reload();"))


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
    must_fail(_big, root, ("css/board.css", "--num:clamp(40px,7.2vh,72px)", "--num:clamp(20px,3vh,72px)"))


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
        assert live() == "Leave now for route 47 at 9th St & Washington Av.", live()
        s.page.evaluate("document.querySelector('#bvLive').textContent = ''")
        s.tick(30000)
        assert live() == "", "announced once per change"


def test_live_region_announces_only_new_leave_now(root):
    _announce(root)
    must_fail(_announce, root, ("js/boardview.js", "prevState[id] !== 'now' && st === 'now'", "st === 'now'"))


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
