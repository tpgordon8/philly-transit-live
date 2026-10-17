"""Package B: Septer as an installed app (ARCHITECTURE.md section 17): the service worker (sw.js) and its cache rules, the update flow,
offline start, live data never cached, the Install card on Chromium phones and the Add to Home Screen hint on iOS Safari, the
dismissal memory, the manifest, and the launch splash.

Service workers are blocked in every other test (harness Session default), so page.route stays authoritative there; the tests below
turn them on and mock the few third-party hosts the worker itself may fetch with context-level routes."""
import contextlib
import json
import pathlib
import re
import shutil
import struct
import sys
import tempfile
import time

from harness import LEAFLET, PNG, WORKER_HOST, Session
from playwright.sync_api import TimeoutError as PlaywrightTimeout

import stamp_version

FAST = {
    "test_manifest_is_valid_and_complete",
    "test_splash_covers_first_paint_and_is_released_after_boot",
    "test_ios_safari_hint_once",
    "test_install_card_logic_on_chromium_phone",
}

PHONE = (390, 844)
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
IPHONE_CHROME = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0 Mobile/15E148 Safari/604.1"
KEY = "septa.install.v1"
DAY_MS = 24 * 3600 * 1000
SITE = ("index.html", "sw.js", "js", "css", "data", "icons", "board", "manifest.webmanifest")
PROMPT_EVENT = """(() => { window.__prompts = 0;
  const e = new Event('beforeinstallprompt', {cancelable: true});
  e.prompt = () => { window.__prompts++; return Promise.resolve(); };
  e.userChoice = Promise.resolve({outcome: 'accepted'});
  window.dispatchEvent(e); return e.defaultPrevented; })()"""


def seed(value, key=KEY):
    return f"try {{ if (localStorage.getItem({json.dumps(key)}) === null) localStorage.setItem({json.dumps(key)}, {json.dumps(json.dumps(value))}); }} catch (e) {{}}"


def phone(root, **kw):
    kw.setdefault("viewport", PHONE)
    return Session(root, mobile=True, touch=True, **kw)


@contextlib.contextmanager
def site_copy(root, edits=()):
    """A throw-away copy of the site (with sw.js) so a test can change a file or break one line."""
    root = pathlib.Path(root)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for name in SITE:
            src = root / name
            shutil.copytree(src, tmp / name) if src.is_dir() else shutil.copy(src, tmp / name)
        for rel, old, new in edits:
            f = tmp / rel
            text = f.read_text()
            assert old in text, f"mutation target not found in {rel}: {old}"
            f.write_text(text.replace(old, new, 1))
        yield tmp


def must_fail(check, root, *edits):
    with site_copy(root, edits) as broken:
        try:
            check(broken)
        except (AssertionError, PlaywrightTimeout):
            return
    raise AssertionError(f"the check still passed with the code broken: {edits}")


def mock_third_parties(s):
    """The worker fetches Leaflet, tiles and fonts itself; page.route does not see those, the context does."""
    def leaflet(route):
        route.fulfill(status=200, content_type="application/javascript", headers={"access-control-allow-origin": "*"}, body=LEAFLET.read_bytes())

    s.ctx.route("**/cdnjs.cloudflare.com/ajax/libs/leaflet/**", leaflet)
    s.ctx.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    s.ctx.route("**/fonts.googleapis.com/**", lambda r: r.fulfill(status=200, content_type="text/css", body=""))
    s.ctx.route("**/fonts.gstatic.com/**", lambda r: r.abort("failed"))


def wait_controlled(s, timeout=15000):
    s.page.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller !== null", timeout=timeout, polling=100)


def cache_names(s):
    return s.page.evaluate("caches.keys()")


def cached_urls(s):
    return s.page.evaluate("""async () => { const out = {}; for (const k of await caches.keys()) { const c = await caches.open(k); out[k] = (await c.keys()).map(r => r.url); } return out; }""")


def sw_version(root):
    return re.search(r"var VERSION = '([0-9a-f]+)'", (pathlib.Path(root) / "sw.js").read_text()).group(1)


def png_size(path):
    b = pathlib.Path(path).read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", b[16:24])


def boot_sw(root, **kw):
    s = Session(root, service_workers=True, **kw)
    s.__enter__()
    mock_third_parties(s)
    return s


