"""Swipe the phone bottom sheet (ARCHITECTURE.md 15.10): drag the handle, the header or the closed sheet up to open it and down to close it;
the sheet follows the finger, settles by speed or by half, a tap still toggles, a drag never presses the button it ends on, sideways drags
and wide screens are left alone, and Up/Down on the focused handle do the same. Each fast check runs again on a broken copy (`must_fail`)."""
from harness import Session
from test_first_run import must_fail

FAST = {
    "test_swipe_opens_and_closes_and_follows_the_finger",
    "test_a_flick_a_short_drag_and_a_tap",
    "test_a_drag_on_the_closed_sheet_opens_it_without_pressing_buttons",
    "test_sideways_drags_wide_screens_and_keys",
}
PHONE = (390, 844)
SETTLED = "document.getAnimations().every(a => a.playState !== 'running' || !isFinite(a.effect.getComputedTiming().iterations))"


def boot(s):
    s.open()
    s.wait_live()
    s.page.wait_for_timeout(300)
    s.page.wait_for_function(SETTLED)


def state(s):
    return s.page.evaluate("document.getElementById('app').dataset.sheet")


def settle(s):
    s.page.wait_for_timeout(350)
    s.page.wait_for_function(SETTLED)


def center(s, sel):
    b = s.page.locator(sel).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def below_handle(s):
    b = s.page.locator("#status").bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] - 4  # the handle sticks over the top of the header


def drag(s, x, y0, y1, steps=10, pause=30, x1=None, release=True):
    m = s.page.mouse
    m.move(x, y0)
    m.down()
    for i in range(1, steps + 1):
        m.move(x if x1 is None else x + (x1 - x) * i / steps, y0 + (y1 - y0) * i / steps)
        s.page.wait_for_timeout(pause)
    if release:
        m.up()


def sheet(root):
    return Session(root, viewport=PHONE, mobile=True, touch=True)


def check_follow_and_settle(root):
    with sheet(root) as s:
        boot(s)
        assert state(s) == "peek"
        x, y = center(s, "#sheetHandle")
        peek_h = s.page.evaluate("document.getElementById('panel').getBoundingClientRect().height")
        map_h = s.page.evaluate("document.getElementById('stage').getBoundingClientRect().height")
        drag(s, x, y, y - 170, steps=6, pause=60, release=False)  # slow, held past halfway
        mid = s.page.evaluate("({rows: document.getElementById('app').style.gridTemplateRows, drag: document.getElementById('app').classList.contains('sheet-drag'), h: document.getElementById('panel').getBoundingClientRect().height, m: document.getElementById('stage').getBoundingClientRect().height})")
        assert mid["drag"] and mid["rows"] and peek_h + 100 < mid["h"], mid  # the sheet follows the finger
        assert mid["m"] < map_h - 100, mid  # and the map gives way under it
        s.page.mouse.up()  # let go past halfway: it opens
        settle(s)
        assert state(s) == "open"
        assert s.page.evaluate("document.getElementById('app').style.gridTemplateRows") == "" and not s.page.evaluate("document.getElementById('app').classList.contains('sheet-drag')")
        assert s.page.get_attribute("#sheetHandle", "aria-expanded") == "true"
        open_h = s.page.evaluate("document.getElementById('panel').getBoundingClientRect().height")
        assert open_h > peek_h + 100, (peek_h, open_h)
        # slow drag down from the header closes it
        x, y = below_handle(s)
        drag(s, x, y, y + 260, steps=8, pause=60)
        settle(s)
        assert state(s) == "peek" and s.page.get_attribute("#sheetHandle", "aria-expanded") == "false"
        assert s.page.evaluate("document.getElementById('app').style.gridTemplateRows") == ""
        assert not s.console_errors, s.console_errors


def test_swipe_opens_and_closes_and_follows_the_finger(root):
    check_follow_and_settle(root)
    must_fail(check_follow_and_settle, root, ("js/swipe.js", "st.h = Math.max(st.lo, Math.min(st.hi, st.h0 - dy));", "st.h = st.h0;"))
    must_fail(check_follow_and_settle, root, ("js/swipe.js", "app.style.removeProperty('grid-template-rows');", "0;"))


