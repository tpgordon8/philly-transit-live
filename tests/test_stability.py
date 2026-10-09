"""WP-H3 stability and load: closed sheet in the markup (no layout shift), preconnect hints, silent storage failures,
malformed feed answers, slower polling when quiet, ?v= cache-skew guard, manifest id and theme colour, saved-data backups."""
import json
import pathlib
import re
import shutil
import tempfile
import time

import stamp_version
from harness import Session

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_sheet_ships_closed",
    "test_preconnect_hints",
    "test_storage_failure_toasts_once",
    "test_rule_message_says_when_saving_failed",
    "test_malformed_feed_is_an_error_not_an_empty_feed",
    "test_version_stamp_matches_content",
    "test_network_url_carries_the_script_token",
    "test_save_failure_toast_goes_under_the_leave_now_toast",
    "test_a_throwing_toast_hook_does_not_drop_the_message",
    "test_privacy_link_opens_details_without_changing_the_hash",
    "test_leave_now_message_names_the_mode",
    "test_manifest_id_and_theme",
    "test_backup_of_corrupt_saved_data",
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIN = 60000
SAVE_MSG = "Can't save on this device, so your settings won't be kept."
RULE_MSG = "can't be saved on this device"
PLACES_MSG = "Only your first 50 saved places are kept."
STOP_HASH = "#stop=14880&route=21"
SECURITY = "Object.defineProperty(window, 'localStorage', {configurable: true, get() { throw new DOMException('denied', 'SecurityError'); }});"
QUOTA = "Storage.prototype.setItem = function () { throw new DOMException('full', 'QuotaExceededError'); };"
CLS = """(() => { window.__cls = 0;
 new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({type: 'layout-shift', buffered: true}); })();"""


def seed(key, raw):
    return f"try {{ localStorage.setItem({json.dumps(key)}, {json.dumps(raw)}); }} catch (e) {{}}"


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()


def toasts(s):
    return s.page.evaluate("[...document.querySelectorAll('#toasts .tmsg')].map(e => e.textContent)")


def ls(s, key):
    return s.page.evaluate("(k) => localStorage.getItem(k)", key)


def set_radius(s, v):
    s.page.evaluate("(v) => { const r = document.querySelector('#radius'); r.value = v; r.dispatchEvent(new Event('change', {bubbles: true})); }", v)


# ---------------------------------------------------------------- 1. the sheet ships closed
def test_sheet_ships_closed(root):
    html = (pathlib.Path(root) / "index.html").read_text()
    assert re.search(r'<div id="app" data-sheet="peek">', html)
    assert re.search(r'id="sheetHandle"[^>]*aria-expanded="false"', html)
    # sheet.js never runs: the markup alone must already give the closed layout on a phone
    with Session(root, viewport=(390, 844), mobile=True, touch=True, extra_routes={"/js/sheet.js": (200, "application/javascript", "")}) as s:
        s.open()
        s.page.wait_for_selector("#panel")
        panel = s.page.locator("#panel").bounding_box()
        assert panel["height"] < 200 and panel["y"] > 600, panel
    # wide screen: sidebar fully visible, handle hidden (so its aria-expanded is not exposed), nothing collapsed
    with Session(root, viewport=(1280, 800)) as s:
        boot(s)
        assert not s.page.locator("#sheetHandle").is_visible()
        assert s.page.locator("#h-alerts").is_visible() and s.page.locator("#h-places").is_visible()
        panel = s.page.locator("#panel").bounding_box()
        assert panel["width"] > 380 and panel["height"] >= 780, panel
        assert s.page.get_attribute("#sheetHandle", "aria-expanded") == "false"
    # phone: JS keeps the attributes in step with the sheet
    with Session(root, viewport=(390, 844), mobile=True, touch=True) as s:
        boot(s)
        assert s.page.get_attribute("#app", "data-sheet") == "peek" and s.page.get_attribute("#sheetHandle", "aria-expanded") == "false"
        s.page.click("#sheetHandle")
        assert s.page.get_attribute("#app", "data-sheet") == "open" and s.page.get_attribute("#sheetHandle", "aria-expanded") == "true"


