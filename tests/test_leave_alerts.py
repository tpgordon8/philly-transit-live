"""Tasks 3.1 + 3.2: client-side "Leave now" alerts (rules in localStorage, evaluated on every refresh)."""
import json
import math
import re

from harness import FIX, Session

STOPS = json.loads((FIX / "Stops.json").read_text())
SID, SROUTE = "14880", "21"
STOP = next(x for x in STOPS[SROUTE] if x["stopid"] == SID)
SNAME = STOP["stopname"]
SLAT, SLNG = float(STOP["lat"]), float(STOP["lng"])
HASH = f"#stop={SID}&route={SROUTE}"
KEY = "septa.rules.v1"
HOOK = "window.__SEPTA_TEST__ = true"
MLAT = 111195.0

NOTIF = """(function () {
  var perm = 'default';
  window.__notes = []; window.__permCalls = 0; window.__nextPerm = 'granted';
  function N(t, o) { window.__notes.push({ t: t, o: o || null }); }
  Object.defineProperty(N, 'permission', { get: function () { return perm; } });
  N.requestPermission = function (cb) { window.__permCalls++; perm = window.__nextPerm; if (cb) cb(perm); return Promise.resolve(perm); };
  window.Notification = N;
  window.__setPerm = function (p) { perm = p; };
})();"""
HIDDEN = """(function () {
  window.__hidden = false;
  Object.defineProperty(document, 'hidden', { configurable: true, get: function () { return window.__hidden; } });
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: function () { return window.__hidden ? 'hidden' : 'visible'; } });
})();"""


def mlng(lat):
    return MLAT * math.cos(math.radians(lat))


def offset(bearing_deg, meters):
    return (SLAT + meters * math.cos(math.radians(bearing_deg)) / MLAT,
            SLNG + meters * math.sin(math.radians(bearing_deg)) / mlng(SLAT))


def dist_m(lat, lng):
    return math.hypot((lat - SLAT) * MLAT, (lng - SLNG) * mlng(SLAT))


def bearing_to_stop(lat, lng):
    return math.degrees(math.atan2((SLNG - lng) * mlng(SLAT), (SLAT - lat) * MLAT)) % 360


def buses(s):
    return s.worker.data["TransitView"]["bus"]


def bus(s, vid):
    return next(b for b in buses(s) if str(b["VehicleID"]) == vid)


def bump_all(s, secs):
    for b in buses(s):
        b["timestamp"] = int(b["timestamp"]) + secs


def step(s, vid="3678", toward_m=120):
    """Advance the feed by 15 s and move bus `vid` toward the stop (120 m / 15 s = 8 m/s)."""
    b = bus(s, vid)
    lat, lng = float(b["lat"]), float(b["lng"])
    f = min(1.0, toward_m / dist_m(lat, lng))
    b["lat"], b["lng"] = f"{lat + (SLAT - lat) * f:.6f}", f"{lng + (SLNG - lng) * f:.6f}"
    bump_all(s, 15)
    s.tick(15000)


def setup_moving(s, start_m=3000, bearing=200):
    lat, lng = offset(bearing, start_m)
    b = bus(s, "3678")
    b["lat"], b["lng"], b["heading"] = f"{lat:.6f}", f"{lng:.6f}", bearing_to_stop(lat, lng)


def boot(s, hash_=HASH):
    s.open(hash_=hash_)
    s.wait_live()
    s.page.wait_for_selector("#addAlert")
    s.settle()


def add_alert(s, minutes):
    s.page.select_option("#alertMin", str(minutes))
    s.page.click("#addAlert")


def status(s, i=0):
    return s.page.locator("#rules .rstatus").nth(i).inner_text()


def status_min(s):
    m = re.search(r"about (\d+) min", status(s))
    return int(m.group(1)) if m else None


def toasts(s):
    return s.page.locator("#toasts .toast").all_inner_texts()


def msg(route, minutes):
    return f"Leave now — the {route} is about {minutes} min from {SNAME}"


def stored_rules(s):
    raw = s.page.evaluate(f"localStorage.getItem('{KEY}')")
    return json.loads(raw)["rules"] if raw else []


# ---------------------------------------------------------------- (a) unit

