"""WP-H2 accessibility and visual polish: direction badges by zoom, marker focus and selection looks, border and colour contrast
(computed from the page's own styles, light and dark), the on-chip cue, reduced motion, the phone card header, the 760 px
breakpoint, the stop card order and the skip link. Contrast is computed here with the WCAG formula, not asserted from hex codes."""
import re

from harness import Session
from test_responsive import boot, rect, select_vehicle, session

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_badge_hidden_at_low_zoom_shown_on_selected_and_unknown",
    "test_border_contrast_is_3_to_1_in_both_schemes",
    "test_focused_marker_is_raised_and_ringed",
}

SCHEMES = ("light", "dark")
TILES_LIGHT = ("#e8e0d8", "#f2efe9")  # typical OSM tile grounds


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def rgb(css):
    """'rgb(1, 2, 3)', 'rgba(...)' or '#rrggbb' -> (r, g, b)."""
    css = css.strip()
    if css.startswith("#"):
        h = css[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    nums = re.findall(r"[\d.]+", css)
    return tuple(round(float(n)) for n in nums[:3])


def lum(c):
    r, g, b = rgb(c) if isinstance(c, str) else c
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def token(s, name):
    return s.page.evaluate("(n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()", name)


# ------------------------------------------------------------------ 1. direction badges

def test_badge_hidden_at_low_zoom_shown_on_selected_and_unknown(root):
    with Session(root) as s:
        boot(s)
        assert s.page.evaluate("window.SEPTA.map.map.getZoom()") < 16
        assert s.page.evaluate("document.querySelector('#map').classList.contains('dir-lo')")
        disp = """() => [...document.querySelectorAll('.veh-wrap')].map(e => { const d = e.querySelector('.dr');
            return {sel: e.classList.contains('sel'), none: d.classList.contains('none'), shown: getComputedStyle(d).display !== 'none', label: e.getAttribute('aria-label')}; })"""
        rows = s.page.evaluate(disp)
        known = [r for r in rows if not r["none"]]
        unknown = [r for r in rows if r["none"]]
        assert known and unknown, "the fixture has vehicles with and without a direction"
        assert not any(r["shown"] for r in known), "letters hide below zoom 16"
        assert all(r["shown"] for r in unknown), "the ? badge stays"
        # the accessible name keeps the direction while the letter is hidden
        assert any(re.search(r"(north|east|south|west)bound| heading ", r["label"]) for r in known), [r["label"] for r in known[:5]]
        # a selected vehicle always shows its letter
        s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].find(e => !e.querySelector('.dr.none')).click()")
        s.page.wait_for_selector(".veh-wrap.sel")
        sel = s.page.evaluate("(() => { const e = document.querySelector('.veh-wrap.sel .dr'); return getComputedStyle(e).display !== 'none'; })()")
        assert sel
        assert sum(1 for r in s.page.evaluate(disp) if r["shown"] and not r["none"]) == 1
        # zooming in to 16 shows every letter, zooming out hides them again
        s.page.evaluate("window.SEPTA.map.map.setZoom(16, {animate: false})")
        s.page.wait_for_timeout(200)
        assert not s.page.evaluate("document.querySelector('#map').classList.contains('dir-lo')")
        assert all(r["shown"] for r in s.page.evaluate(disp))
        s.page.evaluate("window.SEPTA.map.map.setZoom(15, {animate: false})")
        s.page.wait_for_timeout(200)
        assert s.page.evaluate("document.querySelector('#map').classList.contains('dir-lo')")
        assert not s.console_errors, s.console_errors


# ------------------------------------------------------------------ 2/4. focus and selection looks