def test_no_layout_shift_when_sheet_script_is_late(root):
    """CLS at 390x844 with js/sheet.js held back 800 ms (a slow connection); it was 0.169 when the markup shipped the panel open."""
    with Session(root, viewport=(390, 844), mobile=True, touch=True, init_scripts=[CLS]) as s:
        def slow(route):
            time.sleep(0.8)
            route.fallback()
        s.page.route("**/js/sheet.js*", slow)
        boot(s)
        s.page.wait_for_timeout(1000)
        cls = s.page.evaluate("window.__cls")
        assert cls < 0.01, cls


# ---------------------------------------------------------------- 2. preconnect hints
def test_preconnect_hints(root):
    html = (pathlib.Path(root) / "index.html").read_text()
    head = html[: html.index("</head>")]
    pre = re.findall(r'<link rel="preconnect" href="([^"]+)"( crossorigin)?>', head)
    assert pre == [("https://septa-proxy.tpgordon8.workers.dev", " crossorigin"), ("https://fonts.gstatic.com", " crossorigin"),
                   ("https://tile.openstreetmap.org", " crossorigin")], pre
    # every external host named in the head is one we know about; the Leaflet tag keeps its SRI
    hosts = set(re.findall(r'(?:href|src)="https?://([^/"]+)', head))
    assert hosts <= {"septa-proxy.tpgordon8.workers.dev", "fonts.gstatic.com", "tile.openstreetmap.org", "fonts.googleapis.com"}, hosts
    assert 'integrity="sha384-NElt3Op+9NBMCYaef5HxeJmU4Xeard/Lku8ek6hoPTvYkQPh3zLIrJP7KiRocsxO" crossorigin="anonymous"' in html
    assert "Content-Security-Policy" not in html


# ---------------------------------------------------------------- 3. storage failures
def test_storage_failure_toasts_once(root):
    for name, script in (("SecurityError", SECURITY), ("QuotaExceededError", QUOTA)):
        with Session(root, init_scripts=[script]) as s:
            boot(s)
            assert toasts(s) == [], name
            set_radius(s, "1")
            set_radius(s, "2")
            s.page.click("[data-mode=train]", force=True)
            assert toasts(s) == [SAVE_MSG], (name, toasts(s))
            assert not [e for e in s.console_errors if "pageerror" in e], s.console_errors
    with Session(root) as s:  # storage that works: no toast
        boot(s)
        set_radius(s, "1")
        assert toasts(s) == []


GRANTED_HIDDEN = """(function () {
  window.__notes = [];
  function N(t, o) { window.__notes.push({ t: t, o: o || null }); }
  N.permission = 'granted';
  N.requestPermission = function () { return Promise.resolve('granted'); };
  window.Notification = N;
  Object.defineProperty(document, 'hidden', { configurable: true, get: function () { return window.__hidden === true; } });
})();"""