UNIT_JS = """([slat, slng]) => {
    const T = window.__SEPTA_TEST__, H = T.speedHist, ev = T.evalRule, r = {};
    const now = 1e12, okSrc = { ok: now - 1000, stale: false };
    const hist = (key, d0, mps) => { H[key] = [0, 15, 30].map(t => ({ ts: 1000 + t, lat: slat + (d0 + mps * (30 - t)) / 111195, lng: slng })); };
    const veh = (key, d, over) => Object.assign({ key, kind: 'bus', route: '21', nextId: '14880', lat: slat + d / 111195, lng: slng, heading: 180 }, over || {});
    const rule = (over) => Object.assign({ id: 'r1', route: '21', stopId: '14880', lat: slat, lng: slng, minutes: 5, enabled: true, last: null }, over || {});
    hist('b1', 2000, 10);               // 2000 m at 10 m/s -> 4 min
    hist('b2', 3000, 10);               // 3000 m at 10 m/s -> 6 min
    hist('far', 6000, 10);              // 10 min
    r.fire = ev(rule(), [veh('b1', 2000)], now, okSrc);
    r.equal = ev(rule({ minutes: 4 }), [veh('b1', 2000)], now, okSrc);
    r.above = ev(rule({ minutes: 3 }), [veh('b1', 2000)], now, okSrc);
    r.otherNext = ev(rule(), [veh('b1', 2000, { nextId: '999' })], now, okSrc);
    r.otherRoute = ev(rule(), [veh('b1', 2000, { route: '12' })], now, okSrc);
    r.train = ev(rule(), [veh('b1', 2000, { kind: 'train' })], now, okSrc);
    r.unknown = ev(rule({ minutes: 30 }), [veh('nohist', 100)], now, okSrc);
    H.still = [0, 15, 30].map(t => ({ ts: 1000 + t, lat: slat + 0.01, lng: slng }));
    r.still = ev(rule({ minutes: 30 }), [veh('still', 1000)], now, okSrc);
    r.none = ev(rule(), [], now, okSrc);
    r.stale = ev(rule(), [veh('b1', 2000)], now, { ok: now - 1000, stale: true });
    r.dropped = ev(rule(), [veh('b1', 2000)], now, { ok: now - 130000, stale: false });
    r.missing = ev(rule(), [veh('b1', 2000)], now, { ok: 0, stale: false });
    r.paused = ev(rule({ enabled: false }), [veh('b1', 2000)], now, okSrc);
    // rough: heading toward the stop but its next stop is another one -> never eligible
    r.rough = ev(rule({ minutes: 30 }), [veh('b1', 2000, { nextId: '999' })], now, okSrc);
    r.roughEta = T.etaFor(veh('b1', 2000, { nextId: '999' }), { id: '14880', lat: slat, lng: slng });
    // de-dupe
    r.dupRecent = ev(rule({ last: { key: 'b1', t: now - 60000 } }), [veh('b1', 2000)], now, okSrc);
    r.dupOld = ev(rule({ last: { key: 'b1', t: now - 16 * 60000 } }), [veh('b1', 2000)], now, okSrc);
    r.dupOther = ev(rule({ last: { key: 'zzz', t: now - 60000 } }), [veh('b1', 2000)], now, okSrc);
    r.dupSecond = ev(rule({ minutes: 8, last: { key: 'b1', t: now - 60000 } }), [veh('b1', 2000), veh('b2', 3000)], now, okSrc);
    r.best = ev(rule({ minutes: 8 }), [veh('far', 6000), veh('b2', 3000), veh('b1', 2000)], now, okSrc);
    return r;
}"""