def test_focused_marker_is_raised_and_ringed(root):
    for scheme in SCHEMES:
        with Session(root, color_scheme=scheme) as s:
            boot(s)
            z = "i => document.querySelectorAll('.veh-wrap')[i].style.zIndex"
            before = int(s.page.evaluate(z, 0))
            s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].focus()")
            s.page.keyboard.press("Shift+Tab")  # keyboard modality: :focus-visible applies
            s.page.keyboard.press("Tab")
            focused = s.page.evaluate("document.activeElement.classList.contains('veh-wrap')")
            if not focused:
                s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].focus()")
            assert int(s.page.evaluate(z, 0)) >= before + 1500, "a focused marker is raised"
            ring = s.page.evaluate("""() => { const c = getComputedStyle(document.activeElement);
                return {w: c.outlineWidth, st: c.outlineStyle, oc: c.outlineColor, sh: c.boxShadow, fv: document.activeElement.matches(':focus-visible')}; }""")
            assert ring["fv"] and ring["st"] == "solid" and ring["w"] == "3px", (scheme, ring)
            inner = re.match(r"(rgba?\([^)]*\))", ring["sh"])
            assert inner, (scheme, ring)
            assert ratio(ring["oc"], inner.group(1)) >= 3, ("the two rings contrast with each other", scheme, ring)
            # the outer ring contrasts with the map ground of the scheme (light tiles, dark tiles)
            ground = TILES_LIGHT[0] if scheme == "light" else s.page.evaluate("getComputedStyle(document.querySelector('#map')).backgroundColor")
            assert ratio(ring["oc"], ground) >= 3, (scheme, ring, ground)
            s.page.keyboard.press("Tab")
            assert int(s.page.evaluate(z, 0)) == before, "blur restores the stacking"


def test_selected_glow_has_its_own_colour_and_stale_stays_readable(root):
    for scheme in SCHEMES:
        with Session(root, color_scheme=scheme) as s:
            boot(s)
            sel, acc, bus, train = (rgb(token(s, "--" + n)) for n in ("sel", "accent", "bus", "train"))
            assert len({sel, acc, bus, train}) == 4, "the selection colour is not the accent, bus or train colour"
            assert acc != bus, "bus blue is not exactly the accent"
            s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].click()")
            s.page.wait_for_selector(".veh-wrap.sel")
            f = s.page.evaluate("getComputedStyle(document.querySelector('.veh-wrap.sel .vb')).filter")
            assert f.count("drop-shadow") >= 3 and f"rgb({sel[0]}, {sel[1]}, {sel[2]})" in f, f
            # stale: opacity .7 and a dashed outline, so the route number stays readable
            s.page.evaluate("document.querySelectorAll('.veh-wrap')[1].classList.add('stale')")
            c = s.page.evaluate("""() => { const e = document.querySelectorAll('.veh-wrap')[1]; return {o: getComputedStyle(e).opacity,
                da: getComputedStyle(e.querySelector('.bd')).strokeDasharray, pill: getComputedStyle(e.querySelector('.rt')).backgroundColor,
                ink: getComputedStyle(e.querySelector('.rt')).color}; }""")
            assert float(c["o"]) == 0.7 and c["da"] not in ("none", ""), c
            ground = TILES_LIGHT[0] if scheme == "light" else "#0e1620"
            pill = tuple(0.7 * p + 0.3 * g for p, g in zip(rgb(c["pill"]), rgb(ground)))
            ink = tuple(0.7 * p + 0.3 * g for p, g in zip(rgb(c["ink"]), rgb(ground)))
            assert ratio(pill, ink) >= 4.5, ("route number on a stale marker", scheme, ratio(pill, ink))


def test_location_dot_has_own_token_ring_and_reduced_motion_pulse(root):
    for scheme in SCHEMES:
        with Session(root, color_scheme=scheme) as s:
            boot(s)
            me = rgb(token(s, "--me"))
            assert me != rgb(token(s, "--accent")) and me != rgb(token(s, "--bus"))
            d = s.page.evaluate("""() => { const e = document.querySelector('.pin .me'), c = getComputedStyle(e), a = getComputedStyle(e, '::after');
                return {bg: c.backgroundColor, bw: c.borderTopWidth, bc: c.borderTopColor, anim: a.animationName}; }""")
            assert rgb(d["bg"]) == me and d["bw"] == "3px" and rgb(d["bc"]) == (255, 255, 255), d
            assert d["anim"] == "mepulse", d
    with Session(root, reduced_motion="reduce") as s:
        boot(s)
        assert s.page.evaluate("getComputedStyle(document.querySelector('.pin .me'), '::after').animationName") == "none"


