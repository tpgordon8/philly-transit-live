"""Card hierarchy (UX audit #6, #7): the stop card, the vehicle card, the Indego station card and the service alerts list. Minutes and
counts are the largest things, state is colour AND words, chrome is 44 px icon buttons with names, loading shows shimmer rows, empty
and error states say what happened and offer Retry, and cards slide up briefly unless the rider asks for reduced motion."""
import re

from harness import Session, load_fixtures
from test_first_run import must_fail
import test_indego_layer as IL
import test_stop_board as SB

FAST = {
    "test_stop_card_shows_skeleton_while_loading",
    "test_stop_card_minutes_are_the_hero_and_chrome_is_icon_buttons",
    "test_vehicle_card_next_stop_estimate_and_star_toggle",
}

HASH = SB.HASH


def px(v):
    return float(str(v).replace("px", "").strip())


def css(s, sel, prop):
    return s.page.evaluate("([sel, p]) => getComputedStyle(document.querySelector(sel)).getPropertyValue(p)", [sel, prop])


def box(s, sel):
    return s.page.evaluate("(sel) => { const r = document.querySelector(sel).getBoundingClientRect(); return {w: r.width, h: r.height}; }", sel)


def moving_board(s, hash_=HASH):
    SB.setup_moving(s)
    if hash_:
        SB.open_board(s, hash_)
    else:
        s.open()
        s.wait_live()
        s.settle()
    SB.step(s, "3678", 120)
    SB.step(s, "3678", 120)


# ---------------------------------------------------------------- stop card

def check_skeleton(root):
    with Session(root, viewport=(390, 844)) as s:
        s.page.route("**/Stops?*", lambda r: None)  # the stop list never arrives
        s.open(hash_=HASH)
        s.wait_live()
        s.page.wait_for_selector("#stopCard:not([hidden]) .sk-row", timeout=3000)
        assert s.page.locator("#stopCard .sk-row").count() == 3
        assert s.page.get_attribute("#stopCard", "aria-busy") == "true"
        assert s.page.locator("#stopCard [role=status]").inner_text() == "Loading stop details"
        assert s.page.locator("#copyStop").count() == 0 and s.page.locator("#pinBoard").count() == 0, "no actions before the stop is known"
        assert s.page.get_attribute("#stopClose", "aria-label") == "Close stop details"
        c = box(s, "#stopClose")
        assert c["w"] >= 44 and c["h"] >= 44, c
        assert css(s, "#stopCard .sk", "animation-name") == "sk-shine"
        s.page.click("#stopClose")
        assert s.page.is_hidden("#stopCard")
    with Session(root, viewport=(390, 844), reduced_motion="reduce") as s:
        s.page.route("**/Stops?*", lambda r: None)
        s.open(hash_=HASH)
        s.wait_live()
        s.page.wait_for_selector("#stopCard .sk-row", timeout=3000)
        assert css(s, "#stopCard .sk", "animation-name") == "none"
        assert css(s, "#stopCard", "animation-name") == "none"


def test_stop_card_shows_skeleton_while_loading(root):
    check_skeleton(root)
    must_fail(check_skeleton, root, ("js/stops.js", "if (!stopLists[route]) renderStopLoading();", ""))