def test_save_failure_toast_goes_under_the_leave_now_toast(root):
    """A phone shows only the last toast: a first-time "Can't save" notice must not cover a leave-now toast, and a notice never
    raises a system notification (the leave-now message already did, with the tab hidden)."""
    with Session(root, init_scripts=["window.__SEPTA_TEST__ = true", QUOTA, GRANTED_HIDDEN], viewport=(390, 844), mobile=True) as s:
        boot(s)
        s.page.evaluate("window.__hidden = true")
        s.page.evaluate("window.__SEPTA_TEST__.notify('Leave now: test message.')")
        set_radius(s, "1")  # a save that fails: the first-time "Can't save" toast, raised after the leave-now one
        assert toasts(s) == [SAVE_MSG, "Leave now: test message."], toasts(s)
        assert s.page.evaluate("window.__notes.map(n => n.o.body)") == ["Leave now: test message."]
        shown = s.page.evaluate("[...document.querySelectorAll('#toasts .toast')].filter(t => getComputedStyle(t).display !== 'none').map(t => t.textContent)")
        assert len(shown) == 1 and shown[0].startswith("Leave now: test message."), shown
    with Session(root, init_scripts=["window.__SEPTA_TEST__ = true", QUOTA]) as s:  # desktop: the oldest of the others is dropped, never the notice
        boot(s)
        for i in range(4):
            s.page.evaluate(f"window.__SEPTA_TEST__.notify('Leave now: {i}.')")
        set_radius(s, "1")
        got = toasts(s)
        assert len(got) == 3 and got[0] == SAVE_MSG and got[-1] == "Leave now: 3.", got


def test_a_throwing_toast_hook_does_not_drop_the_message(root):
    with Session(root) as s:
        boot(s)
        r = s.page.evaluate("""() => { const U = window.SEPTA.util, real = U.toastHook; let calls = 0;
            U.toastHook = () => { calls++; throw new Error('boom'); };
            U.toastOnce('kept', 'Kept message.');
            const afterThrow = document.querySelectorAll('#toasts .tmsg').length;
            U.toastHook = real; U.flushToasts();
            return {calls, afterThrow, texts: [...document.querySelectorAll('#toasts .tmsg')].map(e => e.textContent)}; }""")
        assert r["calls"] == 1 and r["afterThrow"] == 0 and r["texts"] == ["Kept message."], r


def test_privacy_link_opens_details_without_changing_the_hash(root):
    with Session(root) as s:
        boot(s, STOP_HASH)
        s.page.wait_for_selector("#copyStop")
        before = s.page.evaluate("location.href")
        assert s.page.evaluate("document.querySelector('#privacyDetails').open") is False
        s.page.click("#sugAttrFind .priv-link")
        assert s.page.evaluate("document.querySelector('#privacyDetails').open") is True
        assert s.page.evaluate("location.href") == before and s.page.evaluate("location.hash") == STOP_HASH
        assert s.page.evaluate("document.activeElement.tagName") == "SUMMARY"
        assert not s.page.is_hidden("#stopCard"), "the open stop card stays open"


def test_leave_now_message_names_the_mode(root):
    with Session(root, init_scripts=["window.__SEPTA_TEST__ = true"]) as s:
        boot(s)
        got = s.page.evaluate("""() => { const f = window.__SEPTA_TEST__.leaveMsg;
            return ['21', 'G1', 'B1'].map(r => f({route: r, stopName: 'Main St'}, 4)); }""")
        assert got == ["Leave now: the Route 21 bus is about 4 min from Main St.",
                       "Leave now: the Route G1 trolley is about 4 min from Main St.",
                       "Leave now: the Route B1 vehicle is about 4 min from Main St."], got


def test_toast_raised_before_alerts_js_loads_is_delivered(root):
    over = json.dumps({"home": None, "list": [{"id": f"p{i}", "name": f"Place {i}", "lat": 39.9 + i / 1000, "lng": -75.1} for i in range(52)]})
    with Session(root, init_scripts=[seed("septa.places.v1", over)]) as s:
        boot(s)
        assert toasts(s) == [PLACES_MSG], toasts(s)
        assert s.page.locator("#places li").count() == 50


def test_rule_message_says_when_saving_failed(root):
    for script, expect_bad in ((None, False), (QUOTA, True)):
        with Session(root, init_scripts=[script] if script else []) as s:
            boot(s, STOP_HASH)
            s.page.wait_for_selector("#addAlert")
            s.page.click("#addAlert")
            live = s.page.inner_text("#alertLive")
            assert live.startswith("Alert set for route 21, under 8 min."), live
            assert (RULE_MSG in live) == expect_bad, live
            assert s.page.locator("#rules li").count() == 1
            assert "You will see an alert here." in live and "banner" not in live, live
            assert toasts(s) == [], toasts(s)  # the live line already says it; the toast would speak a second time


