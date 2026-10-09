"""WP-H1: rider-facing wording. Key strings, the plain-language rule (no jargon in anything a rider sees or hears in the main
states), error wiring (aria-invalid) and vehicle marker names. Hermetic, like the other browser tests."""
import copy
import pathlib
import re

from harness import Session

import test_idle_pause as ip
import test_stop_board as sb
import test_trip_ui as tu

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_index_html_wording_and_no_jargon",
    "test_status_line_and_failure_banners",
    "test_search_and_trip_errors_set_aria_invalid",
    "test_marker_names_carry_direction_letter_and_stale",
}

HOOK = "window.__SEPTA_TEST__ = true"
# Words a rider should never read or hear. (The "Privacy details" disclosure keeps its precise technical wording on purpose.)
BANNED = [r"\bproxy\b", r"\bAPI\b", r"\bstale\b", r"GPS fix", r"\bETA\b", r"search point", r"map cent(?:er|re)", r"\bWorker\b", r"\bghost", r"\bfeed\b"]
VISIBLE_JS = """() => {
    const out = [document.body.innerText];
    document.querySelectorAll('[aria-label],[placeholder],[title]').forEach(e => {
        if (e.closest('.veh-wrap')) return;  // marker names are checked on their own (they must say "stale")
        out.push(e.getAttribute('aria-label') || '', e.getAttribute('placeholder') || '', e.getAttribute('title') || '');
    });
    return out.join('\\n');
}"""


def no_jargon(text, where):
    for pat in BANNED:
        m = re.search(pat, text, re.I)
        assert not m, f"{where}: banned word {m.group(0)!r} in: ...{text[max(0, m.start() - 60):m.end() + 60]!r}"


def rider_html(root):
    """index.html as a rider meets it: no head, scripts or styles; the privacy details body is excluded."""
    html = (pathlib.Path(root) / "index.html").read_text()
    html = re.sub(r"<head>.*?</head>|<script.*?</script>|<style.*?</style>|<details.*?</details>", " ", html, flags=re.S)
    return html


def test_index_html_wording_and_no_jargon(root):
    html = (pathlib.Path(root) / "index.html").read_text()
    for part in (
        "Suggestions by <a", "map data <a", "Privacy details</a>", '<summary>Privacy details</summary>', 'aria-label="Street address or intersection"',
        ">Use Home</button>", ">Set as Home</button>", ">Near here</button>", ">All of SEPTA</button>",
        "Tap a stop on the map, then tap Add alert.",
        "Walking, Indego, one bus or trolley, or driving. No subway, Regional Rank or transfers yet.".replace("Rank", "Rail"),
        "Positions from SEPTA's data, refreshed about every 15 seconds.",
        "When you type an address, the text and your approximate area (within about 1 km) are sent to Photon, a free place-search service, to suggest places.",
        "An address you type and submit in the main search box that you did not pick from the suggestions is sent to Nominatim (OpenStreetMap's address search) for exact matches and intersections.",
        "When you plan a trip, the start and end points (within about 10 m, or closer if our server cannot be reached) are sent to our server and the free OpenStreetMap routing service.",
        "Your saved places, settings, alerts and one backup copy of any damaged saved data are kept only in this browser's storage.",
        "Part of Septer didn't load. Check your connection and reload the page.",
    ):
        assert part in html, part
    for gone in ("Nothing is stored in this page", "Make Home", "Save as Home", "Near this search", "Whole system", "Suggestions: "):
        assert gone not in html, gone
    assert html.count('class="empty-line tp-priv"') == 1 and html.count("<details") == 1, "the long privacy text appears once"
    assert html.index('id="privacyDetails"') > html.index('id="h-alerts"'), "privacy sits at the end of the panel"
    visible = re.sub(r"<[^>]+>", " ", rider_html(root))
    attrs = " ".join(re.findall(r'(?:aria-label|placeholder|title)="([^"]*)"', rider_html(root)))
    no_jargon(visible + " " + attrs, "index.html")
    assert not re.search(r"\.js\b", visible + attrs), "no file names in rider text"
    readme = (pathlib.Path(root) / "README.md").read_text()
    assert readme.index("Septer shows where") < readme.index("is the new name of this project")


def banner(s):
    return s.page.inner_text("#banner") if s.page.is_visible("#banner") else ""


def run_until(s, cond_js, step_ms=16000, tries=8):
    for _ in range(tries):
        if s.page.evaluate(cond_js):
            return
        s.tick(step_ms)
    assert s.page.evaluate(cond_js), s.page.inner_text("#statusText")