# ---------------------------------------------------------------- manifest
def test_manifest_is_valid_and_complete(root):
    root = pathlib.Path(root)
    m = json.loads((root / "manifest.webmanifest").read_text())
    html = (root / "index.html").read_text()
    for k in ("name", "short_name", "description", "start_url", "scope", "id", "display", "background_color", "theme_color", "icons"):
        assert m.get(k), k
    assert m["display"] == "standalone" and m["display_override"][0] == "standalone", m
    assert "minimal-ui" in m["display_override"]
    assert m["categories"] and set(m["categories"]) <= {"travel", "navigation", "utilities", "transportation"}, m["categories"]
    assert m["prefer_related_applications"] is False
    sizes = {i["sizes"]: i for i in m["icons"] if i["type"] == "image/png"}
    assert {"192x192", "512x512"} <= set(sizes), sizes
    assert any(i.get("purpose") == "maskable" for i in m["icons"])
    for i in m["icons"]:
        f = root / i["src"]
        assert f.exists(), i
        if i["type"] == "image/png":
            w, h = (int(x) for x in i["sizes"].split("x"))
            assert png_size(f) == (w, h), (i, png_size(f))
    sc = m["shortcuts"]
    assert len(sc) >= 1 and sc[0]["short_name"] == "Board" and sc[0]["url"] == "./#board", sc
    for x in sc:
        assert x["url"].startswith("./") and x["name"]
        for i in x.get("icons", []):
            assert (root / i["src"]).exists(), i
    assert re.search(r'<link rel="manifest" href="manifest.webmanifest">', html)
    assert '<meta name="apple-mobile-web-app-status-bar-style" content="default">' in html
    assert "viewport-fit=cover" in html and 'name="apple-mobile-web-app-capable"' in html
    css = (root / "css" / "install.css").read_text()
    for needle in ("overscroll-behavior:none", "-webkit-tap-highlight-color:transparent", "-webkit-touch-callout:none", "touch-action:manipulation", "user-select:none"):
        assert needle in css, needle
    assert "input,textarea,select" in css and "user-select:text" in css  # fields and copyable text stay selectable


# ---------------------------------------------------------------- splash
def splash_probe(s):
    return s.page.evaluate("""() => { const h = document.documentElement, b = getComputedStyle(h, '::before');
        return {ready: h.classList.contains('app-ready'), content: b.content, pos: b.position, bg: b.backgroundColor, z: b.zIndex}; }""")


def test_splash_covers_first_paint_and_is_released_after_boot(root):
    def check(r):
        with Session(r) as s:
            s.open()
            s.wait_live()
            p = splash_probe(s)
            assert p["ready"] and p["content"] == "none", p  # gone once the app has started
            assert not s.console_errors, s.console_errors
    check(root)
    must_fail(check, root, ("js/install.js", "  releaseSplash();\n", "  /* never released */\n"))
    # while the app has not started (install.js held back) the splash is a fixed full-screen overlay in both colour schemes
    for scheme, bg in (("light", "rgb(238, 241, 244)"), ("dark", "rgb(10, 17, 25)")):
        with Session(root, color_scheme=scheme, extra_routes={"/js/install.js": (200, "application/javascript", "")}) as s:
            s.open()
            p = splash_probe(s)
            assert not p["ready"] and p["content"] == '"Septer"' and p["pos"] == "fixed" and p["bg"] == bg, (scheme, p)
            s.page.clock.run_for(8100)  # the backstop timer in <head>: a broken boot never leaves the splash up for ever
            assert splash_probe(s)["ready"]
    # no layout shift from taking it away
    cls = "(() => { window.__cls = 0; new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({type: 'layout-shift', buffered: true}); })();"
    with Session(root, init_scripts=[cls], viewport=PHONE, mobile=True, touch=True) as s:
        s.open()
        s.wait_live()
        s.page.wait_for_timeout(300)
        assert s.page.evaluate("window.__cls") < 0.02, s.page.evaluate("window.__cls")
    html = (pathlib.Path(root) / "index.html").read_text()
    assert html.index('id="splash"') < html.index("css/leaflet.css"), "the splash style must come before every stylesheet link"
    assert "<noscript><style>html::before" in html