def check_stop_hierarchy(root):
    with Session(root, viewport=(390, 844)) as s:
        moving_board(s)
        row = '#stopBoard button[data-key="b3678"]'
        hero, num, unit = f"{row} .sbeta b", f"{row} .sbeta b .n", f"{row} .sbeta b .u"
        assert re.fullmatch(r"\d+ min", s.page.inner_text(hero)), s.page.inner_text(hero)
        big, small = px(css(s, num, "font-size")), px(css(s, unit, "font-size"))
        assert big >= 26 and small <= big / 1.8, (big, small)
        assert "tabular-nums" in css(s, hero, "font-variant-numeric")
        assert s.page.inner_text(f"{row} .sbeta small") == "estimate", "the estimate is labelled"
        # the direction line and the late/on-time chip: words plus a colour class
        assert s.page.inner_text(f"{row} .sbdir")
        pill = s.page.locator(f"{row} .pill")
        assert re.search(r"(good|warn|bad|unk)", pill.get_attribute("class")) and pill.inner_text().strip()
        # chrome: icon buttons with names, 44 px; one primary action with an icon
        for sel, name in (("#copyStop", "Copy link to this stop"), ("#stopClose", "Close stop details")):
            b = box(s, sel)
            assert b["w"] >= 44 and b["h"] >= 44, (sel, b)
            assert s.page.get_attribute(sel, "aria-label") == name
            assert s.page.locator(f"{sel} svg").count() == 1 and s.page.inner_text(sel).strip() == ""
        assert "primary" in s.page.get_attribute("#pinBoard", "class") and s.page.locator("#pinBoard svg").count() == 1
        assert s.page.inner_text("#pinBoard") == "Pin to board" and box(s, "#pinBoard")["h"] >= 44
        # the title is the first bold line and the icon buttons share its row
        t, c = s.page.evaluate("""() => [document.querySelector('#stopCard b'), document.querySelector('#copyStop')].map(e => { const r = e.getBoundingClientRect(); return [r.top, r.bottom]; })""")
        assert c[0] < t[1] and t[0] < c[1], (t, c)


def test_stop_card_minutes_are_the_hero_and_chrome_is_icon_buttons(root):
    check_stop_hierarchy(root)
    must_fail(check_stop_hierarchy, root, ("css/stops.css", "#stopCard .sbeta b{font:700 30px/1", "#stopCard .sbeta b{font:700 16px/1"))


def test_stop_card_error_and_empty_states_offer_a_way_on(root):
    # the stop list fails: a plain message, a second line and a primary Retry that works
    with Session(root, viewport=(390, 844)) as s:
        state = {"fail": True}
        s.page.route("**/Stops?*", lambda r: r.abort("failed") if state["fail"] else r.fallback())
        s.open(hash_=HASH)
        s.wait_live()
        s.page.wait_for_selector("#stopRetry", timeout=8000)
        assert s.page.locator("#stopCard .sstate.bad svg").count() == 1
        assert "Couldn't load stops right now." in s.page.inner_text("#stopCard")
        assert "primary" in s.page.get_attribute("#stopRetry", "class")
        state["fail"] = False
        s.page.click("#stopRetry")
        s.page.wait_for_selector("#copyStop")
    # no bus on the route: a calm empty state, not a bare line
    with Session(root, viewport=(390, 844)) as s:
        s.worker.data["TransitView"] = {"bus": []}
        SB.open_board(s)
        st = s.page.locator("#stopBoard .sstate.calm")
        assert st.count() == 1 and "No buses on route 21 are heading to this stop right now." in st.inner_text()
        assert "This updates every 15 seconds." in st.inner_text()
    # live data down: say so plainly (the refresh loop retries on its own, with back-off)
    with Session(root, viewport=(390, 844)) as s:
        s.worker.mode = "http502"
        s.open(hash_=HASH)
        for _ in range(3):
            s.tick(2000, cap_ms=3000)
        s.page.wait_for_selector("#stopBoard .sstate.bad", timeout=15000)
        t = s.page.inner_text("#stopBoard")
        assert "Live data unavailable. No arrival times are shown." in t and "keeps trying" in t, t


# ---------------------------------------------------------------- vehicle card

def check_vehicle_card(root):
    with Session(root, viewport=(390, 844)) as s:
        moving_board(s, "")
        s.page.evaluate("window.SEPTA.map.select('b3678')")
        s.page.wait_for_selector("#detail .veta b", timeout=5000)
        assert s.page.inner_text("#detailHead").startswith("To "), "the destination leads"
        assert px(css(s, "#detailHead", "font-size")) >= 19 and px(css(s, "#detail .rbadge", "font-size")) >= 22
        assert re.fullmatch(r"\d+ min", s.page.inner_text("#detail .veta b"))
        assert px(css(s, "#detail .veta b", "font-size")) >= 26 and s.page.inner_text("#detail .veta small") == "estimate"
        assert s.page.inner_text("#detail .vstop") and s.page.locator("#viewStop").count() == 1
        star = s.page.locator("#starBtn")
        assert star.get_attribute("aria-pressed") == "false" and star.inner_text().strip() == "Star route"
        off = css(s, "#starBtn svg", "fill")
        star.click()
        star = s.page.locator("#starBtn")
        assert star.get_attribute("aria-pressed") == "true" and star.inner_text().strip() == "Starred"
        assert css(s, "#starBtn svg", "fill") != off, "the on state is visible, not only announced"
        c = box(s, "#detailClose")
        assert c["w"] >= 44 and c["h"] >= 44 and s.page.inner_text("#detailClose").strip() == ""


