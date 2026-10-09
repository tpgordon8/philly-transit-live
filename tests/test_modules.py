"""WP3: the page is a set of classic scripts under js/ (ARCHITECTURE.md section 14): load failures are visible, only
one namespace is added to window, and the files stay small."""
import pathlib
import re

from harness import Session

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_isnum_is_defined_once_and_exported_before_the_leaflet_early_return",
    "test_missing_script_file_shows_error_banner",
    "test_page_adds_only_the_septa_namespace",
}

HOOK = "window.__SEPTA_TEST__ = true"
FILES = ["util", "feed", "map", "landmarks", "suggest", "panel", "stops", "alerts", "routing", "candidates", "planner", "trip", "sheet", "main"]


def test_missing_script_file_shows_error_banner(root):
    """If any js file fails to load the visitor sees a banner naming it, not a blank page."""
    for name in ("feed", "trip", "main"):
        with Session(root, extra_routes={f"/js/{name}.js": (404, "text/plain", "not found")}) as s:
            s.open()
            s.page.wait_for_selector("#loadError", timeout=5000)
            assert s.page.is_visible("#loadError")
            text = s.page.inner_text("#loadError")
            assert text == "Part of Septer didn't load. Check your connection and reload the page.", text
            assert not re.search(r"\.js|\(", text), text  # no file names in rider text; they go to the console and S.failed
            assert any(f"{name}.js" in f for f in s.page.evaluate("window.SEPTA.failed")), name
            assert s.page.get_attribute("#loadError", "role") == "alert"
            box = s.page.evaluate("(() => { const r = document.querySelector('#loadError').getBoundingClientRect(); return [r.top, r.width, innerWidth]; })()")
            assert box[0] <= 1 and box[1] >= box[2] - 1, box  # pinned to the top, full width


def test_healthy_page_shows_no_error_banner(root):
    with Session(root) as s:
        s.open()
        s.wait_live()
        assert s.page.query_selector("#loadError") is None
        assert s.page.evaluate("window.SEPTA.started === true && window.SEPTA.failed.length === 0")
        assert not s.console_errors, s.console_errors


def test_page_adds_only_the_septa_namespace(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        s.wait_live()
        extra = s.page.evaluate("""() => { const f = document.createElement('iframe'); document.body.appendChild(f);
            const base = new Set(Object.getOwnPropertyNames(f.contentWindow)); f.remove();
            return Object.getOwnPropertyNames(window).filter(k => !base.has(k)); }""")
        allowed = {"SEPTA", "L", "leaflet", "__SEPTA_TEST__"}  # our namespace, Leaflet (CDN script; it also exposes `leaflet`), the test hook
        stray = sorted(k for k in extra if k not in allowed and not k.startswith("__pw") and not k.startswith("_leaflet"))
        assert not stray, f"unexpected globals: {stray}"
        assert set(s.page.evaluate("Object.keys(window.SEPTA)")) >= set(FILES) - {"main"}  # main.js adds no namespace of its own


def test_js_files_are_small_and_listed_in_order(root):
    root = pathlib.Path(root)
    html = (root / "index.html").read_text()
    listed = re.findall(r'<script src="js/([a-z]+)\.js(?:\?v=[0-9a-f]+)?"></script>', html)
    assert listed == FILES, listed
    for name in FILES:
        n = (root / "js" / f"{name}.js").read_text().count("\n")
        assert n <= 700, f"js/{name}.js has {n} lines"
    assert html.index("leaflet.min.js") < html.index("js/util.js"), "Leaflet must load before the app"
    inline = sum(m.count("\n") + 1 for m in re.findall(r"<script>\n(.*?)</script>", html, flags=re.S))
    assert inline < 60, inline


def test_isnum_is_defined_once_and_exported_before_the_leaflet_early_return(root):
    root = pathlib.Path(root)
    src = {n: (root / "js" / f"{n}.js").read_text() for n in FILES}
    defs = [n for n in FILES if re.search(r"function isNum\(", src[n])]
    assert defs == ["util"], defs
    u = src["util"]
    early = re.search(r"if \(typeof L === 'undefined'\) \{", u).start()
    assert re.search(r"function isNum\(", u).start() < early and u.index("S.util.isNum = isNum") < early, "isNum must exist even when Leaflet is missing"
    for name in ("routing", "planner", "trip"):
        assert re.search(r"isNum\s*=\s*S\.util\.isNum", src[name]), f"{name}.js must import isNum from util"


def test_worker_header_comment_says_septer(root):
    first = (pathlib.Path(root) / "worker" / "worker.js").read_text().split("\n")[0]
    assert "Septer" in first and "Philly Transit Live" not in first, first