# ---------------------------------------------------------------- service worker
def test_sw_registers_on_localhost_and_caches_the_shell(root):
    def check(root):
        s = boot_sw(root)
        try:
            s.open()
            s.wait_live()
            wait_controlled(s)
            names = cache_names(s)
            v = sw_version(root)
            assert f"septer-shell-{v}" in names, (names, v)
            urls = cached_urls(s)[f"septer-shell-{v}"]
            rel = {u.replace(s.base + "/", "") for u in urls}
            sw = (pathlib.Path(root) / "sw.js").read_text()
            shell = json.loads(re.search(r"var SHELL = (\[.*?\]);", sw).group(1))
            want = {x if x != "./" else "" for x in shell}
            assert want <= rel, sorted(want - rel)
            assert any(u.startswith("js/main.js?v=") for u in rel) and any(u.startswith("data/bus-network.json?v=") for u in rel)
            assert any("leaflet.min.js" in u for u in urls), "Leaflet is stored for offline start"
            scope = s.page.evaluate("navigator.serviceWorker.getRegistration().then(r => r.scope)")
            assert scope == s.base + "/", scope  # a worker at the repo root controls the whole site (GitHub Pages: the project root)
            assert not s.console_errors, s.console_errors
        finally:
            s.__exit__(None, None, None)

    check(root)
    must_fail(check, root, ("sw.js", "return cache.put(u, r);", "return null;"))


def test_offline_reload_serves_the_shell_and_never_stale_vehicles(root):
    def check(root):
        s = boot_sw(root)
        try:
            s.open()
            s.wait_live()
            wait_controlled(s)
            assert s.markers() > 0
            s.ctx.set_offline(True)
            s.worker.mode = "abort"  # routed requests are answered by the mock even offline; make the feed fail like a real dead network
            s.page.reload()
            s.page.wait_for_function("window.SEPTA && window.SEPTA.started === true", timeout=10000, polling=100)
            assert s.page.evaluate("document.documentElement.classList.contains('app-ready')")
            assert s.page.is_visible("#offlineBar")
            assert "offline" in s.page.inner_text("#offlineBar").lower()
            assert s.page.get_attribute("#offlineBar", "role") == "status"
            assert s.page.is_visible("#panel") or s.page.is_visible("#sheetHandle")
            s.page.wait_for_timeout(500)
            assert s.markers() == 0, "no vehicle from an earlier visit may be drawn as live"
            assert not re.search(r"Live", s.page.inner_text("#statusText")), s.page.inner_text("#statusText")
            s.ctx.set_offline(False)
            s.worker.mode = "ok"
            assert s.page.evaluate("navigator.onLine")
            s.page.wait_for_function("document.getElementById('offlineBar').hidden", timeout=5000, polling=100)
        finally:
            s.__exit__(None, None, None)

    check(root)
    must_fail(check, root, ("sw.js", "return cache.put(u, r);", "return null;"))


def test_live_feeds_and_third_party_calls_are_never_cached(root):
    def check(r):
        s = boot_sw(r)
        try:
            s.open()
            s.wait_live()
            wait_controlled(s)
            s.page.reload()  # now the worker is in the path of every request
            s.wait_live()
            s.page.evaluate("fetch('https://photon.komoot.io/api/?q=test').catch(() => 0)")
            s.page.evaluate("fetch('https://routing.openstreetmap.de/routed-foot/route/v1/driving/0,0;1,1').catch(() => 0)")
            s.page.wait_for_timeout(500)
            every = [u for urls in cached_urls(s).values() for u in urls]
            bad = [u for u in every if re.search(r"workers\.dev|septa\.org|photon\.komoot|routing\.openstreetmap|bcycle", u)]
            assert not bad, bad
            assert s.worker.hits and not s.septa_direct
            # the feed is requested again on every refresh rather than answered by the worker
            before = len(s.worker.hits)
            s.tick(16000)
            assert len(s.worker.hits) > before
        finally:
            s.__exit__(None, None, None)
    check(root)
    must_fail(check, root, ("sw.js", "'fonts.gstatic.com']", "'fonts.gstatic.com', '" + WORKER_HOST + "']"))