# ---------------------------------------------------------------- 4. malformed feed answers
def test_malformed_feed_is_an_error_not_an_empty_feed(root):
    with Session(root) as s:
        boot(s)
        r = s.page.evaluate("""() => { const f = window.SEPTA.feed, out = {};
          const t = (n, fn) => { try { out[n] = fn().length; } catch (e) { out[n] = 'throws'; } };
          t('bus {}', () => f.normBuses({})); t('bus null', () => f.normBuses(null)); t('bus str', () => f.normBuses({bus: 'x'}));
          t('bus string', () => f.normBuses('<html>')); t('bus []', () => f.normBuses({bus: []}));
          t('train {}', () => f.normTrains({})); t('train null', () => f.normTrains(null)); t('train str', () => f.normTrains({train: 'x'}));
          t('train []', () => f.normTrains([])); return out; }""")
        assert r == {"bus {}": "throws", "bus null": "throws", "bus str": "throws", "bus string": "throws", "bus []": 0,
                     "train {}": "throws", "train null": "throws", "train str": "throws", "train []": 0}, r


def stale_state(s):
    return s.page.evaluate("(() => { const b = window.SEPTA.util.state.src.bus; return [b.stale, b.err, b.list.length]; })()")


def test_malformed_200_takes_the_stale_path(root):
    for label, body in (("{}", {}), ("null", None), ('{"bus":"x"}', {"bus": "x"})):
        with Session(root) as s:
            boot(s)
            n = s.markers()
            assert n > 0
            s.worker.data["TransitView"] = body
            s.tick(20000, cap_ms=3000)
            stale, err, count = stale_state(s)
            assert stale and err and count > 0, (label, stale_state(s))
            assert s.markers() == n, (label, "the map must keep the last good positions", s.markers(), n)
            assert not s.page.locator("#empty").is_visible(), label
            assert "older positions" in s.page.inner_text("#banner").lower(), (label, s.page.inner_text("#banner"))
    with Session(root) as s:  # an HTML page answered with status 200
        boot(s)
        s.page.route("**/septa-proxy.tpgordon8.workers.dev/TransitView*", lambda r: r.fulfill(status=200, content_type="text/html", body="<html><body>Maintenance</body></html>"))
        s.tick(20000, cap_ms=3000)
        s.tick(2000, cap_ms=3000)  # the retry after 1.5 s; this route is not counted in worker.hits, so give it time
        assert stale_state(s)[:2] == [True, True] and s.markers() > 0, stale_state(s)
    with Session(root) as s:  # a valid empty list is a healthy empty feed
        boot(s)
        s.worker.data["TransitView"] = {"bus": []}
        s.worker.data["TrainView"] = []  # the harness turns every mode on
        s.tick(20000, cap_ms=3000)
        stale, err, count = stale_state(s)
        assert not stale and not err and count == 0, stale_state(s)
        s.page.wait_for_selector("#empty:not([hidden])", timeout=3000)
        s.settle()
        assert s.markers() == 0 and "quiet around here" in s.page.inner_text("#empty").lower()


def test_malformed_train_feed_takes_the_stale_path(root):
    seed_rail = seed("septa.prefs.v1", json.dumps({"radius": 5, "filters": {"bus": False, "trolley": False, "subway": False, "train": True}}))
    with Session(root, init_scripts=[seed_rail]) as s:
        boot(s)
        s.worker.data["TrainView"] = {}
        s.tick(20000, cap_ms=3000)
        t = s.page.evaluate("(() => { const b = window.SEPTA.util.state.src.train; return [b.stale, b.err]; })()")
        assert t == [True, True], t


