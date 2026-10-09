"""Screenshot matrix for the mobile and responsive pass (not part of the suite).

    python3 tests/shots_responsive.py [--root DIR] [--out DIR] [--widths 390,1280] [--states closed,open]

Saves <out>/<width>x<height>_<state>.png for every viewport in tests/test_responsive.py (plus phone landscape) and these states:
closed (panel closed or at rest), open (panel open), trip (trip planner with results), suggest (suggestion list open),
vehicle (vehicle card open), stop (stop card open). Uses the hermetic harness, so it needs no network.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_responsive as T  # noqa: E402

ALL = ["closed", "open", "trip", "suggest", "vehicle", "stop"]


def shoot(root, vp, state, out):
    hash_ = T.STOP_HASH if state == "stop" else ""
    with T.session(root, vp) as s:
        T.boot(s, hash_)
        if state == "closed":
            T.set_sheet(s, False)
        elif state == "open":
            T.set_sheet(s, True)
        elif state == "trip":
            T.plan_trip(s)
        elif state == "suggest":
            T.open_suggestions(s)
        elif state == "vehicle":
            T.select_vehicle(s)
        elif state == "stop":
            T.set_sheet(s, False)
        s.page.wait_for_timeout(300)
        path = out / f"{vp[0]}x{vp[1]}_{state}.png"
        s.page.screenshot(path=str(path))
        return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default="/tmp/claude-0/shots")
    ap.add_argument("--widths", default="")
    ap.add_argument("--states", default=",".join(ALL))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    want = {int(w) for w in a.widths.split(",") if w}
    vps = [v for v in T.VIEWPORTS + [T.LANDSCAPE] if not want or v[0] in want]
    for vp in vps:
        for state in a.states.split(","):
            try:
                print(shoot(a.root, vp, state, out))
            except Exception as e:  # noqa: BLE001 - a failed state must not stop the matrix
                print(f"FAILED {vp[0]}x{vp[1]} {state}: {str(e).splitlines()[0][:200]}")


if __name__ == "__main__":
    main()