# ------------------------------------------------------------------ 2. colour tokens

def test_train_trolley_bus_contrast_tokens(root):
    with Session(root, color_scheme="light") as s:
        boot(s)
        for kind, floor in (("train", 3), ("trolley", 3), ("bus", 3), ("subway", 3)):
            col = token(s, "--" + kind)
            for tile in TILES_LIGHT:
                assert ratio(col, tile) >= floor, (kind, col, tile, ratio(col, tile))
        body = s.page.evaluate("""() => { const e = document.querySelector('.veh-wrap.k-train .bd'); return e ? getComputedStyle(e).fill : null; }""")
        if body:
            assert rgb(body) == rgb(token(s, "--train")), "the train body is drawn in the token"
    with Session(root, color_scheme="dark") as s:
        boot(s)
        ground = s.page.evaluate("getComputedStyle(document.querySelector('#map')).backgroundColor")
        for kind in ("train", "trolley", "bus", "subway"):
            assert ratio(token(s, "--" + kind), ground) >= 3, kind


def test_dark_tiles_are_quieter(root):
    with Session(root, color_scheme="dark") as s:
        boot(s)
        f = token(s, "--tile-filter")
        assert re.search(r"saturate\(\.?0?\.35\)", f) and re.search(r"brightness\(\.?0?\.8\)", f), f
        assert s.page.evaluate("getComputedStyle(document.querySelector('.leaflet-tile-pane')).filter") != "none"
    with Session(root, color_scheme="light") as s:
        boot(s)
        assert token(s, "--tile-filter") == "none"


# ------------------------------------------------------------------ 3. borders and chips

def test_border_contrast_is_3_to_1_in_both_schemes(root):
    for scheme in SCHEMES:
        with Session(root, color_scheme=scheme) as s:
            boot(s)
            s.page.click(".chip.k-trolley")  # the legacy test defaults have every mode on; an unchecked chip is the case to measure
            rows = s.page.evaluate("""() => {
              const bg = e => { for (let n = e; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; if (!/rgba\\(.*, 0\\)|transparent/.test(c)) return c; } return 'rgb(255,255,255)'; };
              const out = [];
              const add = (name, e) => { const c = getComputedStyle(e); out.push({name, border: c.borderTopColor, width: c.borderTopWidth, inside: bg(e), outside: bg(e.parentElement)}); };
              for (const id of ['addr', 'tripFrom', 'tripTo', 'placeName']) add('#' + id, document.getElementById(id));
              add('chip:not(.on)', document.querySelector('.chip:not(.on)'));
              return out; }""")
            assert len(rows) == 5
            for r in rows:
                assert float(r["width"].replace("px", "")) >= 1, r
                assert ratio(r["border"], r["outside"]) >= 3, (scheme, r, ratio(r["border"], r["outside"]))
                assert ratio(r["border"], r["inside"]) >= 3, (scheme, r, ratio(r["border"], r["inside"]))
    with Session(root) as s:  # the stop card's own field and select
        boot(s, "#stop=14880&route=21")
        s.page.wait_for_selector("#stopCard:not([hidden]) #alertMin")
        for scheme in SCHEMES:
            s.page.emulate_media(color_scheme=scheme)
            c = s.page.evaluate("""() => { const e = document.querySelector('#alertMin'), c = getComputedStyle(e); return [c.borderTopColor, getComputedStyle(document.querySelector('#stopCard')).backgroundColor]; }""")
            assert ratio(*c) >= 3, (scheme, c)


