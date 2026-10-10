"""My stops board, logic and view together (no fakes): pin a stop from its card, open the board, and check that the row on screen
shows the same numbers S.board.rows() computes from the live mock feed, that they tick, and that removing the pin empties the board."""
import re

from harness import Session
from test_first_run import must_fail, seed
from test_stop_board import SID, SROUTE, setup_moving, step
from test_board_logic import PLACES, js

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
        assert "21" in txt and "Home" in txt and re.search(r"Bus in\s*\d+\s*min|about\s*\d+", txt, re.I), txt
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