def test_tiles_are_cached_but_bounded_and_old_caches_are_cleaned(root):
    with site_copy(root, [("sw.js", "var RUNTIME_MAX = 240;", "var RUNTIME_MAX = 5;")]) as r:
        s = boot_sw(r)
        try:
            s.open()
            s.wait_live()
            wait_controlled(s)
            s.page.evaluate("""async () => { await caches.open('septer-shell-oldoldold').then(c => c.put('/x', new Response('x')));
              await caches.open('someone-elses-cache').then(c => c.put('/y', new Response('y'))); }""")
            s.page.reload()
            s.wait_live()
            s.page.evaluate("""async () => { for (let i = 0; i < 12; i++) await new Promise(res => { const im = new Image(); im.onload = im.onerror = res; im.src = 'https://tile.openstreetmap.org/9/' + i + '/6.png'; }); }""")
            s.page.wait_for_timeout(600)
            urls = cached_urls(s)
            run = urls.get("septer-runtime-v1", [])
            assert 0 < len(run) <= 5, run
            assert all("tile.openstreetmap.org" in u or "fonts." in u for u in run)
            assert "someone-elses-cache" in urls  # only our own shell caches are touched
        finally:
            s.__exit__(None, None, None)
    # old shell caches go away when the worker activates (it activated before the stale one was added, so force the check with an update)
    with site_copy(root) as r:
        s = boot_sw(r)
        try:
            s.open()
            wait_controlled(s)
            s.page.evaluate("caches.open('septer-shell-oldoldold').then(c => c.put('/x', new Response('x')))")
            (r / "js" / "util.js").write_text((r / "js" / "util.js").read_text() + "\n// v2\n")
            stamp_version.main(["--root", str(r)])
            s.page.evaluate("navigator.serviceWorker.getRegistration().then(g => g.update())")
            s.page.wait_for_selector("#updateCard", state="visible", timeout=15000)
            assert "septer-shell-oldoldold" in cache_names(s)  # still waiting: nothing is deleted under a running page
            s.page.click("#updateCard .ic-go")
            s.page.wait_for_function(f"caches.keys().then(k => k.length && !k.includes('septer-shell-oldoldold') && k.includes('septer-shell-{sw_version(r)}'))", timeout=15000, polling=200)
        finally:
            s.__exit__(None, None, None)


def test_update_flow_offers_a_reload_and_applies_it(root):
    with site_copy(root) as r:
        s = boot_sw(r)
        try:
            s.open()
            s.wait_live()
            wait_controlled(s)
            old = sw_version(r)
            assert not s.page.is_visible("#updateCard") if s.page.query_selector("#updateCard") else True
            util = r / "js" / "util.js"
            util.write_text(util.read_text() + "\n// second release\n")
            stamp_version.main(["--root", str(r)])
            new = sw_version(r)
            assert new != old
            tok = re.search(r"js/util\.js\?v=([0-9a-f]+)", (r / "index.html").read_text()).group(1)
            s.page.evaluate("navigator.serviceWorker.getRegistration().then(g => g.update())")
            s.page.wait_for_selector("#updateCard", state="visible", timeout=15000)
            assert "new version" in s.page.inner_text("#updateCard").lower()
            assert s.page.evaluate("navigator.serviceWorker.getRegistration().then(g => !!g.waiting)")
            assert f"septer-shell-{old}" in cache_names(s) and f"septer-shell-{new}" in cache_names(s)
            # "Later" hides it without applying anything
            s.page.click("#updateCard .ic-x")
            assert not s.page.is_visible("#updateCard")
            assert s.page.evaluate("navigator.serviceWorker.getRegistration().then(g => !!g.waiting)")
            s.page.evaluate("navigator.serviceWorker.getRegistration().then(g => g.update())")  # nothing new: card stays away
            # apply it
            s.page.evaluate("window.SEPTA.install.offerUpdate()")  # e.g. the next time the app is reopened
            s.page.wait_for_selector("#updateCard", state="visible", timeout=3000)
            s.page.wait_for_timeout(300)
            with s.page.expect_navigation(timeout=15000):
                s.page.click("#updateCard .ic-go")
            s.page.wait_for_function("window.SEPTA && window.SEPTA.started === true", timeout=10000, polling=100)
            wait_controlled(s)
            assert any(f"js/util.js?v={tok}" in x.get_attribute("src") for x in s.page.query_selector_all("script[src]"))
            names = cache_names(s)
            assert f"septer-shell-{new}" in names and f"septer-shell-{old}" not in names, names
        finally:
            s.__exit__(None, None, None)


