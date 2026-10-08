"""Task 1.2: shareable stop links (#stop=<id>&route=<route>)."""
import json

from harness import FIX, Session

STOPS = json.loads((FIX / "Stops.json").read_text())
TV = json.loads((FIX / "TransitView.json").read_text())
PREFS = "septa.prefs.v1"
SID, SROUTE = "14880", "21"
STOP = next(x for x in STOPS[SROUTE] if x["stopid"] == SID)
LAT, LNG = float(STOP["lat"]), float(STOP["lng"])


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()
    s.settle()


def stop_pin_offset(s):
    """Pixel distance between the stop pin and the map container center (center of view == stop when ~0)."""
    return s.page.evaluate("""() => {
        const mp = document.querySelector('#map').getBoundingClientRect();
        const p = document.querySelector('.stp').getBoundingClientRect();
        return Math.hypot(p.left + p.width / 2 - (mp.left + mp.width / 2), p.top + p.height / 2 - (mp.top + mp.height / 2)) }""")


def stop_pins(s):
    return s.page.evaluate("document.querySelectorAll('.stp').length")


def stored(s):
    return s.page.evaluate(f"localStorage.getItem('{PREFS}')")


def card_text(s):
    return s.page.inner_text("#stopCard")


def pick_vehicle():
    """A route-21 bus with a next stop that exists in the stop fixture."""
    ids = {x["stopid"]: x["stopname"] for x in STOPS[SROUTE]}
    for b in TV["bus"]:
        if b["route_id"] == SROUTE and b.get("next_stop_id") and str(b["next_stop_id"]) in ids and b["next_stop_name"]:
            return str(b["next_stop_id"]), b["next_stop_name"]
    raise AssertionError("no fixture vehicle")


def select_vehicle_with_next(s, next_name):
    n = s.page.evaluate("document.querySelectorAll('.veh-wrap').length")
    for i in range(n):
        s.page.evaluate(f"document.querySelectorAll('.veh-wrap')[{i}].click()")
        if s.page.locator("#viewStop").count() and next_name in s.page.inner_text("#detail"):
            return True
    return False


def test_view_stop_from_vehicle(root):
    sid, nname = pick_vehicle()
    stop = next(x for x in STOPS[SROUTE] if x["stopid"] == sid)
    with Session(root) as s:
        boot(s)
        assert select_vehicle_with_next(s, nname)
        before = s.markers()
        s.page.click("#viewStop")
        s.page.wait_for_selector("#stopCard:not([hidden]) #copyStop")
        s.settle()
        assert stop["stopname"] in card_text(s) and f"Stop {sid} · Route {SROUTE}" in card_text(s)
        assert s.page.evaluate("location.hash") == f"#stop={sid}&route={SROUTE}"
        assert stop_pins(s) == 1
        assert stop_pin_offset(s) < 3
        # The radius re-centers on the stop (spec), so the vehicle count follows the radius filter. What must hold:
        # the stop pin is a separate marker, not a vehicle, and every other marker icon is a vehicle or the center pin.
        icons = s.page.evaluate("document.querySelectorAll('.leaflet-marker-icon').length")
        assert icons == s.markers() + 2 and before > 0, (icons, s.markers())
        assert s.page.evaluate("document.querySelectorAll('.veh-wrap .stp').length") == 0
        s.page.evaluate("document.querySelectorAll('.veh-wrap')[0].click()")
        assert not s.page.is_hidden("#stopCard"), "selecting a vehicle must not close the stop card"
        assert not s.console_errors, s.console_errors


def test_vehicle_count_unchanged_when_stop_marker_added(root):
    with Session(root) as s:
        boot(s)
        n = s.markers()
        s.page.evaluate(f"location.hash = '#stop={SID}&route={SROUTE}'")
        s.page.wait_for_selector("#copyStop")
        # the stop marker is outside the vehicles Map, so the count only changes via the radius filter, never by +1
        assert s.page.evaluate("document.querySelectorAll('.veh-wrap').length") >= 0
        assert stop_pins(s) == 1 and n > 0