def check_flick_short_tap(root):
    with sheet(root) as s:
        boot(s)
        x, y = center(s, "#sheetHandle")
        drag(s, x, y, y - 24, steps=3, pause=40)  # short and slow: not enough
        settle(s)
        assert state(s) == "peek", "a short slow drag springs back"
        drag(s, x, y, y - 70, steps=4, pause=4)  # short but fast: a flick
        settle(s)
        assert state(s) == "open", "a flick opens the sheet wherever it was let go"
        x, y = center(s, "#sheetHandle")
        drag(s, x, y, y + 70, steps=4, pause=4)
        settle(s)
        assert state(s) == "peek", "and a downward flick closes it"
        s.page.click("#sheetHandle")
        settle(s)
        assert state(s) == "open", "a tap still toggles"
        s.page.click("#sheetHandle")
        settle(s)
        assert state(s) == "peek"


def test_a_flick_a_short_drag_and_a_tap(root):
    check_flick_short_tap(root)
    must_fail(check_flick_short_tap, root, ("js/swipe.js", "else if (Math.abs(v) > FLICK_PX_MS) open = v < 0;", ""))


def check_closed_sheet_drag(root):
    with sheet(root) as s:
        boot(s)
        s.page.evaluate("window.__locate = 0; document.getElementById('btnLocate').addEventListener('click', () => { window.__locate++; })")
        x, y = center(s, "#btnLocate")
        drag(s, x, y, y - 200, steps=8, pause=50)
        settle(s)
        assert state(s) == "open", "a drag that starts on a button of the closed sheet opens it"
        assert s.page.evaluate("window.__locate") == 0, "and does not press the button it started on"
        s.page.wait_for_timeout(400)
        s.page.click("#sheetHandle")
        settle(s)
        # typing in the search field is not hijacked
        x, y = center(s, "#addr")
        s.page.mouse.move(x, y)
        s.page.mouse.down()
        s.page.mouse.move(x, y - 60, steps=4)
        s.page.mouse.up()
        settle(s)
        assert state(s) == "peek", "the field was not a drag handle, and the tap on it may have opened or not; the sheet only closed by the handle click"
        assert not s.console_errors, s.console_errors


def test_a_drag_on_the_closed_sheet_opens_it_without_pressing_buttons(root):
    check_closed_sheet_drag(root)


def check_sideways_wide_keys(root):
    with sheet(root) as s:
        boot(s)
        x, y = below_handle(s)
        drag(s, x - 80, y, y - 14, steps=5, pause=30, x1=x + 80, release=False)  # mostly sideways, but far enough up to be tempting
        assert not s.page.evaluate("document.getElementById('app').classList.contains('sheet-drag')"), "a sideways drag is not a sheet drag"
        s.page.mouse.up()
        settle(s)
        assert state(s) == "peek"
        s.page.focus("#sheetHandle")
        s.page.keyboard.press("ArrowUp")
        settle(s)
        assert state(s) == "open"
        s.page.keyboard.press("ArrowDown")
        settle(s)
        assert state(s) == "peek"
    for vp in ((1280, 800), (844, 390)):
        with Session(root, viewport=vp, mobile=vp[0] < 1000, touch=vp[0] < 1000) as s:
            boot(s)
            assert s.page.evaluate("window.SEPTA.swipe.active()") is False
            b = s.page.locator("#panel").bounding_box()
            before = s.page.evaluate("document.getElementById('panel').getBoundingClientRect().height")
            drag(s, b["x"] + 80, 300, 120, steps=6, pause=40)
            settle(s)
            assert s.page.evaluate("document.getElementById('app').style.gridTemplateRows") == "" and s.page.evaluate("document.getElementById('panel').getBoundingClientRect().height") == before


def test_sideways_drags_wide_screens_and_keys(root):
    check_sideways_wide_keys(root)
    must_fail(check_sideways_wide_keys, root, ("js/swipe.js", "if (Math.abs(dx) > Math.abs(dy)) {", "if (false) {"))
    must_fail(check_sideways_wide_keys, root, ("js/swipe.js", "sh.setOpen(e.key === 'ArrowUp');", ""))
