"""My stops board, logic and view together (no fakes): pin a stop from its card, open the board, and check that the row on screen
shows the same numbers S.board.rows() computes from the live mock feed, that they tick, and that removing the pin empties the board."""
import json
import re

from harness import Session
from test_first_run import must_fail, seed
from test_stop_board import SID, SROUTE, setup_moving, step
from test_board_logic import KEY, PLACES, SETUP2, T0, js, pin

FAST = {"test_pin_a_stop_and_see_it_on_the_board"}
HASH = f"#stop={SID}&route={SROUTE}"


def check_pin_and_see_it(root):
    with Session(root, viewport=(1133, 744), init_scripts=[seed("septa.places.v1", PLACES)]) as s:
        setup_moving(s)
        s.open(hash_=HASH)
        s.wait_live()
        s.settle()
        for _ in range(3):
            step(s, "3678", 120)
        s.page.wait_for_selector("#pinBoard")
        s.page.click("#pinBoard")
        s.page.locator("#pinChoose button").first.click()  # Home
        assert s.page.inner_text("#stopLive") == "Pinned to board."
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector("#boardView", state="visible")
        s.settle()
        rows = s.page.locator("#boardView li")
        assert rows.count() == 1, rows.count()
        txt = rows.first.inner_text()
        assert "21" in txt and "Home" in txt and re.search(r"Bus in \(estimate\)\s*\d+\s*min|about\s*\d+", txt, re.I), txt
        assert re.search(r"LATER|SOON|LEAVE NOW|MISSED", txt), txt
        r = js(s, "window.SEPTA.board.rows(Date.now())[0]")
        eta = r["arrivals"][0]["etaMin"]
        shown = int(re.search(r"(\d+)\s*min", txt.split("Bus in", 1)[-1]).group(1)) if "Bus in" in txt else None
        assert shown is None or abs(shown - eta) <= 1.5, (shown, eta, txt)
        # settings: Remove empties the board and shows the empty state
        s.page.click("#boardView button:has-text('Settings')")
        s.page.locator("#boardView button:has-text('Remove')").first.click()
        assert js(s, "window.SEPTA.board.pins().length") == 0
        s.page.wait_for_selector("#boardView :text('Pin a stop')", timeout=5000)
        assert not s.console_errors, s.console_errors


def test_pin_a_stop_and_see_it_on_the_board(root):
    check_pin_and_see_it(root)
    must_fail(check_pin_and_see_it, root, ("js/board.js", "S.board.rows = rows;", "S.board.rows = function () { return []; };"))


# ---------------------------------------------------------------------------------------------------------------------------
# The three tests below are written against the FIX CONTRACT (tests fix brief, review items 6, 7 and 10) and read the REAL view
# (js/boardview.js from the view lane): "Place removed" for a deleted place, "Bus nearby" for buses with no measured time yet and
# "45+" for an arrival more than 45 minutes away. They fail until the view lane is merged; the architect runs them after the merge.
# They are deliberately not in FAST.
# ---------------------------------------------------------------------------------------------------------------------------
def board_text(s):
    s.page.evaluate("location.hash = '#board'")
    s.page.wait_for_selector("#boardView", state="visible")
    s.settle()
    return s.page.locator("#boardView li").first.inner_text()


def check_removed_place_on_screen(root):
    stored = json.dumps({"pins": [pin(0, placeId="gone", stopName="Market St & 15th", walkMin=None)], "bufferMin": 2, "bad": False})
    with Session(root, viewport=(1133, 744), init_scripts=[seed(KEY, stored)]) as s:
        s.open()
        s.wait_live()
        s.settle()
        txt = board_text(s)
        assert "Place removed" in txt and "5 min" in txt, txt
        assert js(s, "window.SEPTA.board.pins().length") == 1, "the pin is not dropped"
        assert not s.console_errors, s.console_errors


def check_far_and_pending_on_screen(root):
    two = json.dumps({"pins": [pin(0, walkMin=3), pin(1, stopId="101", walkMin=3)], "bufferMin": 2, "bad": False})
    with Session(root, viewport=(1133, 744), init_scripts=[seed(KEY, two)]) as s:
        s.open()
        s.wait_live()
        s.settle()
        # pin 0: one bus 52 minutes away; pin 1: two buses heading here with no measured time
        js(s, """() => { const S = window.SEPTA;
            S.stops.boardRows = (stop) => ({ a: (stop.id === '100' ? [{ key: 'far', min: 52 }] : [{ key: 'x', min: null }, { key: 'y', min: null }])
                .map(x => ({ v: { key: x.key }, d: 0.1, eta: { min: x.min, rough: false } })), b: [] });
            S.board.refresh(); }""")
        s.page.evaluate("location.hash = '#board'")
        s.page.wait_for_selector("#boardView", state="visible")
        s.settle()
        rows = s.page.locator("#boardView li")
        assert rows.count() == 2, rows.count()
        far, pending = rows.nth(0).inner_text(), rows.nth(1).inner_text()
        assert "45+" in far and not re.search(r"LEAVE NOW|SOON|LATER|MISSED", far), far
        assert "Bus nearby" in pending and "time not known yet" in pending, pending
        assert not s.console_errors, s.console_errors


def test_removed_place_is_shown_on_the_board(root):
    check_removed_place_on_screen(root)
    must_fail(check_removed_place_on_screen, root, ("js/board.js", "note: pin.placeId && !pl ? 'place-removed' : ''", "note: ''"))


def test_far_and_pending_arrivals_are_shown_on_the_board(root):
    check_far_and_pending_on_screen(root)
    must_fail(check_far_and_pending_on_screen, root, ("js/board.js", "pending++;", ""))
    must_fail(check_far_and_pending_on_screen, root, ("js/board.js", "if (left > FAR_MIN) a.far = true;", ""))


FAST.add("test_panel_renders_before_the_sheet_module_has_loaded")


def check_panel_without_sheet(root):
    # a page opened straight on #board can refresh before js/sheet.js has run: the panel must not throw
    with Session(root) as s:
        s.open()
        s.wait_live()
        s.page.evaluate("window.__sp = window.SEPTA.sheet.syncPill; delete window.SEPTA.sheet.syncPill")
        err = s.page.evaluate("(() => { try { window.SEPTA.panel.renderMyRoutes(); return ''; } catch (e) { return String(e); } })()")
        s.page.evaluate("window.SEPTA.sheet.syncPill = window.__sp")
        assert err == "", err


def test_panel_renders_before_the_sheet_module_has_loaded(root):
    check_panel_without_sheet(root)
    must_fail(check_panel_without_sheet, root, ("js/panel.js", "if (S.sheet.syncPill)\n      S.sheet.syncPill();", "S.sheet.syncPill();"))


FAST.add("test_the_board_path_opens_the_board")


def check_board_path(root):
    with Session(root, viewport=(1133, 744)) as s:
        s.open(path="board/")
        s.page.wait_for_url("**/index.html#board" if False else "**/#board", timeout=10000)
        s.page.wait_for_selector("#boardView", state="visible", timeout=10000)
        assert s.page.url.endswith("/#board"), s.page.url


def test_the_board_path_opens_the_board(root):
    check_board_path(root)
    must_fail(check_board_path, root, ("board/index.html", "location.replace('../#board');", ""),
              ("board/index.html", '<meta http-equiv="refresh" content="0; url=../#board">', ""))
