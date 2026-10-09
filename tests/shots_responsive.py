"""Screenshot matrix for the mobile and responsive pass (not part of the suite).

    python3 tests/shots_responsive.py [--root DIR] [--out DIR] [--widths 390,1280] [--states closed,open] [--schemes light,dark]

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


def fake_tile():
    """A 256 px tile that looks like an OSM tile (cream ground, white roads with grey casing, a park, a yellow main road)."""
    import io
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (256, 256), "#f2efe9")
    d = ImageDraw.Draw(im)
    d.rectangle([150, 150, 250, 240], fill="#c8facc")
    for box, w, col in (((0, 90, 256, 90), 9, "#fcd6a4"), ((70, 0, 70, 256), 6, "#ffffff"), ((0, 200, 256, 200), 6, "#ffffff"), ((190, 0, 190, 256), 6, "#ffffff")):
        d.line(box, fill="#bbbbbb", width=w + 2)
        d.line(box, fill=col, width=w)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def shoot(root, vp, state, out, scheme=None):
    hash_ = T.STOP_HASH if state == "stop" else ""
    kw = {"color_scheme": scheme, "tile_png": fake_tile()} if scheme else {}
    with T.session(root, vp, **kw) as s:
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
        path = out / f"{vp[0]}x{vp[1]}_{state}{'_' + scheme if scheme else ''}.png"
        s.page.screenshot(path=str(path))
        return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default="/tmp/claude-0/shots")
    ap.add_argument("--widths", default="")
    ap.add_argument("--schemes", default="", help="comma list of light,dark (with a realistic fake tile); default: browser default")
    ap.add_argument("--states", default=",".join(ALL))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    want = {int(w) for w in a.widths.split(",") if w}
    vps = [v for v in T.VIEWPORTS + [T.LANDSCAPE] if not want or v[0] in want]
    for vp in vps:
        for state, scheme in [(st, sc) for st in a.states.split(",") for sc in (a.schemes.split(",") if a.schemes else [None])]:
            try:
                print(shoot(a.root, vp, state, out, scheme))
            except Exception as e:  # noqa: BLE001 - a failed state must not stop the matrix
                print(f"FAILED {vp[0]}x{vp[1]} {state}: {str(e).splitlines()[0][:200]}")


if __name__ == "__main__":
    main()
