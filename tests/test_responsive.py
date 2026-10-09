"""WP-E mobile and responsive pass (ARCHITECTURE.md 15.2): the app at ten widths plus phone landscape, with touch emulation on
phones. Per viewport: no horizontal scroll, tap targets of at least 44 px, text inputs of at least 16 px (iOS does not zoom
in), the panel reachable and the map visible, the bottom sheet behaves, the suggestion list stays inside the viewport and
clear of the field, the vehicle card and map controls do not overlap. Each viewport is its own test so the runner can spread them."""
import json
import pathlib
import re

from harness import FIX, Session

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_layout_390",
    "test_layout_1280",
    "test_layout_landscape_844x390",
    "test_sheet_toggle_and_keyboard_reach",
}

# (width, height) as in ARCHITECTURE.md 15.2; phones (up to 414 wide) and landscape phones get Chromium's mobile + touch emulation.
VIEWPORTS = [(320, 568), (360, 740), (390, 844), (414, 896), (600, 960), (768, 1024), (820, 1180), (1024, 768), (1280, 800), (1440, 900)]
LANDSCAPE = (844, 390)
MIN_TAP = 44
STOPS = json.loads((FIX / "Stops.json").read_text())
STOP_HASH = "#stop=14880&route=21"

CONTROLS_JS = """() => {
  const SEL = 'a[href], button, input, select, textarea, summary, [role=button], [tabindex]:not([tabindex="-1"])';
  const out = [];
  for (const e of document.querySelectorAll(SEL)) {
    if (e.closest('.leaflet-control-attribution, .sr-only, #loadError') || e.id === 'map' || e.matches('.leaflet-container')) continue;
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none' || cs.pointerEvents === 'none' || !e.getClientRects().length) continue;
    if (e.type === 'hidden') continue;
    let t = e;
    if (e.matches('input[type=checkbox], input[type=radio]')) t = e.closest('label') || e;
    const r = t.getClientRects()[0];
    out.push({tag: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).join('.') : ''),
      text: (e.textContent || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 24), w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
      font: e.matches('input[type=text], input:not([type]), textarea, select') ? parseFloat(cs.fontSize) : null});
  }
  return out;
}"""


def phone_like(vp):
    return vp[0] <= 414 or vp == LANDSCAPE


def session(root, vp, **kw):
    phone = phone_like(vp)
    return Session(root, viewport=vp, touch=phone or vp[0] <= 820, mobile=phone, **kw)


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()
    s.page.wait_for_timeout(300)


def rect(s, sel):
    return s.page.evaluate("""(sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect();
        return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; }""", sel)


def overlap(a, b):
    return a["l"] < b["r"] - 0.5 and b["l"] < a["r"] - 0.5 and a["t"] < b["b"] - 0.5 and b["t"] < a["b"] - 0.5


def handle_visible(s):
    return s.page.evaluate("(() => { const h = document.querySelector('#sheetHandle'); return !!h && h.getClientRects().length > 0 })()")


def sheet_open(s):
    return s.page.get_attribute("#sheetHandle", "aria-expanded") == "true"


def set_sheet(s, want_open):
    """Open or close the phone bottom sheet; a no-op where the panel is a sidebar."""
    if handle_visible(s) and sheet_open(s) != want_open:
        s.page.click("#sheetHandle")
        s.page.wait_for_timeout(120)


def pick(s, sel, text, label):
    """Type into an address field and tap the built-in suggestion with this label (no network)."""
    s.page.click(sel)
    s.page.fill(sel, text)
    s.page.locator(".sug-opt", has_text=label).first.click()


def plan_trip(s):
    set_sheet(s, True)
    pick(s, "#tripFrom", "city hall", "Philadelphia City Hall")
    pick(s, "#tripTo", "30th street", "30th Street Station")
    s.page.click("#tripGo")
    s.page.wait_for_selector("#tripResults .tp-card", timeout=15000)
    s.page.wait_for_timeout(500)