# ---------------------------------------------------------------- 5. slower polling when quiet
def tv_hits(s, minutes):
    s.worker.hits.clear()
    for _ in range(minutes):
        s.tick(MIN)
    return sum(1 for h in s.worker.hits if h == "TransitView")


def test_polling_slows_after_ten_quiet_minutes_and_recovers_on_input(root):
    with Session(root) as s:
        boot(s)
        before = tv_hits(s, 2)
        assert before >= 7, before  # every 15 s
        for _ in range(10):
            s.tick(MIN)
        quiet = tv_hits(s, 4)  # well past 10 quiet minutes
        assert 5 <= quiet <= 11, (before, quiet)  # about every 30 s: 8 in 4 minutes (16 at 15 s); slack for a loaded machine
        s.page.mouse.move(700, 700)
        s.page.mouse.down()
        s.page.mouse.up()
        back = tv_hits(s, 3)  # 15 s cadence: about 12; the slow cadence would give 6
        assert back >= 9, (quiet, back)
        for _ in range(11):
            s.tick(MIN)
        again = tv_hits(s, 3)
        assert again <= 8, ("quiet again", again)
        s.page.keyboard.press("Shift")
        key = tv_hits(s, 3)
        assert key >= 9, ("after a key", key)
        assert "Paused" not in s.page.inner_text("#statusText")


RULE = {"id": "r1", "route": "21", "stopId": "14880", "stopName": "Test stop", "lat": 39.95, "lng": -75.16, "minutes": 8, "enabled": True, "last": None}


def test_quiet_slowdown_skips_tabs_with_a_rule_or_an_open_stop(root):
    """A visible tab with an enabled leave-now rule, or an open stop card, keeps the 15 s cadence after 10 quiet minutes."""
    cases = (("rule", [seed("septa.rules.v1", json.dumps({"rules": [RULE]}))], ""),
             ("stop", [], STOP_HASH))
    for name, scripts, hash_ in cases:
        with Session(root, init_scripts=scripts) as s:
            boot(s, hash_)
            for _ in range(12):
                s.tick(MIN)
            n = tv_hits(s, 4)
            assert n >= 12, (name, n)  # 15 s cadence: 16 in 4 minutes; the slow cadence gives 8
    with Session(root, init_scripts=[seed("septa.rules.v1", json.dumps({"rules": [dict(RULE, enabled=False)]}))]) as s:
        boot(s)  # a disabled rule does not count
        for _ in range(12):
            s.tick(MIN)
        n = tv_hits(s, 4)
        assert n <= 11, n


# ---------------------------------------------------------------- 6. cache-skew guard
def test_version_stamp_matches_content(root):
    root = pathlib.Path(root)
    html = (root / "index.html").read_text()
    token = stamp_version.content_hash(root)
    tags = stamp_version.stamped(html)
    assert len(tags) == 15 + 10, tags  # every app script and stylesheet
    assert all(t == token for _, t in tags), f"index.html is not stamped with ?v={token}: run python3 tests/stamp_version.py"
    assert "leaflet.min.js?" not in html and "fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap" in html
    import test_modules
    assert [re.sub(r"\.js$", "", u.split("/")[-1]) for u, _ in tags if u.startswith("js/")] == test_modules.FILES
    # the script itself: idempotent, and it notices a changed file
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for d in ("js", "css", "data"):
            shutil.copytree(root / d, tmp / d)
        (tmp / "index.html").write_text(re.sub(r"\?v=[0-9a-f]+", "", html))
        assert stamp_version.main(["--root", str(tmp), "--check"]) == 1
        assert stamp_version.main(["--root", str(tmp)]) == 0
        once = (tmp / "index.html").read_text()
        assert once == html and stamp_version.main(["--root", str(tmp)]) == 0 and (tmp / "index.html").read_text() == once
        assert stamp_version.main(["--root", str(tmp), "--check"]) == 0
        with open(tmp / "js" / "util.js", "a") as f:
            f.write("\n// changed\n")
        assert stamp_version.main(["--root", str(tmp), "--check"]) == 1
        assert stamp_version.main(["--root", str(tmp)]) == 0 and (tmp / "index.html").read_text() != once
        assert stamp_version.main(["--root", str(tmp), "--check"]) == 0
        # the network file is covered too: changing it alone changes the token
        with open(tmp / "data" / "bus-network.json", "a") as f:
            f.write("\n")
        assert stamp_version.main(["--root", str(tmp), "--check"]) == 1
        assert stamp_version.main(["--root", str(tmp)]) == 0 and stamp_version.main(["--root", str(tmp), "--check"]) == 0