def test_on_chip_has_a_non_colour_cue(root):
    with Session(root) as s:
        boot(s)
        s.page.click(".chip.k-trolley")  # legacy test defaults: all four modes start on
        cue = """(sel) => { const c = document.querySelector(sel); return {w: parseInt(getComputedStyle(c).fontWeight, 10),
            glyph: getComputedStyle(c.querySelector('.sw'), '::after').content}; }"""
        on = s.page.evaluate(cue, ".chip.on")
        off = s.page.evaluate(cue, ".chip:not(.on)")
        assert on["w"] >= 700 and off["w"] < 700, (on, off)
        assert on["glyph"] not in ("none", "normal"), on
        assert off["glyph"] in ("none", "normal"), off
        s.page.click(".chip.k-trolley")
        assert s.page.evaluate(cue, ".chip.k-trolley")["w"] >= 700


# ------------------------------------------------------------------ 4. skip link

def test_skip_link_is_first_in_map_and_jumps_past_markers(root):
    with Session(root) as s:
        boot(s)
        first = s.page.evaluate("""() => { const st = document.querySelector('#stage');
            return [...st.querySelectorAll('a[href], button, [tabindex]:not([tabindex="-1"])')][0].id; }""")
        assert first == "skipVeh", first
        assert s.page.inner_text("#skipVeh") == "Skip vehicles"
        assert rect(s, "#skipVeh")["b"] <= 0, "off screen until it has focus"
        s.page.focus("#skipVeh")
        r = rect(s, "#skipVeh")
        assert r["t"] >= 0 and r["w"] >= 44 and r["h"] >= 44, r
        for _ in range(3):  # without the link, Tab walks the markers one by one
            s.page.keyboard.press("Tab")
        assert s.page.evaluate("document.activeElement.classList.contains('veh-wrap')")
        s.page.focus("#skipVeh")
        s.page.keyboard.press("Enter")
        assert s.page.evaluate("document.activeElement.classList.contains('leaflet-control-zoom-in')")


# ------------------------------------------------------------------ 7. reduced motion

def test_reduced_motion_map_options(root):
    probe = """() => { const m = window.SEPTA.map.map; return {za: m.options.zoomAnimation, fa: m.options.fadeAnimation, mz: m.options.markerZoomAnimation,
        ok: window.SEPTA.map.animOK()}; }"""
    with Session(root, reduced_motion="reduce") as s:
        boot(s)
        assert s.page.evaluate(probe) == {"za": False, "fa": False, "mz": False, "ok": False}
        s.page.evaluate("""() => { const m = window.SEPTA.map.map; window.__fit = null; const f = m.fitBounds.bind(m);
            m.fitBounds = (b, o) => { window.__fit = o; return f(b, o); }; window.SEPTA.map.fitRadius(); }""")
        assert s.page.evaluate("window.__fit.animate") is False
        # a small setView move does not glide
        s.page.evaluate("""() => { const m = window.SEPTA.map.map, c = m.getCenter(); m.setView([c.lat + 0.0005, c.lng], m.getZoom()); }""")
        assert not s.page.evaluate("document.querySelector('.leaflet-map-pane').classList.contains('leaflet-pan-anim')")
    with Session(root, reduced_motion="no-preference") as s:
        boot(s)
        p = s.page.evaluate(probe)
        assert p["za"] is True and p["fa"] is True and p["mz"] is False and p["ok"] is True, p
        s.page.evaluate("""() => { const m = window.SEPTA.map.map, c = m.getCenter(); m.setView([c.lat + 0.0005, c.lng], m.getZoom()); }""")
        assert s.page.evaluate("document.querySelector('.leaflet-map-pane').classList.contains('leaflet-pan-anim')"), "control: motion is on without the preference"


# ------------------------------------------------------------------ 8. layout

def test_empty_note_leaves_no_gap_above_radius(root):
    with Session(root) as s:
        boot(s)
        assert s.page.evaluate("document.querySelector('#note').textContent") == ""
        assert s.page.get_attribute("#note", "aria-live") == "polite", "the live region stays in the page"
        assert rect(s, "#note")["h"] == 0
        gap = rect(s, ".radius")["t"] - rect(s, "#btnLocate")["b"]
        assert gap <= 16, gap
        s.page.evaluate("document.querySelector('#note').textContent = 'Located you'")
        assert rect(s, "#note")["h"] > 0, "text still shows when there is some"


