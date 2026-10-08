"""Idle pause: after an hour without a real interaction the page makes no requests until the user comes back."""
import json

from harness import Session

MIN = 60000
RULE = {"rules": [{"id": "r1", "route": "21", "stopId": "14880", "stopName": "Test stop", "lat": 39.95, "lng": -75.17,
                   "minutes": 2, "enabled": True, "last": None}]}
STOP_HASH = "#stop=14880&route=21"


def adv(s, minutes, chunk=5):
    """Advance the fake clock by `minutes` in chunks of at most `chunk` minutes."""
    left = minutes
    while left > 0:
        n = min(chunk, left)
        s.tick(n * MIN)
        left -= n


def jump(s, minutes):
    """Skip the clock ahead in one step (timers fire once, not 240 times), then let one 15 s tick run."""
    s.page.clock.fast_forward(minutes * MIN)
    s.tick(15000)


def window_hits(s, minutes):
    """Requests seen while advancing `minutes` more."""
    s.worker.hits.clear()
    adv(s, minutes, chunk=1)
    return list(s.worker.hits)


def notice_visible(s):
    return s.page.locator("#idleBar").is_visible()


def status(s):
    return s.page.inner_text("#statusText")


def boot(s, hash_=""):
    s.open(hash_=hash_)
    s.wait_live()


def paused_session(s, hash_=""):
    boot(s, hash_)
    jump(s, 61)
    assert notice_visible(s)


def test_a_no_requests_after_an_hour_idle(root):
    with Session(root) as s:
        boot(s)
        jump(s, 61)
        assert window_hits(s, 2) == []
        assert notice_visible(s)
        assert "Paused" in status(s), status(s)
        assert "Paused to save requests after an hour without use. Tap anywhere or press Resume to continue." in s.page.inner_text("#idleBar")
        assert "Leave-now" not in s.page.inner_text("#idleBar")
        assert s.page.inner_text("#resumeBtn") == "Resume"
        assert s.page.evaluate("document.querySelector('#statusLive').textContent") == "Paused"
        assert s.page.evaluate("!document.querySelector('#idleBar').closest('[aria-live],[role=alert],[role=status]') && !document.querySelector('#idleBar').getAttribute('aria-live')")
        assert not s.console_errors, s.console_errors


def test_b_interaction_postpones_pause(root):
    with Session(root) as s:
        boot(s)
        adv(s, 58)
        assert len(window_hits(s, 1)) >= 3, "requests continue before the hour is up"
        assert not notice_visible(s)
        s.page.mouse.move(700, 780)
        s.page.mouse.down()
        s.page.mouse.up()
        adv(s, 41)  # minute 100
        assert len(window_hits(s, 1)) >= 3, "still requesting at minute 100"
        assert not notice_visible(s)
        adv(s, 17)  # minute 118, one minute short of 59 + 60
        assert not notice_visible(s)
        adv(s, 3)  # past minute 119
        assert notice_visible(s) and window_hits(s, 2) == []


def test_c_resume_button_clears_notice_and_refetches(root):
    with Session(root) as s:
        paused_session(s)
        s.worker.hits.clear()
        s.page.click("#resumeBtn")
        s.tick(1000)
        assert not notice_visible(s)
        assert "TransitView" in s.worker.hits and "Alerts" in s.worker.hits, s.worker.hits
        assert "Paused" not in status(s)
        n = len(window_hits(s, 2))
        assert n >= 4, "normal cadence continues after resume"


def test_d_keydown_resumes_and_enter_on_button_works(root):
    with Session(root) as s:
        paused_session(s)
        s.worker.hits.clear()
        s.page.keyboard.press("Shift")
        s.tick(1000)
        assert not notice_visible(s) and "TransitView" in s.worker.hits
    with Session(root) as s:
        paused_session(s)
        s.page.focus("#resumeBtn")
        s.worker.hits.clear()
        s.page.keyboard.press("Enter")
        s.tick(1000)
        assert not notice_visible(s) and "TransitView" in s.worker.hits


def test_e_returning_to_visible_tab_resumes(root):
    with Session(root) as s:
        paused_session(s)
        s.worker.hits.clear()
        s.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        s.tick(1000)
        assert not notice_visible(s) and "TransitView" in s.worker.hits, s.worker.hits


def test_f_leave_now_alerts_paused_too(root):
    seed = f"try {{ localStorage.setItem('septa.rules.v1', {json.dumps(json.dumps(RULE))}); }} catch (e) {{}}"
    with Session(root, init_scripts=[seed]) as s:
        boot(s)
        assert s.page.locator("#rules li").count() == 1
        jump(s, 61)
        assert notice_visible(s)
        assert "Leave-now alerts are paused as well." in s.page.inner_text("#idleBar")
        assert window_hits(s, 5) == [], "even with an enabled rule nothing is requested while paused"
        assert s.page.locator("#toasts .toast").count() == 0
        assert json.loads(s.page.evaluate("localStorage.getItem('septa.rules.v1')"))["rules"][0]["last"] is None
        assert not s.console_errors, s.console_errors


def test_g_phone_layout_with_notice(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s)
        s.page.evaluate("document.querySelector('.veh-wrap').click()")
        s.tick(500)
        assert s.page.locator("#detail").is_visible()
        jump(s, 61)
        assert notice_visible(s)
        assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth")
        bar = s.page.locator("#idleBar").bounding_box()
        card = s.page.locator("#detail").bounding_box()
        assert bar["y"] + bar["height"] <= card["y"] + 0.5, (bar, card)
        assert bar["x"] >= 0 and bar["x"] + bar["width"] <= 390
    with Session(root, viewport=(390, 844)) as s:
        boot(s, STOP_HASH)
        s.page.wait_for_selector("#stopCard:not([hidden])")
        jump(s, 61)
        assert notice_visible(s) and s.page.locator("#stopCard").is_visible()
        bar = s.page.locator("#idleBar").bounding_box()
        card = s.page.locator("#stopCard").bounding_box()
        assert bar["y"] + bar["height"] <= card["y"] + 0.5, (bar, card)
        assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_h_paused_and_resumed_have_no_console_errors(root):
    with Session(root) as s:
        paused_session(s)
        adv(s, 5)  # lets the data age out and apply() redraw while paused
        assert s.markers() == 0
        assert not s.page.locator("#empty").is_visible()
        s.page.click("#resumeBtn")
        s.tick(1000)
        assert s.markers() > 0
        assert not s.console_errors, s.console_errors
        assert not s.unexpected and not s.septa_direct