def test_network_url_carries_the_script_token(root):
    """routing.js reads ?v= from its own script tag and puts the same token on the network file's URL; no token, no query."""
    token = stamp_version.content_hash(root)
    with Session(root) as s:
        seen = []
        s.page.on("request", lambda r: seen.append(r.url) if "bus-network.json" in r.url else None)
        boot(s)
        s.page.evaluate("window.SEPTA.routing.loadNetwork()")
        s.page.wait_for_timeout(300)
        assert seen and all(u.endswith("/data/bus-network.json?v=" + token) for u in seen), seen
    root = pathlib.Path(root)
    tmp = pathlib.Path(tempfile.mkdtemp())  # an unstamped copy of the page: the fallback is no query
    for d in ("js", "css", "data", "icons"):
        if (root / d).exists():
            shutil.copytree(root / d, tmp / d)
    (tmp / "index.html").write_text(re.sub(r"(js/[a-z]+\.js)\?v=[0-9a-f]+", r"\1", (root / "index.html").read_text()))
    with Session(tmp) as s:
        seen = []
        s.page.on("request", lambda r: seen.append(r.url) if "bus-network.json" in r.url else None)
        boot(s)
        s.page.evaluate("window.SEPTA.routing.loadNetwork()")
        s.page.wait_for_timeout(300)
        assert seen and all(u.endswith("/data/bus-network.json") for u in seen), seen
    shutil.rmtree(tmp, ignore_errors=True)


def test_stamped_urls_load(root):
    with Session(root) as s:
        boot(s)
        assert s.page.evaluate("window.SEPTA.started === true && window.SEPTA.failed.length === 0")
        urls = s.page.evaluate("[...document.scripts].map(x => x.src).filter(u => /\\/js\\//.test(u))")
        assert urls and all("?v=" in u for u in urls), urls
        assert not s.console_errors, s.console_errors


# ---------------------------------------------------------------- 7. manifest
def test_manifest_id_and_theme(root):
    root = pathlib.Path(root)
    m = json.loads((root / "manifest.webmanifest").read_text())
    html = (root / "index.html").read_text()
    light = re.search(r'<meta name="theme-color" content="(#[0-9a-fA-F]{6})" media="\(prefers-color-scheme: light\)">', html).group(1)
    accent = re.search(r"--accent:(#[0-9a-fA-F]{6})", (root / "css" / "base.css").read_text()).group(1)
    assert m["id"] == "./" and m["start_url"] == "./" and m["scope"] == "./", m
    assert m["theme_color"].lower() == light.lower() == accent.lower(), (m["theme_color"], light, accent)