def test_vehicle_card_header_does_not_wrap_on_phones(root):
    for vp in ((360, 740), (390, 844)):
        with session(root, vp) as s:
            boot(s)
            select_vehicle(s)
            card, head = rect(s, "#detail"), rect(s, "#detail .dh")
            close, badge, star = rect(s, "#detailClose"), rect(s, "#detail .rbadge"), rect(s, "#starBtn")
            assert close["w"] >= 44 and close["h"] >= 44, close
            assert abs(close["r"] - card["r"]) <= 2 and close["t"] - card["t"] <= 2, ("pinned top-right", close, card)
            assert s.page.get_attribute("#detailClose", "aria-label") == "Close vehicle details"
            cy = lambda r: (r["t"] + r["b"]) / 2  # noqa: E731
            assert abs(cy(badge) - cy(star)) <= 8, ("badge and star share one row", vp, badge, star)
            assert star["r"] <= close["l"] + 1, ("star clears the close button", star, close)
            assert head["h"] <= 80, ("header is a single row", vp, head)
            vs = s.page.evaluate("""() => { const b = document.querySelector('#viewStop'); if (!b) return null; const c = getComputedStyle(b);
                return {ghost: b.classList.contains('ghost'), border: c.borderTopColor, dd: b.closest('dd').getBoundingClientRect().height}; }""")
            if vs:
                assert vs["ghost"] and re.search(r"0\)$", vs["border"]) and vs["dd"] <= 72, vs


def test_stop_card_order_buttons_and_alert_sentence(root):
    with session(root, (390, 844)) as s:
        boot(s, "#stop=14880&route=21")
        s.page.wait_for_selector("#stopCard:not([hidden]) #alertMin")
        assert "ghost" in s.page.get_attribute("#copyStop", "class")
        assert "primary" not in s.page.get_attribute("#copyStop", "class")
        board, alert = rect(s, "#stopBoard"), rect(s, ".alertrow")
        assert board["t"] < alert["t"], ("arrival times come before the alert form", board, alert)
        sel, mins, add = rect(s, "#alertMin"), rect(s, ".alertmin"), rect(s, "#addAlert")
        assert abs((sel["t"] + sel["b"]) / 2 - (mins["t"] + mins["b"]) / 2) <= 2 and mins["r"] >= sel["r"], "select and 'min away' stay together"
        assert s.page.evaluate("getComputedStyle(document.querySelector('.alertmin')).whiteSpace") == "nowrap", "the select and 'min away' never split"
        assert add["w"] >= 80, ("Add alert keeps its full width", add)
        assert add["t"] >= sel["b"] - 1 and add["l"] <= sel["l"] + 40, ("Add alert on its own line", add, sel)
        # a row with no estimate shows small muted text instead of a large dash
        for r in s.page.evaluate("""() => [...document.querySelectorAll('#stopBoard .sbeta b')].map(b => ({t: b.textContent, none: b.classList.contains('none'), fs: parseFloat(getComputedStyle(b).fontSize)}))"""):
            if r["none"]:
                assert r["fs"] <= 13, r
            else:
                assert r["t"] != "—", r


# ------------------------------------------------------------------ 9. breakpoint

def test_breakpoint_760_side_panel_for_tablets(root):
    for w, h, side in ((820, 1180, True), (768, 1024, True), (761, 900, True), (760, 900, False), (600, 960, False), (390, 844, False)):
        with session(root, (w, h)) as s:
            boot(s)
            handle = s.page.evaluate("!!document.querySelector('#sheetHandle').getClientRects().length")
            p, m = rect(s, "#panel"), rect(s, "#map")
            narrow = s.page.evaluate("window.SEPTA.map.NARROW.matches")
            assert handle == (not side) and narrow == (not side), (w, handle, narrow)
            if side:
                assert p["r"] <= m["l"] + 1 and abs(p["w"] - 392) <= 2, (w, p, m)
                assert s.page.evaluate("document.querySelector('#app').dataset.sheet") in ("peek", None, "open")
            else:
                assert p["t"] >= m["b"] - 1 and abs(p["w"] - w) < 2, (w, p, m)