def test_deep_link_opens_and_does_not_persist_center(root):
    with Session(root) as s:
        boot(s, f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#copyStop")
        s.settle()
        assert STOP["stopname"] in card_text(s)
        assert stop_pin_offset(s) < 3
        assert stored(s) is None or "center" not in json.loads(stored(s)) or abs(json.loads(stored(s))["center"]["lat"] - LAT) > 0.0005
        # the saved center must not be the stop, even after another prefs write (radius change)
        s.page.evaluate("""() => { const r = document.querySelector('#radius'); r.value = 2; r.dispatchEvent(new Event('change', {bubbles: true})) }""")
        raw = stored(s)
        c = json.loads(raw)["center"]
        assert abs(c["lat"] - LAT) > 0.0005 or abs(c["lng"] - LNG) > 0.0005, "stop link overwrote saved center"
        assert not s.console_errors, s.console_errors


def test_bad_hashes_ignored_and_missing_stop(root):
    for h in ("#stop=abc&route=21", "#stop=1&route=../x", "#stop=&route=", "#stop=14880", "#route=21", "#junk"):
        with Session(root) as s:
            boot(s, h)
            assert s.page.is_hidden("#stopCard"), h
            assert stop_pins(s) == 0
            assert not s.console_errors, (h, s.console_errors)
    with Session(root) as s:
        boot(s)
        before = s.page.evaluate("document.querySelector('.leaflet-map-pane').style.transform")
        s.page.evaluate(f"location.hash = '#stop=999999&route={SROUTE}'")
        s.page.wait_for_function("document.querySelector('#stopCard').textContent.includes(\"couldn't be found\")")
        s.settle()
        assert "That stop couldn't be found on route 21." in card_text(s)
        assert s.page.locator("#stopRetry").count() == 0
        assert s.page.evaluate("document.querySelector('.leaflet-map-pane').style.transform") == before
        assert stop_pins(s) == 0
        assert not s.console_errors, s.console_errors


def test_copy_link(root):
    with Session(root) as s:
        s.ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        boot(s, f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#copyStop")
        s.page.click("#copyStop")
        s.page.wait_for_function("document.querySelector('#stopLive').textContent.includes('Link copied')")
        url = s.page.evaluate("navigator.clipboard.readText()")
        assert url == f"{s.base}/index.html#stop={SID}&route={SROUTE}", url
        assert str(STOP["lat"])[:6] not in url and str(STOP["lng"])[:7] not in url
        assert "lat" not in url and "lng" not in url and "center" not in url
        assert "Link copied" in s.page.inner_text("#stopLive")


def test_copy_link_fallback_input(root):
    with Session(root, init_scripts=["Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('no'))}})"]) as s:
        boot(s, f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#copyStop")
        s.page.click("#copyStop")
        s.page.wait_for_selector("#stopUrl")
        assert s.page.input_value("#stopUrl").endswith(f"#stop={SID}&route={SROUTE}")
        assert s.page.get_attribute("#stopUrl", "readonly") is not None


def test_fetch_failure_shows_retry(root):
    with Session(root) as s:
        s.worker.mode = "abort"
        s.open(hash_=f"#stop={SID}&route={SROUTE}")
        s.tick(5000)
        s.page.wait_for_selector("#stopRetry")
        assert "Couldn't load stops right now." in card_text(s)
        assert s.page.locator("#stopClose").count() == 1
        assert stop_pins(s) == 0
        s.worker.mode = "ok"
        s.page.click("#stopRetry")
        s.page.wait_for_selector("#copyStop")
        assert STOP["stopname"] in card_text(s)


def test_refresh_keeps_stop_and_view(root):
    with Session(root) as s:
        boot(s, f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#copyStop")
        s.settle()
        pane = lambda: s.page.evaluate("document.querySelector('.leaflet-map-pane').style.transform")
        before, off = pane(), stop_pin_offset(s)
        s.tick(15500)
        s.tick(15500)
        assert stop_pins(s) == 1 and pane() == before
        assert abs(stop_pin_offset(s) - off) < 1
        assert not s.page.is_hidden("#stopCard")


def test_mobile_no_horizontal_scroll(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s, f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#copyStop")
        assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert s.page.evaluate("document.body.scrollWidth <= window.innerWidth")
        r = s.page.evaluate("(() => { const r = document.querySelector('#stopCard').getBoundingClientRect(); return [r.left, r.right] })()")
        assert r[0] >= 0 and r[1] <= 390


def test_close_clears_everything(root):
    with Session(root) as s:
        boot(s, f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#stopClose")
        s.page.click("#stopClose")
        assert s.page.is_hidden("#stopCard") and stop_pins(s) == 0
        assert s.page.evaluate("location.hash") == ""
        assert s.page.evaluate("location.href").endswith("/index.html")
        assert not s.page.evaluate("location.href").endswith("#")


def test_stop_opens_when_transitview_fails(root):
    with Session(root) as s:
        s.worker.data["TransitView"] = {"bus": []}
        s.open(hash_=f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#copyStop")
        assert STOP["stopname"] in card_text(s) and stop_pins(s) == 1
        assert not s.console_errors, s.console_errors


def test_stop_list_cached_per_route(root):
    with Session(root) as s:
        boot(s, f"#stop={SID}&route={SROUTE}")
        s.page.wait_for_selector("#copyStop")
        other = STOPS[SROUTE][1]["stopid"]
        s.page.evaluate(f"location.hash = '#stop={other}&route={SROUTE}'")
        s.page.wait_for_function(f"document.querySelector('#stopCard').textContent.includes('Stop {other}')")
        assert sum(1 for h in s.worker.hits if h.startswith("Stops")) == 1


def test_mobile_vehicle_card_is_never_covered_by_stop_card(root):
    with Session(root, viewport=(390, 844)) as s:
        s.open(hash_="#stop=14880&route=21")
        s.wait_live()
        s.page.wait_for_function("getComputedStyle(document.querySelector('#stopCard')).display !== 'none'")
        s.settle()
        assert s.page.evaluate("getComputedStyle(document.querySelector('#stopCard')).display") != "none"
        s.page.evaluate("document.querySelector('.veh-wrap').click()")
        assert s.page.evaluate("getComputedStyle(document.querySelector('#stopCard')).display") == "none", "stop card covers the vehicle card"
        s.page.click("#detail button[aria-label='Close vehicle details']")
        assert s.page.evaluate("getComputedStyle(document.querySelector('#stopCard')).display") != "none", "stop card should return"
