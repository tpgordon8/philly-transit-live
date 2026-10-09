"""Screenshots of the Indego layer (not part of the suite).

    python3 tests/shots_indego.py [--root DIR] [--out DIR] [--widths 390,1280] [--schemes light,dark]

Saves <out>/indego_<width>_<scheme>_<state>.png for the states layer (zoom 15, markers only), card (a station card open) and hint (zoom 12).
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_indego_layer as T  # noqa: E402
import test_responsive as R  # noqa: E402
from shots_responsive import fake_tile  # noqa: E402


def shoot(root, width, scheme, state, out):
    vp = (width, 844 if width < 700 else 800)
    with R.session(root, vp, init_scripts=[T.HOOK, T.ON], color_scheme=scheme, tile_png=fake_tile()) as s:
        s.open()
        s.wait_live()
        T.view(s, 12 if state == "hint" else 15)
        if state != "hint":
            s.page.wait_for_function("document.querySelectorAll('.ind-wrap').length > 0")
        if state == "card":
            T.open_first(s)
        s.page.wait_for_timeout(400)
        path = out / f"indego_{width}_{scheme}_{state}.png"
        s.page.screenshot(path=str(path))
        return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default="/tmp/claude-0/shots-indego")
    ap.add_argument("--widths", default="390,1280")
    ap.add_argument("--schemes", default="light,dark")
    ap.add_argument("--states", default="layer,card,hint")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for w in (int(x) for x in a.widths.split(",")):
        for sc in a.schemes.split(","):
            for st in a.states.split(","):
                print(shoot(a.root, w, sc, st, out))


if __name__ == "__main__":
    main()
