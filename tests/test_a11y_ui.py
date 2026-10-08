"""Hardening pass B (UI / accessibility): keyboard selection, live regions, phone toasts, pan above card, banner stacking,
touch targets, focus management, empty-state vs zoom control, badge contrast, clearSelection refactor."""
import json
import re

from harness import FIX, Session

STOPS = json.loads((FIX / "Stops.json").read_text())
SID, SROUTE = "14880", "21"
HASH = f"#stop={SID}&route={SROUTE}"
PHONE = (360, 640)
MLAT = 111195.0

LIVE_SEL = "[aria-live], [role=status], [role=alert], [role=log]"

OBSERVE = """() => {
  window.__liveMut = 0; window.__liveLog = [];
  const sel = %r;
  const inLive = n => { const e = n.nodeType === 1 ? n : n.parentElement; return e && e.closest(sel); };
  window.__obs = new MutationObserver(list => { for (const m of list) { const r = inLive(m.target); if (r) { window.__liveMut++; window.__liveLog.push((r.id || r.className || r.tagName) + ':' + m.type); } } });
  window.__obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
}""" % LIVE_SEL


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()
    s.page.wait_for_timeout(300)


def rect(s, sel):
    return s.page.evaluate("""(sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect();
        return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; }""", sel)


def overlap(a, b):
    return a["l"] < b["r"] and b["l"] < a["r"] and a["t"] < b["b"] and b["t"] < a["b"]


def click_marker(s, i=0):
    s.page.evaluate(f"document.querySelectorAll('.veh-wrap')[{i}].click()")


def sel_marker_rect(s):
    return rect(s, ".veh-wrap.sel")


def pane(s):
    return s.page.evaluate("document.querySelector('.leaflet-map-pane').style.transform")


# ------------------------------------------------------------------ 1. keyboard selection + accessible names

def test_marker_enter_space_select_and_label(root):
    with Session(root) as s:
        boot(s)
        info = s.page.evaluate("""() => [...document.querySelectorAll('.veh-wrap')].slice(0, 40).map(e => [e.getAttribute('role'), e.getAttribute('aria-label')])""")
        assert info
        for role, label in info:
            assert role == "button", role
            assert label and re.match(r"^(Route \S+ (bus|trolley)|Regional Rail train \S+.*?)( heading (N|NE|E|SE|S|SW|W|NW))?, ", label), label
            assert "999" not in label and "undefined" not in label and "null" not in label, label
        assert any("late" in l or "on time" in l or "early" in l for _, l in info)
        # Enter
        s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].focus()")
        s.page.keyboard.press("Enter")
        assert s.page.is_visible("#detail")
        assert s.page.evaluate("document.activeElement.id") == "detailHead"
        assert s.page.evaluate("document.querySelector('.veh-wrap.sel') === document.querySelectorAll('.veh-wrap')[0]")
        # Space on another marker (and the page must not scroll for it)
        s.page.evaluate("document.querySelectorAll('.veh-wrap')[1].focus()")
        s.page.keyboard.press("Space")
        assert s.page.evaluate("document.querySelector('.veh-wrap.sel') === document.querySelectorAll('.veh-wrap')[1]")
        assert s.page.evaluate("document.activeElement.id") == "detailHead"
        assert not s.console_errors, s.console_errors


def test_label_follows_refresh(root):
    with Session(root) as s:
        boot(s)
        before = s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].getAttribute('aria-label')")
        vid = s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].querySelector('.rt').textContent")
        bus = next((b for b in s.worker.data["TransitView"]["bus"] if b["route_id"] == vid and b["late"] is not None and 0 <= int(b["late"]) < 900), None)
        assert bus is not None
        old = bus["late"]
        bus["late"] = old + 7
        for b in s.worker.data["TransitView"]["bus"]:
            b["timestamp"] = int(b["timestamp"]) + 15
        s.tick(15500)
        after = s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].map(e => e.getAttribute('aria-label')).join('|')")
        assert f"{old + 7} min late" in after, (before, old)


# ------------------------------------------------------------------ 2. live regions