# ---------------------------------------------------------------- 8. data safety
def test_backup_of_corrupt_saved_data(root):
    bad = {"septa.prefs.v1": "{not json", "septa.places.v1": "[1,2]", "septa.routes.v1": '"x"', "septa.rules.v1": '{"rules":"x"}'}
    with Session(root, init_scripts=[seed(k, v) for k, v in bad.items()]) as s:
        boot(s)
        for k, v in bad.items():
            assert ls(s, k + ".bak") == v, (k, ls(s, k + ".bak"))
            assert ls(s, k) == v, "load must not rewrite the original"
        set_radius(s, "1")  # the next save replaces the corrupt prefs, the backup keeps the old text
        assert json.loads(ls(s, "septa.prefs.v1"))["radius"] == 1 and ls(s, "septa.prefs.v1.bak") == "{not json"
    # wrongly shaped parts: a bad place inside a good list, a bad center, a bad star, a dropped rule
    part = {"septa.prefs.v1": '{"center":{"lat":"x","lng":1},"radius":0.5}',
            "septa.places.v1": '{"home":null,"list":[{"id":"a","name":"A","lat":39.9,"lng":-75.1},{"name":5}]}',
            "septa.routes.v1": '{"stars":["21",7],"onlyMine":true}',
            "septa.rules.v1": '{"rules":[{"id":"r1","route":"%%%"}]}'}
    with Session(root, init_scripts=[seed(k, v) for k, v in part.items()]) as s:
        boot(s)
        for k, v in part.items():
            assert ls(s, k + ".bak") == v, k
    # healthy data and a fresh browser leave no backups, and a full disk for the backup does not break the page
    good = {"septa.prefs.v1": '{"center":{"lat":39.95,"lng":-75.16,"label":"x"},"radius":1,"filters":{"bus":true}}',
            "septa.places.v1": '{"home":null,"list":[{"id":"a","name":"A","lat":39.9,"lng":-75.1}]}',
            "septa.routes.v1": '{"stars":["21"],"onlyMine":true}'}
    with Session(root, init_scripts=[seed(k, v) for k, v in good.items()]) as s:
        boot(s)
        assert [k for k in s.page.evaluate("Object.keys(localStorage)") if k.endswith(".bak")] == []
    with Session(root) as s:
        boot(s)
        assert [k for k in s.page.evaluate("Object.keys(localStorage)") if k.endswith(".bak")] == []
    nobak = "const _s = Storage.prototype.setItem; Storage.prototype.setItem = function (k, v) { if (/\\.bak$/.test(k)) throw new DOMException('full', 'QuotaExceededError'); return _s.call(this, k, v); };"
    with Session(root, init_scripts=[seed("septa.prefs.v1", "{x"), nobak]) as s:
        boot(s)
        assert s.markers() > 0 and ls(s, "septa.prefs.v1.bak") is None and toasts(s) == []


def test_fifty_places_toast_is_shown_once_and_only_when_cut(root):
    mk = lambda n: json.dumps({"home": None, "list": [{"id": f"p{i}", "name": f"P{i}", "lat": 39.9, "lng": -75.1} for i in range(n)]})
    with Session(root, init_scripts=[seed("septa.places.v1", mk(50))]) as s:
        boot(s)
        assert toasts(s) == [] and ls(s, "septa.places.v1.bak") is None
    with Session(root, init_scripts=[seed("septa.places.v1", mk(55))]) as s:
        boot(s)
        assert toasts(s) == [PLACES_MSG] and json.loads(ls(s, "septa.places.v1.bak"))["list"].__len__() == 55
        s.page.reload()
        s.wait_live()
        assert toasts(s) == [PLACES_MSG]  # a new session (page load) shows it again until a save replaces the long list


def test_docs_list_the_new_keys(root):
    text = (pathlib.Path(root) / "ARCHITECTURE.md").read_text()
    sec6 = text[text.index("## 6. localStorage schema"): text.index("## 7. Deployment")]
    for k in ("septa.prefs.v1.bak", "septa.places.v1.bak", "septa.routes.v1.bak", "septa.rules.v1.bak"):
        assert k in sec6, k
    sec5 = text[text.index("## 5. Refresh loop"): text.index("## 6. localStorage")]
    assert "30 s" in sec5 and "10 minutes" in sec5
    sec7 = text[text.index("## 7. Deployment"): text.index("## 8. Test and review")]
    assert "stamp_version.py" in sec7 and "stamp_version.py" in (pathlib.Path(root) / "README.md").read_text()