def test_vehicle_card_next_stop_estimate_and_star_toggle(root):
    check_vehicle_card(root)
    must_fail(check_vehicle_card, root, ("js/map.js", "var e = v.next ? nextEta(v) : null;", "var e = null;"))


def test_cards_slide_up_quickly_and_not_with_reduced_motion(root):
    for rm, want in ((None, "card-up"), ("reduce", "none")):
        with Session(root, viewport=(390, 844), reduced_motion=rm) as s:
            s.open(hash_=HASH)
            s.wait_live()
            s.page.wait_for_selector("#copyStop")
            assert css(s, "#stopCard", "animation-name") == want
            s.page.evaluate("document.querySelector('.veh-wrap').click()")
            s.page.wait_for_selector("#detail:not([hidden])")
            assert css(s, "#detail", "animation-name") == want
            if want != "none":
                assert float(css(s, "#detail", "animation-duration").rstrip("s")) <= 0.22


# ---------------------------------------------------------------- Indego card

def test_indego_card_counts_with_icons_and_status_words(root):
    with IL.start(root, vp=(390, 844)) as s:
        for st in s.mocks.stations():
            s.mocks.set_station(st["station_id"], bikes=0, docks=2)
        IL.boot(s, 15)
        IL.open_first(s)
        tiles = s.page.evaluate("""() => [...document.querySelectorAll('#indegoStats .ind-tile')].map(t => ({n: t.querySelector('b').textContent,
            cls: t.className, word: t.querySelector('.ind-ts').textContent, icon: !!t.querySelector('svg'), fs: parseFloat(getComputedStyle(t.querySelector('b')).fontSize)}))""")
        assert [t["n"] for t in tiles] == ["0", "0", "2"], tiles
        assert [t["word"] for t in tiles] == ["None", "None", "Few left"], tiles
        assert "av-none" in tiles[0]["cls"] and "av-low" in tiles[2]["cls"]
        assert all(t["icon"] and t["fs"] >= 24 for t in tiles), tiles
        assert "0 bikes, 2 open docks" in s.page.inner_text("#indegoCard"), "the sentence stays for screen readers"
        assert s.page.get_attribute("#indegoStats", "aria-hidden") == "true"
        c = box(s, "#indegoClose")
        assert c["w"] >= 44 and c["h"] >= 44 and s.page.get_attribute("#indegoClose", "aria-label") == "Close station details"


# ---------------------------------------------------------------- service alerts

def check_alerts_retry(root):
    with Session(root) as s:
        s.worker.data.pop("Alerts")  # the mock answers 502
        s.open()
        s.wait_live()
        s.tick(2000, cap_ms=3000)  # the fetch layer retries once after 1.5 s
        s.page.wait_for_selector("#alertsRetry", timeout=8000)
        assert "Alerts are unavailable right now." in s.page.inner_text("#alerts")
        s.worker.data["Alerts"] = load_fixtures()["Alerts"]
        s.page.click("#alertsRetry")
        s.tick(500)
        s.page.wait_for_selector("#alerts li.alert .top b", timeout=8000)
        first = s.page.locator("#alerts li.alert").first
        assert re.search(r"\bt-(alert|advisory|detour)\b", first.get_attribute("class"))
        assert float(first.locator(".top b").evaluate("e => parseFloat(getComputedStyle(e).fontSize)")) >= 15
        assert first.locator(".tag").inner_text().strip(), "the kind is a word, not only a colour"


def test_alerts_list_hierarchy_and_retry(root):
    check_alerts_retry(root)
    must_fail(check_alerts_retry, root, ("js/alerts.js", "li0.appendChild(rb);", ""))
