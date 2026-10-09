"""Buses-only, 0.5 mi defaults and the one-time septa.defaults.v2 migration.

All sessions here use legacy_defaults=False so the harness does not pre-seed the old all-modes world.
"""
import json

from harness import Session

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_a_fresh_browser_is_buses_only_half_mile_no_trainview",
    "test_b_legacy_saved_prefs_migrate_once_keep_center",
    "test_f_empty_state_half_mile_and_widen_button",
}

PREFS, KEY = "septa.prefs.v1", "septa.defaults.v2"
NEW = {"bus": True, "trolley": False, "subway": False, "train": False, "indego": False}  # Indego stations are off by default (js/indego.js)
OLD_ALL = {"bus": True, "trolley": True, "subway": True, "train": True}
FAR = {"lat": 40.5, "lng": -75.0, "label": "Nowhere"}  # no fixture vehicle within 5 mi


def seed_if_absent(key, value):
    return (f"try {{ if (localStorage.getItem({json.dumps(key)}) === null) "
            f"localStorage.setItem({json.dumps(key)}, {json.dumps(json.dumps(value))}); }} catch (e) {{}}")


def raw(s, key):
    return s.page.evaluate(f"localStorage.getItem({json.dumps(key)})")


def chips_on(s):
    return s.page.evaluate("[...document.querySelectorAll('#modes input')].filter(i => i.checked).map(i => i.dataset.mode)")


def radius_ui(s):
    return s.page.evaluate("[document.querySelector('#radius').value, document.querySelector('#radiusOut').textContent]")


def hits(s, name):
    return [h for h in s.worker.hits if h == name]


def test_a_fresh_browser_is_buses_only_half_mile_no_trainview(root):
    with Session(root, legacy_defaults=False) as s:
        s.open()
        s.wait_live()
        assert chips_on(s) == ["bus"], chips_on(s)
        assert radius_ui(s) == ["0.5", "0.5 mi"], radius_ui(s)
        kinds = s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].map(w => (w.className.match(/k-(\\w+)/) || [])[1])")
        assert kinds and set(kinds) == {"bus"}, set(kinds)
        for _ in range(5):
            s.tick(15000)
        assert len(hits(s, "TransitView")) >= 5 and not hits(s, "TrainView"), s.worker.hits
        assert not s.console_errors, s.console_errors


def test_b_legacy_saved_prefs_migrate_once_keep_center(root):
    center = {"lat": 39.99, "lng": -75.12, "label": "Kensington"}
    legacy = {"center": center, "radius": 1.5, "filters": OLD_ALL}
    with Session(root, legacy_defaults=False, init_scripts=[seed_if_absent(PREFS, legacy)]) as s:
        s.open()
        s.wait_live()
        assert chips_on(s) == ["bus"], chips_on(s)
        assert radius_ui(s) == ["0.5", "0.5 mi"], radius_ui(s)
        saved = json.loads(raw(s, PREFS))
        assert saved["center"] == center, saved
        assert saved["radius"] == 0.5 and saved["filters"] == NEW, saved
        assert raw(s, KEY) is not None and json.loads(raw(s, KEY)) in ("1", 1), raw(s, KEY)
        assert not hits(s, "TrainView"), s.worker.hits
        assert not s.console_errors, s.console_errors


def test_c_second_load_is_not_migrated_and_rail_is_requested(root):
    with Session(root, legacy_defaults=False) as s:
        s.open()
        s.wait_live()
        assert raw(s, KEY) is not None
        s.page.check("#modes input[data-mode=train]", force=True)
        s.tick(1000)
        assert json.loads(raw(s, PREFS))["filters"]["train"] is True
        s.worker.hits.clear()
        s.page.reload()
        s.wait_live()
        assert chips_on(s) == ["bus", "train"], chips_on(s)
        s.tick(15000)
        assert hits(s, "TrainView"), s.worker.hits
        assert json.loads(raw(s, PREFS))["filters"] == {**NEW, "train": True}
        assert not s.console_errors, s.console_errors


def test_d_trolley_chip_costs_no_trainview(root):
    west = {"lat": 39.9498, "lng": -75.2019, "label": "West Philly"}  # fixture trolleys (T2) run here
    scripts = [seed_if_absent(KEY, "1"), seed_if_absent(PREFS, {"center": west})]
    with Session(root, legacy_defaults=False, init_scripts=scripts) as s:
        s.open()
        s.wait_live()
        s.page.check("#modes input[data-mode=trolley]", force=True)
        for _ in range(3):
            s.tick(15000)
        assert chips_on(s) == ["bus", "trolley"], chips_on(s)
        assert not hits(s, "TrainView"), s.worker.hits
        kinds = s.page.evaluate("[...document.querySelectorAll('.veh-wrap')].map(w => (w.className.match(/k-(\\w+)/) || [])[1])")
        assert "trolley" in kinds, set(kinds)
        n = s.page.evaluate("document.querySelector('[data-n=subway]').textContent")
        assert n.isdigit(), "count must show for a chip fed by TransitView even when the chip is off"
        assert not s.page.evaluate("document.querySelector('[data-n=train]').textContent"), "skipped source stays blank"
        assert not s.console_errors, s.console_errors


def test_e_corrupt_prefs_and_missing_key_boot_with_new_defaults(root):
    for junk in ("{not json", "[1,2]", '"x"', '{"radius":99,"filters":{"bus":"x"}}'):
        script = f"try {{ localStorage.setItem({json.dumps(PREFS)}, {json.dumps(junk)}); }} catch (e) {{}}"
        with Session(root, legacy_defaults=False, init_scripts=[script]) as s:
            s.open()
            s.wait_live()
            assert chips_on(s) == ["bus"] and radius_ui(s) == ["0.5", "0.5 mi"], (junk, chips_on(s), radius_ui(s))
            assert raw(s, KEY) is not None
            assert json.loads(raw(s, PREFS))["filters"] == NEW
            assert not s.console_errors, (junk, s.console_errors)


def test_f_empty_state_half_mile_and_widen_button(root):
    scripts = [seed_if_absent(KEY, "1"), seed_if_absent(PREFS, {"center": FAR})]
    with Session(root, legacy_defaults=False, init_scripts=scripts) as s:
        s.open()
        s.wait_live()
        assert radius_ui(s) == ["0.5", "0.5 mi"], radius_ui(s)
        box = s.page.locator("#empty")
        assert box.is_visible() and "Quiet around here" in box.text_content()
        assert "0.5 mi" in box.text_content()
        btn = s.page.locator("#emptyAct")
        assert btn.text_content().strip() == "Widen to 2 mi", btn.text_content()
        btn.click()
        s.tick(500)
        assert radius_ui(s) == ["2", "2 mi"], radius_ui(s)
        assert json.loads(raw(s, PREFS))["radius"] == 2
        assert not s.console_errors, s.console_errors