def select_vehicle(s):
    """Select a marker that is fully inside the map (so the click lands on it), the way a tap would."""
    s.page.evaluate("""() => { const m = document.querySelector('#map').getBoundingClientRect();
        const el = [...document.querySelectorAll('.veh-wrap')].find(e => { const r = e.getBoundingClientRect();
          return r.left > m.left + 10 && r.right < m.right - 60 && r.top > m.top + 70 && r.bottom < m.bottom - 140; }) || document.querySelector('.veh-wrap');
        el.click(); }""")
    s.page.wait_for_selector("#detail:not([hidden])")
    s.page.wait_for_timeout(400)


def open_suggestions(s):
    s.page.click("#addr")
    s.page.fill("#addr", "phil")
    s.page.wait_for_selector(".sug-opt")
    s.page.wait_for_timeout(150)


def metrics(s):
    return s.page.evaluate("""() => ({sw: document.documentElement.scrollWidth, bw: document.body.scrollWidth, iw: window.innerWidth, ih: window.innerHeight,
        panelSW: document.querySelector('#panel').scrollWidth, panelCW: document.querySelector('#panel').clientWidth})""")


def check_overflow(s, vp, what):
    m = metrics(s)
    assert m["sw"] <= m["iw"] and m["bw"] <= m["iw"], (vp, what, m)
    assert m["panelSW"] <= m["panelCW"] + 1, (vp, what, m)


def check_taps(s, vp, what):
    rows = s.page.evaluate(CONTROLS_JS)
    assert rows, what
    small = [r for r in rows if r["w"] < MIN_TAP - 0.5 or r["h"] < MIN_TAP - 0.5]
    assert not small, (vp, what, small[:12], len(small))
    small_font = [r for r in rows if r["font"] is not None and r["font"] < 16]
    assert not small_font, (vp, what, small_font)


def check_cards_clear(s, vp, what):
    """The vehicle card, the stop card and the map controls never overlap each other or the panel."""
    panel = rect(s, "#panel")
    stage = rect(s, "#stage")
    zoom = rect(s, ".leaflet-control-zoom")
    for sel in ("#detail", "#stopCard"):
        shown = s.page.evaluate("(sel) => { const e = document.querySelector(sel); return !!e && e.getClientRects().length > 0 }", sel)
        if not shown:
            continue
        c = rect(s, sel)
        assert c["l"] >= stage["l"] - 0.5 and c["r"] <= stage["r"] + 0.5 and c["t"] >= stage["t"] - 0.5 and c["b"] <= stage["b"] + 0.5, (vp, what, sel, c, stage)
        assert not overlap(c, panel), (vp, what, sel, c, panel)
        assert not overlap(c, zoom), (vp, what, sel, "overlaps the zoom buttons", c, zoom)
    if s.page.evaluate("!!document.querySelector('#detail:not([hidden])') && !!document.querySelector('#stopCard:not([hidden])') && document.querySelector('#stopCard').getClientRects().length > 0"):
        assert not overlap(rect(s, "#detail"), rect(s, "#stopCard")), (vp, what, "the two cards overlap")


def check_shell(s, vp):
    """Map visible, panel reachable, sheet or sidebar as the width says."""
    m, p = rect(s, "#map"), rect(s, "#panel")
    iw, ih = vp
    assert m["w"] > 0 and m["h"] >= min(220, ih * 0.3), (vp, "map too small", m)
    assert p["w"] > 0 and p["h"] > 0 and p["l"] >= -0.5 and p["r"] <= iw + 0.5 and p["b"] <= ih + 0.5, (vp, "panel outside the screen", p)
    stacked = iw <= 820 and not (vp == LANDSCAPE)
    assert handle_visible(s) == stacked, (vp, "sheet handle", stacked)
    if stacked:
        assert p["t"] >= m["b"] - 1 and abs(p["w"] - iw) < 2, (vp, m, p)
        h = rect(s, "#sheetHandle")
        assert h["h"] >= MIN_TAP - 0.5 and h["t"] >= p["t"] - 1 and h["b"] <= ih, (vp, h)
    else:
        assert p["r"] <= m["l"] + 1, (vp, "panel is a side column", p, m)