def test_status_text_not_live_and_state_changes_announced(root):
    with Session(root) as s:
        boot(s)
        r = s.page.evaluate("""() => ({
            statusLive: !!document.querySelector('#status[aria-live], #status[role=status]'),
            tickHidden: document.querySelector('#statusText').getAttribute('aria-hidden'),
            tickInLive: !!document.querySelector('#statusText').closest('[aria-live], [role=status], [role=alert]'),
            live: document.querySelector('#statusLive').textContent,
            detailLive: document.querySelector('#detail').hasAttribute('aria-live') })""")
        assert not r["statusLive"] and r["tickHidden"] == "true" and not r["tickInLive"], r
        assert re.match(r"^Live, \d+ vehicles? shown$", r["live"]), r
        assert not r["detailLive"], r
        # state change -> announced once
        s.worker.mode = "http502"
        for _ in range(3):
            s.tick(16000)
        assert s.page.inner_text("#statusLive") in ("Stale, showing last known positions", "Live data unavailable"), s.page.inner_text("#statusLive")


def test_no_live_region_mutations_on_plain_refresh(root):
    with Session(root) as s:
        boot(s, HASH)
        s.page.wait_for_selector("#copyStop")
        click_marker(s, 0)
        s.page.wait_for_selector("#detail:not([hidden])")
        s.page.evaluate(OBSERVE)
        for _ in range(3):
            for b in s.worker.data["TransitView"]["bus"]:
                b["timestamp"] = int(b["timestamp"]) + 15
            s.tick(15500)
        n, log = s.page.evaluate("[window.__liveMut, window.__liveLog]")
        assert n == 0, log[:10]
        # sanity: the observer does see a real state change
        s.worker.mode = "http502"
        for _ in range(2):
            s.tick(16000)
        assert s.page.evaluate("window.__liveMut") > 0


def test_failure_state_does_not_churn_alert_region(root):
    with Session(root) as s:
        s.worker.mode = "http502"
        s.open()
        s.page.wait_for_function("!document.querySelector('#banner').hidden", timeout=15000)
        s.tick(3000)
        s.page.evaluate(OBSERVE)
        s.tick(5000)  # five 1 s status ticks while the banner is up
        n, log = s.page.evaluate("[window.__liveMut, window.__liveLog]")
        assert n == 0, log[:10]


def test_detail_announced_once_on_open_only(root):
    with Session(root) as s:
        boot(s)
        assert s.page.inner_text("#detailLive") == ""
        click_marker(s, 0)
        txt = s.page.inner_text("#detailLive")
        assert "Vehicle details opened" in txt and re.search(r"Route|Regional Rail", txt), txt
        s.page.click("#detailClose")
        assert s.page.inner_text("#detailLive") == ""


# ------------------------------------------------------------------ 3. toasts on phones

def _toast_setup(s, minutes=(3, 5, 8)):
    from test_leave_alerts import add_alert, setup_moving, step
    setup_moving(s, 1000)
    s.open(hash_=HASH)
    s.wait_live()
    s.page.wait_for_selector("#addAlert")
    for _ in range(3):
        step(s)
    for m in minutes:
        add_alert(s, m)
    s.page.wait_for_timeout(200)


def visible_toasts(s):
    return s.page.evaluate("[...document.querySelectorAll('#toasts .toast')].filter(t => t.getClientRects().length).map(t => t.textContent)")


def test_phone_one_toast_at_bottom_queue_not_lost(root):
    from test_leave_alerts import HOOK
    with Session(root, viewport=PHONE, init_scripts=[HOOK]) as s:
        _toast_setup(s)
        total = s.page.locator("#toasts .toast").count()
        assert total == 3, total
        assert len(visible_toasts(s)) == 1
        t = rect(s, "#toasts .toast:last-child")
        assert t["l"] >= 7.5 and t["r"] <= 360 - 7.5 and abs(t["w"] - (360 - 16)) < 2, t
        assert t["b"] <= 640 and t["b"] >= 640 - 16, t
        card = rect(s, "#stopCard")
        title = rect(s, "#stopCard b")
        assert not overlap(t, title) and not overlap(t, rect(s, "#copyStop")) and not overlap(t, card), (t, card)
        z = s.page.evaluate("[getComputedStyle(document.querySelector('#toasts')).zIndex, getComputedStyle(document.querySelector('#detail')).zIndex].map(Number)")
        assert z[0] > z[1], z
        # newest wins; dismissing reveals the next, nothing is lost
        for left in (2, 1, 0):
            s.page.locator("#toasts .toast:last-child button").click()
            assert s.page.locator("#toasts .toast").count() == left
            assert len(visible_toasts(s)) == (1 if left else 0)
        assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_phone_toast_over_vehicle_card(root):
    from test_leave_alerts import HOOK
    with Session(root, viewport=PHONE, init_scripts=[HOOK]) as s:
        _toast_setup(s, (8,))
        click_marker(s, 0)
        s.tick(800)
        z = s.page.evaluate("""() => { const t = document.querySelector('#toasts .toast:last-child').getBoundingClientRect();
            const e = document.elementFromPoint(t.left + t.width / 2, t.top + t.height / 2); return !!e.closest('#toasts'); }""")
        assert z