def test_status_line_and_failure_banners(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        s.wait_live()
        assert re.fullmatch(r"Live · updated \d+ s ago · \d+ vehicles? shown", s.page.inner_text("#statusText")), s.page.inner_text("#statusText")
        no_jargon(s.page.evaluate(VISIBLE_JS), "live")
        # one source (buses) goes down while Regional Rail stays up: older positions first, then unavailable
        s.worker.data.pop("TransitView")
        run_until(s, "document.querySelector('#dot').className.includes('stale')")
        assert re.fullmatch(r"Delayed · last update \d+ s ago", s.page.inner_text("#statusText")), s.page.inner_text("#statusText")
        assert s.page.inner_text("#statusLive") == "Delayed, showing older positions"
        assert banner(s) == "Showing older positions for buses, trolleys and subway. The latest update failed. Dimmed markers disappear after 2 minutes.", banner(s)
        no_jargon(s.page.evaluate(VISIBLE_JS), "older positions")
        run_until(s, "/unavailable/.test(document.querySelector('#banner').textContent)", step_ms=30000, tries=12)
        assert banner(s) == "Bus, trolley and subway positions are unavailable. No update for over 2 minutes.", banner(s)
        assert re.fullmatch(r"Some data missing · \d+ shown", s.page.inner_text("#statusText")), s.page.inner_text("#statusText")
        no_jargon(s.page.evaluate(VISIBLE_JS), "one source down")
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        s.wait_live()
        s.worker.mode = "http502"
        run_until(s, "document.querySelector('#dot').className.includes('err')", step_ms=30000, tries=12)
        assert banner(s) == "Live data unavailable. We can't reach SEPTA right now, so no vehicles are shown. We'll keep trying.", banner(s)
        assert s.page.inner_text("#statusLive") == "Live data unavailable"
        no_jargon(s.page.evaluate(VISIBLE_JS), "all down")


def test_search_and_trip_errors_set_aria_invalid(root):
    with tu.session() as s:
        tu.boot(s)
        attr = lambda sel, a: s.page.get_attribute(sel, a)
        assert attr("#addr", "aria-invalid") is None
        s.page.click("#btnSearch")  # empty search
        assert attr("#addr", "aria-invalid") == "true" and attr("#addr", "aria-describedby") == "note"
        assert s.page.inner_text("#note")
        s.page.fill("#addr", "x")
        s.page.dispatch_event("#addr", "input")
        assert attr("#addr", "aria-invalid") is None and attr("#addr", "aria-describedby") is None
        # trip: empty destination, then an address nobody knows
        s.page.fill("#tripFrom", "Origin St")
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripToErr:not([hidden])")
        assert s.page.inner_text("#tripToErr") == "Enter where you're going."
        assert attr("#tripTo", "aria-invalid") == "true" and attr("#tripTo", "aria-describedby") == "tripToErr"
        s.page.fill("#tripTo", "Nowhere")
        assert attr("#tripTo", "aria-invalid") is None and attr("#tripTo", "aria-describedby") is None
        s.page.click("#tripGo")
        s.page.wait_for_selector("#tripToErr:not([hidden])")
        assert s.page.inner_text("#tripToErr") == "Couldn't find that address. Add a cross street or ZIP code."
        assert attr("#tripTo", "aria-invalid") == "true" and attr("#tripTo", "aria-describedby") == "tripToErr"
        s.page.fill("#tripTo", "Dest")
        assert attr("#tripTo", "aria-invalid") is None


def test_marker_names_carry_direction_letter_and_stale(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        s.wait_live()
        marks = s.page.evaluate("""() => [...document.querySelectorAll('.veh-wrap')].map(e =>
            ({label: e.getAttribute('aria-label'), letter: e.querySelector('.dr').textContent, train: e.classList.contains('k-train')}))""")
        words = {"N": "northbound", "E": "eastbound", "S": "southbound", "W": "westbound"}
        checked = 0
        for m in marks:
            assert "stale" not in m["label"], m
            if not m["train"] and m["letter"] in words:
                assert f", {m['letter']}, " in m["label"] and words[m["letter"]] not in m["label"], m
                checked += 1
        assert checked >= 2, marks
        assert s.page.evaluate("window.__SEPTA_TEST__.vehLabel({kind: 'bus', badge: '12', dir: 'W', late: 5})") == "Route 12 bus, W, 5 min late"
        assert s.page.evaluate("window.__SEPTA_TEST__.vehLabel({kind: 'bus', badge: '12', dir: 'W', late: 5}, true)") == "Route 12 bus, westbound, 5 min late"  # the one-off announcement
        s.worker.data.pop("TransitView")
        run_until(s, "document.querySelectorAll('.veh-wrap.stale').length > 0")
        stale = s.page.evaluate("[...document.querySelectorAll('.veh-wrap.stale')].map(e => e.getAttribute('aria-label'))")
        assert stale and all(x.endswith(", position may be out of date") and "stale" not in x for x in stale), stale


def test_stop_card_alert_row_and_vehicle_card_wording(root):
    with Session(root, init_scripts=[HOOK]) as s:
        sb.open_board(s)
        s.page.wait_for_selector("#addAlert")
        assert s.page.get_attribute("#stopClose", "aria-label") == "Close stop details"
        assert s.page.get_attribute("#alertMin", "aria-label") == "Alert when the bus is this many minutes away"
        assert "Estimates from the bus's distance and speed, not official SEPTA predictions." in sb.board(s)
        s.page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('no'))}})")
        s.page.click("#copyStop")
        s.page.wait_for_selector("#stopUrl")
        assert s.page.get_attribute("#stopUrl", "aria-label") == "Link to this stop"
        s.page.click("#addAlert")
        assert s.page.inner_text("#alertLive").endswith("Keep this page open with the screen on. You will see an alert here.")
        name = s.page.get_attribute("#rules .rtoggle", "aria-label")
        assert name.startswith("Alert on: route 21 at "), name
        assert s.page.get_attribute("#rules .rrm", "aria-label").startswith("Remove alert for route 21 at ")
        no_jargon(s.page.evaluate(VISIBLE_JS), "stop card and alert row")
        # Home wording
        s.page.evaluate("document.querySelector('#placeName').value = 'Test'")
        s.page.evaluate("window.SEPTA.panel.setCenter({lat: 39.95, lng: -75.16, label: 'Test spot'}, false)")
        s.page.click("#btnSave")
        assert s.page.inner_text("#places li button.ghost") .startswith("Set as Home"), s.page.inner_text("#places")