def test_registration_failure_never_breaks_the_app(root):
    boot = "Object.defineProperty(navigator, 'serviceWorker', {get() { throw new Error('blocked'); }});"
    with Session(root, init_scripts=[boot, "window.__SEPTA_TEST__ = true"]) as s:
        s.open()
        s.wait_live()
        assert s.page.evaluate("window.SEPTA.failed.length === 0") and s.markers() > 0
    with Session(root, service_workers=True, extra_routes={"/sw.js": (404, "text/plain", "no")}) as s:  # a missing worker file is ignored
        s.open()
        s.wait_live()
        assert s.markers() > 0
    src = (pathlib.Path(root) / "js" / "install.js").read_text()  # a plain-http, non-localhost origin cannot register a worker anyway; the page must not try
    assert "location.protocol === 'https:'" in src and "'localhost'" in src and "'127.0.0.1'" in src


# ---------------------------------------------------------------- install experience
def card_visible(s, sel):
    return s.page.query_selector(sel) is not None and s.page.is_visible(sel)


def stored(s):
    return json.loads(s.page.evaluate(f"localStorage.getItem({json.dumps(KEY)})") or "{}")


def test_install_card_logic_on_chromium_phone(root):
    def check(r):
        # first visit, nothing done yet: the event is held (default prevented) but no card
        with phone(r) as s:
            s.open()
            s.wait_live()
            assert s.page.evaluate(PROMPT_EVENT) is True
            s.page.wait_for_timeout(200)
            assert not card_visible(s, "#installCard")
            assert stored(s)["visits"] == 1
            # a search is the first sign of use
            s.page.evaluate("document.getElementById('searchForm').dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}))")
            s.page.wait_for_selector("#installCard", state="visible", timeout=3000)
            txt = s.page.inner_text("#installCard")
            assert "Install Septer" in txt
            s.page.wait_for_timeout(400)  # the entrance transition
            s.page.evaluate("document.documentElement.style.setProperty('--tabbar-h', '0px')")  # the phone tab bar is tested in test_tabs
            b = s.page.evaluate("(() => { const r = document.getElementById('installCard').getBoundingClientRect(); return [innerHeight - r.bottom, r.left, innerWidth - r.right, getComputedStyle(document.getElementById('installCard')).position]; })()")
            assert b[3] == "fixed" and abs(b[0] - 12) < 1.5 and b[1] >= 15 and b[2] >= 15, b
            s.page.evaluate("document.documentElement.style.setProperty('--tabbar-h', '64px')")
            b2 = s.page.evaluate("innerHeight - document.getElementById('installCard').getBoundingClientRect().bottom")
            assert abs(b2 - 76) < 1.5, b2  # sits above the tab bar Package A adds
            s.page.evaluate("document.documentElement.style.removeProperty('--tabbar-h')")
            # hidden while the keyboard is up
            s.page.focus("#addr")
            s.page.wait_for_function("document.getElementById('installCard').hidden", timeout=2000, polling=50)
            s.page.evaluate("document.activeElement.blur()")
            s.page.wait_for_function("!document.getElementById('installCard').hidden", timeout=2000, polling=50)
            # the buttons are at least 44 px
            for sel in ("#installCard .ic-go", "#installCard .ic-x"):
                h = s.page.evaluate(f"(() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return [r.width, r.height]; }})()")
                assert h[0] >= 44 and h[1] >= 44, (sel, h)
            # Install calls the saved prompt exactly once
            s.page.click("#installCard .ic-go")
            s.page.wait_for_function("window.__prompts === 1", timeout=2000, polling=50)
            assert not card_visible(s, "#installCard")
            s.page.wait_for_function(f"JSON.parse(localStorage.getItem({json.dumps(KEY)})).installed === true", timeout=2000, polling=50)
        # Not now: remembered for 30 days
        with phone(r) as s:
            s.open()
            s.wait_live()
            s.page.evaluate(PROMPT_EVENT)
            s.page.evaluate("window.SEPTA.install.markEngaged()")
            s.page.wait_for_selector("#installCard", state="visible", timeout=3000)
            s.page.click("#installCard .ic-x")
            assert not card_visible(s, "#installCard")
            at = stored(s)["dismissedAt"]
            assert abs(at - time.time() * 1000) < 120000, at
        recent = {"visits": 3, "dismissedAt": int(time.time() * 1000) - 29 * DAY_MS}
        old = {"visits": 3, "dismissedAt": int(time.time() * 1000) - 31 * DAY_MS}
        with phone(r, init_scripts=[seed(recent)]) as s:  # second visit onwards counts as use, but 29 days is still "dismissed"
            s.open()
            s.wait_live()
            s.page.evaluate(PROMPT_EVENT)
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#installCard")
        with phone(r, init_scripts=[seed(old)]) as s:
            s.open()
            s.wait_live()
            s.page.evaluate(PROMPT_EVENT)
            s.page.wait_for_selector("#installCard", state="visible", timeout=3000)
        # never in an installed (standalone) window, never on a desktop, and unusable storage does not throw
        with phone(r, init_scripts=[seed({"visits": 5}), "Object.defineProperty(navigator, 'standalone', {get: () => true});"]) as s:
            s.open()
            s.wait_live()
            s.page.evaluate(PROMPT_EVENT)
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#installCard")
        with Session(r, init_scripts=[seed({"visits": 5})]) as s:
            s.open()
            s.wait_live()
            s.page.evaluate(PROMPT_EVENT)
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#installCard")
        throwing = "Storage.prototype.getItem = function () { throw new Error('denied'); }; Storage.prototype.setItem = function () { throw new Error('denied'); };"
        with phone(r, init_scripts=["window.__SEPTA_TEST__ = true", throwing]) as s:
            s.open()
            s.page.wait_for_function("window.SEPTA && window.SEPTA.started === true", timeout=8000, polling=100)
            s.page.evaluate(PROMPT_EVENT)
            s.page.evaluate("window.SEPTA.install.markEngaged()")
            s.page.wait_for_selector("#installCard", state="visible", timeout=3000)
            s.page.click("#installCard .ic-x")  # remembered only for this page; still no error
            assert not s.console_errors or all("denied" not in e for e in s.console_errors if e.startswith("pageerror")), s.console_errors
    check(root)
    must_fail(check, root, ("js/install.js", "var DISMISS_MS = 30 * 24 * 60 * 60 * 1000;", "var DISMISS_MS = 0;"))
    must_fail(check, root, ("js/install.js", "    if (standalone()) return null;\n", ""))
    must_fail(check, root, ("js/install.js", "    if (!engaged) return null;\n", ""))