def check_focus_rings(s, vp):
    """Tab through the panel: every focused control shows a ring (outline or shadow), also the hidden chip checkboxes (their label shows it)."""
    s.page.keyboard.press("Tab")
    bad = []
    for _ in range(70):
        info = s.page.evaluate("""() => { const a = document.activeElement; if (!a || a === document.body) return null;
            const box = a.matches('input[type=checkbox]') ? a.closest('label') : a; const cs = getComputedStyle(a); const lc = getComputedStyle(box);
            const ring = (c) => (c.outlineStyle !== 'none' && parseFloat(c.outlineWidth) >= 2) || (c.boxShadow && c.boxShadow !== 'none');
            return {id: a.id || a.className || a.tagName, ring: ring(cs) || (a.matches('input[type=checkbox]') && lc.outlineStyle !== 'none' && ring(lc)),
                    focusVisible: a.matches(':focus-visible')}; }""")
        if info and info["focusVisible"] and not info["ring"]:
            bad.append(info["id"])
        s.page.keyboard.press("Tab")
    assert not bad, (vp, "controls without a visible focus ring", bad)


def run_layout(root, vp):
    with session(root, vp) as s:
        boot(s)
        check_shell(s, vp)
        check_overflow(s, vp, "closed")
        # panel closed (peek): only what is visible is measured; open: everything
        set_sheet(s, True)
        check_overflow(s, vp, "open")
        check_taps(s, vp, "open")
        # the panel can be scrolled to its end without the page growing sideways
        s.page.evaluate("document.querySelector('#panel').scrollTop = 99999")
        check_overflow(s, vp, "open, scrolled")
        s.page.evaluate("document.querySelector('#panel').scrollTop = 0")
        # suggestions
        open_suggestions(s)
        lst, fld = rect(s, ".sug-list"), rect(s, "#addr")
        assert lst and lst["l"] >= -0.5 and lst["r"] <= vp[0] + 0.5 and lst["t"] >= -0.5 and lst["b"] <= vp[1] + 0.5, (vp, "suggestion list outside the screen", lst)
        assert not overlap(lst, fld), (vp, "suggestion list covers the field", lst, fld)
        assert fld["t"] >= 0 and fld["b"] <= vp[1], (vp, "field not on screen", fld)
        check_overflow(s, vp, "suggestions")
        rows = s.page.evaluate("[...document.querySelectorAll('.sug-opt')].map(e => e.getBoundingClientRect().height)")
        assert rows and min(rows) >= MIN_TAP - 0.5, (vp, rows)
        s.page.keyboard.press("Escape")
        s.page.fill("#addr", "")
        # vehicle card
        select_vehicle(s)
        check_overflow(s, vp, "vehicle")
        check_taps(s, vp, "vehicle")
        check_cards_clear(s, vp, "vehicle")
        s.page.keyboard.press("Escape")
    with session(root, vp) as s:
        boot(s, STOP_HASH)
        s.page.wait_for_selector("#stopCard:not([hidden]) #copyStop")
        check_overflow(s, vp, "stop")
        check_taps(s, vp, "stop")
        check_cards_clear(s, vp, "stop")
        s.page.click("#copyStop")  # a tap on the card's buttons works and leaves the layout alone
        # a vehicle opened while the stop card is up: the cards share the map without overlapping each other or the zoom buttons
        select_vehicle(s)
        check_cards_clear(s, vp, "stop and vehicle")
        s.page.keyboard.press("Escape")
        set_sheet(s, True)
        check_focus_rings(s, vp)
    with session(root, vp) as s:
        boot(s)
        plan_trip(s)
        check_overflow(s, vp, "trip")
        check_taps(s, vp, "trip")
        s.page.evaluate("document.querySelector('#tripResults').scrollIntoView()")
        check_shell(s, vp)


def _make(vp, name):
    def t(root):
        run_layout(root, vp)
    t.__name__ = t.__qualname__ = name
    return t


for _vp in VIEWPORTS:
    globals()[f"test_layout_{_vp[0]}"] = _make(_vp, f"test_layout_{_vp[0]}")
globals()["test_layout_landscape_844x390"] = _make(LANDSCAPE, "test_layout_landscape_844x390")