def test_notification_and_idle_wording(root):
    script = """(function () { var perm = window.__perm || 'default';
        function N() {} Object.defineProperty(N, 'permission', { get: function () { return perm; } });
        N.requestPermission = function (cb) { perm = 'denied'; if (cb) cb(perm); return Promise.resolve(perm); };
        window.Notification = N; })();"""
    with Session(root, init_scripts=[HOOK, script]) as s:
        s.open()
        s.wait_live()
        assert s.page.inner_text("#enableNotify") == "Get alerts in the background"
        s.page.click("#enableNotify")
        assert s.page.inner_text("#notifyBox") == "Notifications are blocked. Allow them for this site in your browser settings."
        assert s.page.inner_text("#rulesEmpty") == "Tap a stop on the map, then tap Add alert."
        ip.jump(s, 61)
        assert s.page.inner_text("#idleMsg").startswith("Paused after an hour of no activity. Tap Resume to keep tracking."), s.page.inner_text("#idleMsg")
        no_jargon(s.page.evaluate(VISIBLE_JS), "idle")


def test_empty_state_and_vehicle_card_wording(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.worker.data["TransitView"] = {"bus": []}
        s.worker.data["TrainView"] = []
        s.open()
        s.page.wait_for_selector("#empty:not([hidden])")
        assert "No vehicles reporting within" in s.page.inner_text("#empty") and "of here right now." in s.page.inner_text("#empty")
        no_jargon(s.page.evaluate(VISIBLE_JS), "empty state")
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        s.wait_live()
        s.page.locator(".veh-wrap:not(.k-train)").first.click(force=True)
        s.page.wait_for_selector("#detail:not([hidden])")
        pos = s.page.inner_text("#detail")
        assert re.search(r"Position\s*Position updated \d+ s ago", pos), pos
        no_jargon(s.page.evaluate(VISIBLE_JS), "vehicle card")


def test_trip_results_wording_and_order(root):
    with tu.session() as s:
        tu.boot(s)
        tu.plan_ui(s)
        text = s.page.inner_text("#tripResults") + "\n" + s.page.evaluate("[...document.querySelectorAll('#tripResults .tp-steps')].map(e => e.textContent).join('\\n')")
        no_jargon(text, "trip results")
        top = s.page.inner_text("#tripResults .tp-top")
        assert re.fullmatch(r"Fastest without a car: (walk|bike|bus|bike and bus), \d+ min", top), top
        assert "trolley" not in top
        order = s.page.evaluate("[...document.querySelectorAll('#tripList .tp-card')].map(b => b.querySelector('.tp-badge.drive') ? 'car' : 'other')")
        assert order.count("car") == 1 and order[-1] == "car", order
        assert s.page.inner_text("#tripResults .tp-badge.drive") == "By car"
        assert s.page.inner_text("#tripScope") == "Walking, Indego, one bus or trolley, or driving. No subway, Regional Rail or transfers yet."
        steps = s.page.evaluate("[...document.querySelectorAll('#tripResults .tp-sub')].map(e => e.textContent)")
        waits = [x for x in steps if x.startswith("Wait:")]
        assert all(re.fullmatch(r"Wait: (about \d+|under 1) min \((typical, no bus tracked|next bus tracked live)\)", w) for w in waits), waits
        assert all(re.fullmatch(r"Ride: \d+ min \(scheduled\)", x) for x in steps if x.startswith("Ride:")), steps
    # a trolley pattern is called a trolley in the summary line, not a bus
    net = copy.deepcopy(tu.NET)
    for p in net["patterns"]:
        p["kind"] = "trolley"
    with tu.session() as s:
        tu.boot(s, net=net)
        tu.plan_ui(s)
        top = s.page.inner_text("#tripResults .tp-top")
        assert re.fullmatch(r"Fastest without a car: (bike and )?trolley, \d+ min", top), top
        assert "Trolley X47" in s.page.inner_text("#tripResults .tp-l2 >> nth=0") or "Trolley X47" in s.page.inner_text("#tripResults"), top