def test_unit_eval_rule(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.worker.data["TransitView"] = {"bus": []}
        s.open()
        s.wait_live()
        r = s.page.evaluate(UNIT_JS, [SLAT, SLNG])
        assert r["fire"]["fire"] is True and r["fire"]["min"] == 4 and r["fire"]["fireKey"] == "b1", r["fire"]
        assert r["equal"]["fire"] is True, "fires when ETA equals the threshold"
        assert r["above"]["state"] == "watching" and r["above"]["fire"] is False and r["above"]["min"] == 4
        for k in ("otherNext", "otherRoute", "train", "none"):
            assert r[k]["state"] == "none" and not r[k].get("fire"), (k, r[k])
        assert r["unknown"]["state"] == "measuring" and not r["unknown"].get("fire"), r["unknown"]
        assert r["still"]["state"] == "still" and not r["still"].get("fire"), r["still"]
        for k in ("stale", "dropped", "missing"):
            assert r[k] == {"state": "unavailable"}, (k, r[k])
        assert r["paused"] == {"state": "paused"}
        assert r["roughEta"]["rough"] is True and r["roughEta"]["min"] is not None, "premise: etaFor does produce a rough number"
        assert r["rough"]["state"] == "none" and not r["rough"].get("fire"), r["rough"]
        assert r["dupRecent"]["fire"] is False and r["dupRecent"]["min"] == 4
        assert r["dupOld"]["fire"] is True
        assert r["dupOther"]["fire"] is True
        assert r["dupSecond"]["fire"] is True and r["dupSecond"]["fireKey"] == "b2", r["dupSecond"]
        assert r["best"]["min"] == 4 and r["best"]["key"] == "b1" and r["best"]["fireKey"] == "b1", r["best"]


# ---------------------------------------------------------------- (b) e2e

def test_e2e_toast_fires_once_at_threshold(root):
    with Session(root) as s:
        setup_moving(s, 3000)
        boot(s)
        add_alert(s, 5)
        assert s.page.locator("#rules li").count() == 1
        seen, fired_at = [], None
        for i in range(16):
            step(s)
            m = status_min(s)
            t = toasts(s)
            seen.append((m, len(t)))
            if m is not None and m > 5:
                assert t == [], (i, m, t)
            if m is not None and m <= 5:
                fired_at = (i, m, t)
                break
        assert fired_at, seen
        assert any(m is not None and m > 5 for m, _ in seen), "ETA started above the threshold: " + str(seen)
        i, m, t = fired_at
        assert len(t) == 1 and t[0].startswith(msg("21", m)), (t, m)
        assert t[0].replace("Dismiss", "").strip() == msg("21", m)
        assert s.page.locator("#toasts .toast").get_attribute("role") == "alert"
        assert stored_rules(s)[0]["last"]["key"] == "b3678"
        # dismiss by keyboard, then it must not come back on later ticks while the bus is still near
        s.page.locator("#toasts .toast button").focus()
        s.page.keyboard.press("Enter")
        assert toasts(s) == []
        for _ in range(3):
            step(s)
            assert toasts(s) == [], toasts(s)
        assert not s.console_errors, s.console_errors


def test_toast_dismiss_click_and_stack_cap(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.open()
        s.wait_live()
        # drive notify() through real firings: five rules for five minute values, bus already close and measured
        setup_moving(s, 1000)
        s.page.reload()
        s.wait_live()
        s.open(hash_=HASH)
        s.wait_live()
        s.page.wait_for_selector("#addAlert")
        for _ in range(3):
            step(s)
        for m in (3, 5, 8, 10, 15):
            add_alert(s, m)
        # ETA is ~2 min, so the 5/8/10/15 alerts (and 3) all fire as they are added: only the newest 3 stay
        n = len(toasts(s))
        assert n == 3, toasts(s)
        s.page.locator("#toasts .toast button").first.click()
        assert len(toasts(s)) == 2


# ---------------------------------------------------------------- (c) status lines

def test_status_lines(root):
    with Session(root) as s:
        setup_moving(s, 3000)
        boot(s)
        add_alert(s, 5)
        assert status(s) == "Measuring speed…", status(s)
        step(s)
        step(s)
        assert re.fullmatch(r"Watching — nearest bus about \d+ min", status(s)), status(s)
        # paused
        s.page.locator("#rules .rtoggle").uncheck()
        assert status(s) == "Paused"
        s.page.locator("#rules .rtoggle").check()
        assert status(s).startswith("Watching")
        # status text updates in place without stealing focus
        s.page.locator("#rules .rtoggle").focus()
        step(s)
        assert s.page.evaluate("document.activeElement.classList.contains('rtoggle')")
        # no bus heading here
        s.worker.data["TransitView"]["bus"] = [b for b in buses(s) if b["VehicleID"] != "3678"]
        bump_all(s, 15)
        s.tick(15000)
        assert status(s) == "Watching — no bus heading here yet", status(s)
        # unavailable (stale first, then dropped)
        s.worker.mode = "abort"
        s.tick(15000)
        s.tick(2000)
        assert status(s) == "Live data unavailable", status(s)
        for _ in range(9):
            s.tick(15000)
        assert status(s) == "Live data unavailable", status(s)
        assert toasts(s) == []


# ---------------------------------------------------------------- (d) persistence

def test_rules_persist_across_reload(root):
    with Session(root) as s:
        boot(s)
        add_alert(s, 10)
        before = stored_rules(s)
        assert len(before) == 1
        r = before[0]
        assert r["route"] == SROUTE and r["stopId"] == SID and r["minutes"] == 10 and r["enabled"] is True
        assert r["stopName"] == SNAME and abs(r["lat"] - SLAT) < 1e-6 and r["last"] is None
        assert set(r) == {"id", "route", "stopId", "stopName", "lat", "lng", "minutes", "enabled", "last"}
        s.page.reload()
        s.wait_live()
        assert s.page.locator("#rules li").count() == 1
        assert f"Route {SROUTE} · {SNAME} · under 10 min" in s.page.inner_text("#rules li")
        assert stored_rules(s)[0]["id"] == r["id"]


def test_corrupt_storage_is_ignored(root):
    bad = [
        "localStorage.setItem('septa.rules.v1','not json')",
        "localStorage.setItem('septa.rules.v1',JSON.stringify({rules:[{id:'a1',route:'21',stopId:'14880',stopName:'x',lat:39.9,lng:-75.1,minutes:999,enabled:true,last:null}]}))",
        "localStorage.setItem('septa.rules.v1','[1,2,3]')",
        "localStorage.setItem('septa.rules.v1',JSON.stringify({rules:[null,5,'x',{id:'<img>',route:'21<',stopId:'1',lat:'a',lng:null,minutes:5}]}))",
    ]
    for js in bad:
        with Session(root, init_scripts=[js]) as s:
            s.open()
            s.wait_live()
            assert s.page.locator("#rules li").count() == 0, js
            assert "Open a stop, then tap Add alert." in s.page.inner_text("#h-leave ~ #rulesEmpty")
            assert not s.console_errors, (js, s.console_errors)


def test_one_good_rule_survives_bad_neighbours(root):
    good = {"id": "g1", "route": "21", "stopId": "14880", "stopName": SNAME, "lat": SLAT, "lng": SLNG, "minutes": 8, "enabled": True, "last": None}
    badr = dict(good, id="g2", minutes=1)
    js = "localStorage.setItem('septa.rules.v1',%s)" % json.dumps(json.dumps({"rules": [badr, good]}))
    with Session(root, init_scripts=[js]) as s:
        s.open()
        s.wait_live()
        assert s.page.locator("#rules li").count() == 1
        assert "under 8 min" in s.page.inner_text("#rules li")


# ---------------------------------------------------------------- (e) permission

def test_permission_flow(root):
    with Session(root, init_scripts=[NOTIF]) as s:
        s.open()
        s.wait_live()
        assert s.page.locator("#enableNotify").is_visible()
        assert "cannot reach you when the page is closed" in s.page.inner_text("#notifyBox")
        assert s.page.evaluate("window.__permCalls") == 0
        s.tick(30000)
        assert s.page.evaluate("window.__permCalls") == 0
        s.page.click("#enableNotify")
        assert s.page.evaluate("window.__permCalls") == 1
        assert s.page.locator("#enableNotify").count() == 0
        assert "Notifications on" in s.page.inner_text("#notifyBox")


def test_permission_denied_message(root):
    with Session(root, init_scripts=[NOTIF + ";window.__nextPerm='denied'"]) as s:
        s.open()
        s.wait_live()
        s.page.click("#enableNotify")
        assert s.page.locator("#enableNotify").count() == 0
        assert "Notifications blocked in your browser settings" in s.page.inner_text("#notifyBox")


def test_no_button_when_granted_or_unsupported(root):
    with Session(root, init_scripts=[NOTIF + ";window.__setPerm('granted')"]) as s:
        s.open()
        s.wait_live()
        assert s.page.locator("#enableNotify").count() == 0
    with Session(root, init_scripts=["delete window.Notification"]) as s:
        s.open()
        s.wait_live()
        assert s.page.locator("#enableNotify").count() == 0
        assert not s.console_errors


def run_hidden_alert(root, perm):
    with Session(root, init_scripts=[NOTIF, HIDDEN]) as s:
        setup_moving(s, 3000)
        boot(s)
        s.page.evaluate(f"window.__setPerm('{perm}')")
        add_alert(s, 5)
        s.page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
        for _ in range(16):
            step(s)
            if toasts(s):
                break
        t = toasts(s)
        assert len(t) == 1, t
        return t[0].replace("Dismiss", "").strip(), s.page.evaluate("window.__notes")


def test_hidden_alert_notification_only_when_granted(root):
    text, notes = run_hidden_alert(root, "granted")
    assert len(notes) == 1 and notes[0]["t"] == text and text.startswith("Leave now — the 21 is about "), (notes, text)
    text, notes = run_hidden_alert(root, "default")
    assert notes == []
    text, notes = run_hidden_alert(root, "denied")
    assert notes == []


def test_visible_alert_makes_no_system_notification(root):
    with Session(root, init_scripts=[NOTIF]) as s:
        setup_moving(s, 3000)
        boot(s)
        s.page.evaluate("window.__setPerm('granted')")
        add_alert(s, 5)
        for _ in range(16):
            step(s)
            if toasts(s):
                break
        assert len(toasts(s)) == 1
        assert s.page.evaluate("window.__notes") == []


# ---------------------------------------------------------------- (f) hidden-tab refresh

def tv_hits(s):
    return sum(1 for h in s.worker.hits if h == "TransitView")


def test_hidden_tab_refreshes_only_with_enabled_rule(root):
    with Session(root, init_scripts=[HIDDEN]) as s:
        boot(s)
        s.page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
        n0 = tv_hits(s)
        for _ in range(3):
            s.tick(15000)
        assert tv_hits(s) == n0, "no rule: a hidden tab must not request data"
        s.page.evaluate("window.__hidden = false; document.dispatchEvent(new Event('visibilitychange'))")
        s.tick(15000)
        add_alert(s, 5)
        s.page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
        n1 = tv_hits(s)
        for _ in range(4):  # a hidden tab with a rule refreshes once a minute (task 6b), not every 15 s
            s.tick(15000)
        assert 1 <= tv_hits(s) - n1 <= 2, (n1, tv_hits(s))
        # a paused rule counts as no rule
        s.page.locator("#rules .rtoggle").uncheck()
        n2 = tv_hits(s)
        for _ in range(3):
            s.tick(15000)
        assert tv_hits(s) == n2
        # removing the last rule too
        s.page.locator("#rules .rtoggle").check()
        s.page.locator("#rules .rrm").click()
        n3 = tv_hits(s)
        for _ in range(3):
            s.tick(15000)
        assert tv_hits(s) == n3


# ---------------------------------------------------------------- (g) cap and duplicates

def test_duplicates_are_not_created(root):
    with Session(root) as s:
        boot(s)
        btn = s.page.locator("#addAlert")
        assert btn.is_enabled() and btn.inner_text() == "Add alert"
        assert s.page.input_value("#alertMin") == "8"
        assert s.page.eval_on_selector_all("#alertMin option", "o => o.map(x => x.value)") == ["3", "5", "8", "10", "15"]
        btn.click()
        assert btn.is_disabled() and btn.inner_text() == "Alert set"
        assert "Alert set" in s.page.inner_text("#alertLive")
        assert s.page.evaluate("document.activeElement.id") == "alertMin"
        assert len(stored_rules(s)) == 1
        s.page.select_option("#alertMin", "10")
        assert btn.is_enabled()
        s.page.select_option("#alertMin", "8")
        assert btn.is_disabled()
        btn.click(force=True)
        assert len(stored_rules(s)) == 1
        # removing the rule re-enables the button
        s.page.locator("#rules .rrm").click()
        assert btn.is_enabled() and stored_rules(s) == []
        assert "Open a stop, then tap Add alert." in s.page.inner_text("#rulesEmpty")


def test_ten_rule_cap(root):
    rules = [{"id": f"r{i}", "route": "12", "stopId": str(100 + i), "stopName": f"Stop {i}", "lat": 39.95, "lng": -75.16,
              "minutes": 8, "enabled": False, "last": None} for i in range(10)]
    js = "localStorage.setItem('septa.rules.v1',%s)" % json.dumps(json.dumps({"rules": rules}))
    extra = dict(rules[0], id="r11", stopId="105")
    with Session(root, init_scripts=[js]) as s:
        boot(s)
        assert s.page.locator("#rules li").count() == 10
        s.page.click("#addAlert")
        assert "You can keep up to 10 alerts." in s.page.inner_text("#alertLive")
        assert s.page.locator("#rules li").count() == 10 and len(stored_rules(s)) == 10
    # more than ten in storage: only the first ten are kept
    js2 = "localStorage.setItem('septa.rules.v1',%s)" % json.dumps(json.dumps({"rules": rules + [extra]}))
    with Session(root, init_scripts=[js2]) as s:
        s.open()
        s.wait_live()
        assert s.page.locator("#rules li").count() == 10


def test_labels_and_remove_button(root):
    with Session(root) as s:
        boot(s)
        add_alert(s, 3)
        rm = s.page.locator("#rules .rrm")
        assert rm.get_attribute("aria-label") == f"Remove alert for route {SROUTE} at {SNAME}"
        assert s.page.locator("#rules .rtoggle").get_attribute("aria-label")
        assert s.page.locator("#h-leave").text_content() == "Leave-now alerts"
        assert "Alerts only work while this page is open. Phones may pause background tabs." in s.page.inner_text("section[aria-labelledby=h-leave]")
        keys = s.page.evaluate("Object.keys(localStorage).sort()")
        assert set(keys) <= {KEY, "septa.prefs.v1", "septa.defaults.v2"}, keys
        assert not s.page.evaluate("!!document.querySelector('#rules [aria-live]')")
        # stop names are text, never markup
        rm.click()
        assert s.page.locator("#rules li").count() == 0
        assert s.page.evaluate("document.activeElement.id") == "h-leave"


def test_stop_name_is_not_markup(root):
    name = "<img src=x onerror=window.__pwn=1> & Co"
    rule = {"id": "x1", "route": "21", "stopId": "14880", "stopName": name, "lat": SLAT, "lng": SLNG, "minutes": 8, "enabled": True, "last": None}
    js = "localStorage.setItem('septa.rules.v1',%s)" % json.dumps(json.dumps({"rules": [rule]}))
    with Session(root, init_scripts=[js]) as s:
        s.open()
        s.wait_live()
        assert s.page.locator("#rules img").count() == 0
        assert name in s.page.inner_text("#rules li")
        assert s.page.evaluate("window.__pwn") is None


# ---------------------------------------------------------------- (h) phone layout

def test_mobile_no_hscroll_with_section_rule_and_toast(root):
    with Session(root, viewport=(390, 844)) as s:
        setup_moving(s, 1200)
        boot(s)
        add_alert(s, 15)
        for _ in range(3):
            step(s)
        assert len(toasts(s)) == 1
        assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert s.page.evaluate("document.body.scrollWidth <= window.innerWidth")
        r = s.page.evaluate("(() => { const b = document.querySelector('#toasts .toast').getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom] })()")
        assert r[0] >= 0 and r[1] <= 390 and r[2] >= 0, r
        s.page.locator("#rules li").scroll_into_view_if_needed()
        assert s.page.evaluate("(() => { const p = document.querySelector('#panel'); return p.scrollWidth <= p.clientWidth + 1 })()")
        c = s.page.evaluate("(() => { const b = document.querySelector('#stopCard').getBoundingClientRect(); return [b.left, b.right] })()")
        assert c[0] >= 0 and c[1] <= 390, c
        row = s.page.evaluate("(() => { const b = document.querySelector('#stopCard .alertrow'); return b.scrollWidth <= b.clientWidth + 1 })()")
        assert row
        s.shot("leave_alerts_390")