def test_desktop_toasts_unchanged(root):
    from test_leave_alerts import HOOK
    with Session(root, init_scripts=[HOOK]) as s:
        _toast_setup(s)
        assert len(visible_toasts(s)) == 3
        t = rect(s, "#toasts .toast")
        assert t["l"] >= 400 and t["t"] < 60, t


# ------------------------------------------------------------------ 4. pan above the card on phones

def test_phone_select_pans_marker_above_card(root):
    with Session(root, viewport=PHONE) as s:
        boot(s)
        mp = rect(s, "#map")
        # candidate markers fully inside the map, lowest first (those are the ones the card would cover)
        idx = s.page.evaluate("""() => { const m = document.querySelector('#map').getBoundingClientRect();
            return [...document.querySelectorAll('.veh-wrap')].map((e, i) => [i, e.getBoundingClientRect()])
              .filter(([i, r]) => r.left >= m.left && r.right <= m.right && r.top >= m.top && r.bottom <= m.bottom)
              .sort((a, b) => b[1].top - a[1].top).map(a => a[0]); }""")
        assert len(idx) >= 3, idx
        zoom = s.page.evaluate("document.querySelector('.leaflet-tile').src")
        picks = [idx[0], idx[len(idx) // 2], idx[-1]]
        covered_without_pan = 0
        for i in picks:
            click_marker(s, i)
            s.tick(1200)
            card = rect(s, "#detail")
            mk = sel_marker_rect(s)
            assert mk and card
            assert not overlap(mk, card), (i, mk, card)
            assert mk["t"] >= mp["t"] - 0.5 and mk["l"] >= mp["l"] - 0.5 and mk["r"] <= mp["r"] + 0.5, (mk, mp)
            assert card["t"] - mp["t"] >= 60, card
            s.page.click("#detailClose")
        assert s.page.evaluate("document.querySelector('.leaflet-tile').src").split('/')[-3] == zoom.split('/')[-3], "zoom must not change"
        # not on refresh: select, let the view settle, then refresh twice and the pane must not move
        click_marker(s, idx[0])
        s.tick(1200)
        before = pane(s)
        for _ in range(2):
            for b in s.worker.data["TransitView"]["bus"]:
                b["timestamp"] = int(b["timestamp"]) + 15
            s.tick(15500)
        assert pane(s) == before


def test_desktop_select_does_not_pan(root):
    with Session(root) as s:
        boot(s)
        before = pane(s)
        click_marker(s, 0)
        s.tick(1200)
        assert pane(s) == before


# ------------------------------------------------------------------ 5. banner above cards on phones

def test_phone_banner_above_cards_text_unchanged(root):
    with Session(root, viewport=PHONE) as s:
        boot(s)
        click_marker(s, 0)
        s.tick(800)
        del s.worker.data["TrainView"]  # only Regional Rail fails: the warning banner, vehicles stay
        for _ in range(3):
            s.tick(16000)
        s.page.wait_for_function("!document.querySelector('#banner').hidden")
        assert "Showing last known positions for Regional Rail." in s.page.inner_text("#banner")
        assert s.page.is_visible("#detail")
        b = rect(s, "#banner")
        top = s.page.evaluate("""() => { const b = document.querySelector('#banner').getBoundingClientRect();
            const e = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return !!e.closest('#banner'); }""")
        assert top
        assert s.page.evaluate("(() => { const b = document.querySelector('#banner'); return b.scrollHeight <= b.clientHeight + 1 })()")
        z = s.page.evaluate("['#banner', '#detail', '#stopCard'].map(s => Number(getComputedStyle(document.querySelector(s)).zIndex))")
        assert z[0] > z[1] and z[0] > z[2], z
        assert not overlap(b, rect(s, "#detail")), "the card leaves room for the banner"
        close = rect(s, "#detailClose")
        assert not overlap(b, close), (b, close)
        hit = s.page.evaluate("""() => { const r = document.querySelector('#detailClose').getBoundingClientRect();
            return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).closest('#detailClose') !== null; }""")
        assert hit, "banner covers the Close button"
        s.shot("a11y_banner_phone")


def test_phone_banner_over_stop_card_when_feed_down(root):
    with Session(root, viewport=PHONE) as s:
        s.worker.mode = "http502"
        s.open(hash_=HASH)
        s.page.wait_for_function("!document.querySelector('#banner').hidden", timeout=15000)
        s.page.wait_for_selector("#stopCard:not([hidden]) #copyStop", timeout=15000)
        txt = s.page.inner_text("#banner")
        assert txt.startswith("Live data unavailable. Couldn't reach SEPTA"), txt
        assert "Retrying automatically." in txt
        b = rect(s, "#banner")
        z = s.page.evaluate("['#banner', '#detail', '#stopCard'].map(s => Number(getComputedStyle(document.querySelector(s)).zIndex))")
        assert z[0] > z[1] and z[0] > z[2], z
        assert not overlap(b, rect(s, "#stopCard")), "the stop card sits below the banner"
        assert s.page.evaluate("(() => { const b = document.querySelector('#banner'); return b.scrollHeight <= b.clientHeight + 1 })()")
        assert s.page.evaluate("""() => { const b = document.querySelector('#banner').getBoundingClientRect();
            return !!document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2).closest('#banner'); }""")


# ------------------------------------------------------------------ 6. touch targets

def _prepare_controls(s):
    s.open()
    s.page.evaluate("""localStorage.setItem('septa.places.v1', JSON.stringify({home: {name: 'Home spot', lat: 39.95, lng: -75.16}, list: [{id: 'p1', name: 'Work', lat: 39.96, lng: -75.17}]}));
                       localStorage.setItem('septa.routes.v1', JSON.stringify({stars: ['21', 'train:Paoli/Thorndale'], onlyMine: false}))""")
    s.open(hash_=HASH)  # same document, only the fragment differs: reload so the stored state is read
    s.page.reload()
    s.wait_live()
    s.page.wait_for_selector("#addAlert")
    s.page.click("#addAlert")
    s.page.wait_for_timeout(300)


SIZE_JS = """() => {
  const q = (sel) => [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length).map(e => { const r = e.getBoundingClientRect(); return [sel, Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10, (e.textContent || e.id || '').trim().slice(0, 20)]; });
  return [].concat(q('.btn'), q('.seg button'), q('#modes .chip'), q('#myRoutes .chip'), q('#myRoutes .chip .btn'), q('#alertMin'), q('.rule .rtog'),
    q('.rule .rrm'), q('.leaflet-bar a'), q('#radius'), q('#places .btn'), q('#addr'));
}"""


def test_touch_targets_at_least_40(root):
    for vp in (PHONE, (1280, 800)):
        with Session(root, viewport=vp) as s:
            _prepare_controls(s)
            rows = s.page.evaluate(SIZE_JS)
            kinds = {r[0] for r in rows}
            for need in (".btn", ".seg button", "#modes .chip", "#myRoutes .chip", "#alertMin", ".rule .rtog", ".rule .rrm", ".leaflet-bar a", "#radius", "#places .btn"):
                assert need in kinds, (need, kinds)
            small = [r for r in rows if r[2] < 39.5]
            assert not small, (vp, small)
            zoom = [r for r in rows if r[0] == ".leaflet-bar a"]
            assert all(r[1] >= 39.5 for r in zoom), zoom
            cb = s.page.evaluate("(() => { const r = document.querySelector('.rule .rtog input').getBoundingClientRect(); return [r.width, r.height] })()")
            assert cb[0] >= 20 and cb[1] >= 20, cb
            # whole label toggles the checkbox
            before = s.page.evaluate("document.querySelector('.rule .rtog input').checked")
            s.page.locator(".rule .rtog").click(position={"x": 4, "y": 4})
            assert s.page.evaluate("document.querySelector('.rule .rtog input').checked") != before
            sw = s.page.evaluate("[document.documentElement.scrollWidth, window.innerWidth, document.querySelector('#panel').scrollWidth, document.querySelector('#panel').clientWidth]")
            assert sw[0] <= sw[1] and sw[2] <= sw[3] + 1, (vp, sw)
            s.page.locator("#radius").scroll_into_view_if_needed()
            s.shot(f"a11y_controls_{vp[0]}")


# ------------------------------------------------------------------ 7. focus management + Escape

def _open_stop_from_vehicle(s):
    from test_stop_links import pick_vehicle, select_vehicle_with_next
    sid, nname = pick_vehicle()
    assert select_vehicle_with_next(s, nname)
    s.page.focus("#viewStop")
    s.page.keyboard.press("Enter")
    s.page.wait_for_selector("#stopCard:not([hidden]) #copyStop")
    return sid, nname


def test_view_stop_focuses_stop_card(root):
    with Session(root) as s:
        boot(s)
        sid, nname = _open_stop_from_vehicle(s)
        info = s.page.evaluate("""() => { const c = document.querySelector('#stopCard');
            return {active: document.activeElement === c, role: c.getAttribute('role'), label: c.getAttribute('aria-label'), tab: c.getAttribute('tabindex')} }""")
        assert info["active"] and info["role"] == "region" and info["tab"] == "-1", info
        assert info["label"].startswith("Stop ") and len(info["label"]) > 6, info
        assert info["label"].replace("Stop ", "", 1) in s.page.inner_text("#stopCard")
        # survives a refresh (the vehicle card is rebuilt behind it)
        for b in s.worker.data["TransitView"]["bus"]:
            b["timestamp"] = int(b["timestamp"]) + 15
        s.tick(15500)
        assert s.page.evaluate("document.activeElement.id") == "stopCard"


def test_phone_view_stop_shows_and_focuses_stop_card(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s)
        _open_stop_from_vehicle(s)
        assert s.page.evaluate("getComputedStyle(document.querySelector('#stopCard')).display") != "none"
        assert s.page.evaluate("document.activeElement.id") == "stopCard"


def test_escape_closes_stop_card_and_restores_focus(root):
    with Session(root) as s:
        boot(s)
        _open_stop_from_vehicle(s)
        # opener (the View stop button) is still in the DOM: focus returns to it
        assert s.page.evaluate("document.querySelector('#viewStop') !== null")
        s.page.keyboard.press("Escape")
        assert s.page.is_hidden("#stopCard")
        assert s.page.evaluate("document.activeElement.id") == "viewStop"
        assert not s.page.is_hidden("#detail"), "Escape in the stop card must not also close the vehicle card"
        assert s.page.evaluate("location.hash") == ""
    with Session(root) as s:
        boot(s)
        _open_stop_from_vehicle(s)
        # the vehicle card is rebuilt on refresh (same id, new element) and focus stays in the stop card;
        # once the vehicle card is closed there is no opener left, so focus goes to the map
        for b in s.worker.data["TransitView"]["bus"]:
            b["timestamp"] = int(b["timestamp"]) + 15
        s.tick(15500)
        assert s.page.evaluate("document.activeElement.id") == "stopCard"
        s.page.evaluate("document.querySelector('#detailClose').click()")
        assert s.page.evaluate("document.activeElement.id") == "stopCard"
        s.page.keyboard.press("Escape")
        assert s.page.is_hidden("#stopCard")
        assert s.page.evaluate("document.activeElement === document.querySelector('#map')")


def test_escape_closes_only_one_thing(root):
    with Session(root) as s:
        boot(s)
        _open_stop_from_vehicle(s)
        # focus on the page body (not in the stop card): the vehicle card closes first, the stop card stays
        s.page.evaluate("document.activeElement.blur()")
        s.page.keyboard.press("Escape")
        assert s.page.is_hidden("#detail") and not s.page.is_hidden("#stopCard")
        s.page.keyboard.press("Escape")
        assert s.page.is_hidden("#stopCard")


def test_focus_stays_on_close_across_refresh(root):
    with Session(root) as s:
        boot(s)
        s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].focus()")
        s.page.keyboard.press("Enter")
        s.page.focus("#detailClose")
        for b in s.worker.data["TransitView"]["bus"]:
            b["timestamp"] = int(b["timestamp"]) + 15
        s.tick(15500)
        assert s.page.evaluate("document.activeElement.id") == "detailClose"
        s.page.keyboard.press("Enter")
        assert s.page.is_hidden("#detail")
        assert s.page.evaluate("document.activeElement.classList.contains('veh-wrap')"), "focus should return to the marker"


# ------------------------------------------------------------------ 8. empty card vs zoom control

def test_phone_empty_card_clear_of_zoom_buttons(root):
    with Session(root, viewport=PHONE) as s:
        boot(s)
        for m in ("bus", "trolley", "subway", "train"):
            s.page.evaluate(f"document.querySelector('input[data-mode={m}]').click()")
        s.page.wait_for_selector("#empty:not([hidden])")
        e = rect(s, "#empty")
        z = rect(s, ".leaflet-control-zoom")
        assert not overlap(e, z), (e, z)
        assert e["l"] >= 0 and e["r"] <= 360
        assert s.page.evaluate("""() => { const r = document.querySelector('.leaflet-control-zoom-in').getBoundingClientRect();
            return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).closest('.leaflet-control-zoom') !== null }""")
        s.shot("a11y_empty_phone")


# ------------------------------------------------------------------ 9. badge contrast

CONTRAST_JS = """() => {
  const lum = (rgb) => { const c = rgb.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => v / 255).map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
  const out = {};
  for (const cls of ['dr', 'dr none']) {
    const w = document.createElement('div'); w.className = 'veh-wrap'; const d = document.createElement('span'); d.className = cls; d.textContent = 'N'; w.appendChild(d); document.body.appendChild(w);
    const cs = getComputedStyle(d), a = lum(cs.color), b = lum(cs.backgroundColor);
    out[cls] = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); w.remove();
  }
  return out;
}"""


def test_direction_badge_contrast_aa_light_and_dark(root):
    for scheme in ("light", "dark"):
        with Session(root) as s:
            s.page.emulate_media(color_scheme=scheme)
            boot(s)
            r = s.page.evaluate(CONTRAST_JS)
            assert all(v >= 4.5 for v in r.values()), (scheme, r)


# ------------------------------------------------------------------ 10. one clearSelection()

def test_single_clear_selection_and_all_paths_work(root):
    src = (s_root := __import__("pathlib").Path(root) / "index.html").read_text()
    assert len(re.findall(r"function clearSelection\s*\(", src)) == 1
    script = src[src.index("<script>\n(function"):]
    assert max(len(l) for l in script.splitlines()) < 400
    assert len(re.findall(r"classList\.remove\('sel'\)", script)) == 1, "selection cleanup must live only in clearSelection()"
    with Session(root) as s:
        boot(s)
        # Close button
        click_marker(s, 0)
        assert s.page.evaluate("!!document.querySelector('.veh-wrap.sel')")
        s.page.click("#detailClose")
        assert s.page.is_hidden("#detail") and s.page.evaluate("!document.querySelector('.veh-wrap.sel')")
        # Escape
        click_marker(s, 0)
        s.page.keyboard.press("Escape")
        assert s.page.is_hidden("#detail") and s.page.evaluate("!document.querySelector('.veh-wrap.sel')")
        # click on the empty map
        click_marker(s, 0)
        mp = rect(s, "#map")
        s.page.evaluate("""() => { const m = document.querySelector('#map'); const r = m.getBoundingClientRect();
            const ev = (t) => new MouseEvent(t, {bubbles: true, clientX: r.left + 3, clientY: r.top + 3, view: window}); const tgt = document.elementFromPoint(r.left + 3, r.top + 3);
            tgt.dispatchEvent(ev('mousedown')); tgt.dispatchEvent(ev('mouseup')); tgt.dispatchEvent(ev('click')); }""")
        assert s.page.is_hidden("#detail") and s.page.evaluate("!document.querySelector('.veh-wrap.sel')")