def test_sheet_toggle_and_keyboard_reach(root):
    vp = (390, 844)
    with session(root, vp) as s:
        boot(s)
        assert not sheet_open(s) and s.page.get_attribute("#app", "data-sheet") == "peek"
        closed_map = rect(s, "#map")["h"]
        addr = rect(s, "#addr")
        assert addr["b"] <= vp[1] and addr["t"] > closed_map, ("search field reachable while the sheet is closed", addr)
        s.page.click("#sheetHandle")
        s.page.wait_for_timeout(150)
        assert sheet_open(s) and rect(s, "#map")["h"] < closed_map - 100
        # Leaflet was told: its own size matches the box
        assert s.page.evaluate("document.querySelector('.leaflet-container').clientHeight") == round(rect(s, "#map")["h"])
        s.page.click("#sheetHandle")
        s.page.wait_for_timeout(150)
        assert not sheet_open(s) and abs(rect(s, "#map")["h"] - closed_map) < 2
        # Tab into a control below the search field opens the sheet; the search field does not
        s.page.focus("#addr")
        assert not sheet_open(s)
        s.page.focus("#tripFrom")
        assert sheet_open(s)
        # keyboard: the layout shrinks (Android) -> the typed-in field and its list stay on screen
        s.page.set_viewport_size({"width": 390, "height": 844 - 340})
        s.page.wait_for_timeout(200)
        s.page.fill("#tripFrom", "phil")
        s.page.wait_for_selector(".sug-opt")
        fld, lst = rect(s, "#tripFrom"), rect(s, ".sug-list")
        assert fld["t"] >= 0 and fld["b"] <= 504, fld
        assert lst["t"] >= 0 and lst["b"] <= 504 and not overlap(fld, lst), (fld, lst)
        s.page.keyboard.press("Escape")
        s.page.set_viewport_size({"width": 390, "height": 844})
        # keyboard: the layout stays full height (iOS) and only visualViewport shrinks -> the page shrinks with it
        s.page.evaluate("""() => { const vv = window.visualViewport;
            Object.defineProperty(vv, 'height', {configurable: true, get: () => window.innerHeight - 330});
            vv.dispatchEvent(new Event('resize')); }""")
        s.page.wait_for_timeout(150)
        assert s.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--kb').trim()") == "330px"
        assert s.page.evaluate("document.querySelector('#app').getBoundingClientRect().bottom") <= 844 - 330 + 1
        s.page.evaluate("""() => { delete window.visualViewport.height; window.visualViewport.dispatchEvent(new Event('resize')); }""")
        s.page.wait_for_timeout(150)
        assert s.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--kb').trim()") == "0px"


def test_safe_area_dvh_and_viewport_meta(root):
    html = (pathlib.Path(root) / "index.html").read_text()
    assert "viewport-fit=cover" in html
    base = (pathlib.Path(root) / "css" / "base.css").read_text()
    css = "\n".join(p.read_text() for p in sorted((pathlib.Path(root) / "css").glob("*.css")))
    for side in ("top", "right", "bottom", "left"):
        assert f"env(safe-area-inset-{side}" in base, side  # the page itself keeps clear of notches and the home indicator
    assert re.search(r"100vh;\s*height:calc\(100dvh", css), "dvh height needs a vh fallback in front of it"


def test_tap_targets_and_fonts_when_populated(root):
    """Saved places, starred routes and a leave-now rule add buttons: all of them are 44 px too (phone and desktop)."""
    for vp in ((360, 740), (1280, 800)):
        with session(root, vp) as s:
            s.open()
            s.page.evaluate("""localStorage.setItem('septa.places.v1', JSON.stringify({home: {name: 'Home spot', lat: 39.95, lng: -75.16}, list: [{id: 'p1', name: 'Work', lat: 39.96, lng: -75.17}]}));
                               localStorage.setItem('septa.routes.v1', JSON.stringify({stars: ['21', 'train:Paoli/Thorndale'], onlyMine: false}))""")
            s.open(hash_=STOP_HASH)
            s.page.reload()
            s.wait_live()
            s.page.wait_for_selector("#addAlert")
            s.page.click("#addAlert")
            s.page.wait_for_timeout(300)
            set_sheet(s, True)
            check_taps(s, vp, "populated")
            check_overflow(s, vp, "populated")
