"""Task 0.1: records with late:998 are schedule-only trips and must be dropped; late:999 vehicles are kept."""
import json

from harness import FIX, Session

HOOK = ["window.__SEPTA_TEST__ = true"]
TV = json.loads((FIX / "TransitView.json").read_text())


def test_late_998_records_are_dropped(root):
    n998 = sum(1 for b in TV["bus"] if str(b["late"]) == "998")
    assert n998 > 0, "fixture has no late:998 records to test with"
    with Session(root, init_scripts=HOOK) as s:
        s.open()
        r = s.page.evaluate("""(tv) => { const T = window.__SEPTA_TEST__;
            const only998 = {bus: tv.bus.filter(b => String(b.late) === '998')};
            return {leaked: T.normBuses(only998).length, kept999: T.normBuses(tv).filter(v => v.late === null).length}; }""", TV)
        assert r["leaked"] == 0, f"{r['leaked']} late:998 vehicles were kept"
        assert r["kept999"] > 0, "late:999 vehicles must still be kept (as unknown delay)"


def test_late_998_synthetic_record_dropped_and_999_kept(root):
    base = dict(TV["bus"][0], timestamp=TV["bus"][0]["timestamp"])
    with Session(root, init_scripts=HOOK) as s:
        s.open()
        r = s.page.evaluate("""(b) => { const T = window.__SEPTA_TEST__;
            const mk = (late, id) => Object.assign({}, b, {late: late, VehicleID: id, label: id});
            const out = T.normBuses({bus: [mk(998, 'X998'), mk(999, 'X999'), mk(0, 'X0')]}).map(v => v.vid);
            return out; }""", base)
        assert "X998" not in r and "X999" in r and "X0" in r, f"unexpected survivors: {r}"