def test_ios_safari_hint_once(root):
    def check(r):
        with phone(r, user_agent=IPHONE, init_scripts=[seed({"visits": 1})]) as s:
            s.open()
            s.wait_live()
            s.page.wait_for_selector("#iosHintCard", state="visible", timeout=3000)
            t = s.page.inner_text("#iosHintCard")
            assert "Add Septer to your Home Screen" in t and "Share, then Add to Home Screen" in t, t
            assert s.page.query_selector("#iosHintCard svg") is not None
            assert s.page.get_attribute("#iosHintCard svg", "aria-hidden") == "true"
            s.page.evaluate("document.documentElement.style.setProperty('--tabbar-h', '0px')")  # the phone tab bar is tested in test_tabs
            pos = s.page.evaluate("(() => { const r = document.getElementById('iosHintCard').getBoundingClientRect(); return [getComputedStyle(document.getElementById('iosHintCard')).position, innerHeight - r.bottom]; })()")
            assert pos[0] == "fixed" and abs(pos[1] - 12) < 1.5, pos
            s.page.click("#iosHintCard .ic-x")
            assert not card_visible(s, "#iosHintCard")
            assert stored(s)["iosDone"] is True
            s.page.reload()
            s.wait_live()
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#iosHintCard"), "one time only"
        # first visit with no use yet: nothing
        with phone(r, user_agent=IPHONE) as s:
            s.open()
            s.wait_live()
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#iosHintCard")
            s.page.evaluate("document.getElementById('searchForm').dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}))")
            s.page.wait_for_selector("#iosHintCard", state="visible", timeout=3000)
        # not in other iOS browsers, not once installed, never on a desktop
        with phone(r, user_agent=IPHONE_CHROME, init_scripts=[seed({"visits": 4})]) as s:
            s.open()
            s.wait_live()
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#iosHintCard")
        with phone(r, user_agent=IPHONE, init_scripts=[seed({"visits": 4}), "Object.defineProperty(navigator, 'standalone', {get: () => true});"]) as s:
            s.open()
            s.wait_live()
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#iosHintCard")
        with Session(r, init_scripts=[seed({"visits": 4})]) as s:
            s.open()
            s.wait_live()
            s.page.wait_for_timeout(300)
            assert not card_visible(s, "#iosHintCard")
    check(root)
    must_fail(check, root, ("js/install.js", "!/CriOS|FxiOS", "!/Nothing|FxiOS"))
    must_fail(check, root, ("js/install.js", "patch({ iosDone: true });", "patch({});"))
