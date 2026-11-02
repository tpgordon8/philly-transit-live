"""Light / Dark / System theme switch (index.html head script, the Theme section in More, js/panel.js; ARCHITECTURE.md 16.4): the choice is
saved under septa.theme.v1, applied before the first stylesheet loads (no flash), really changes the colours on a device that prefers the
opposite, keeps the two theme-color tags in step, and the page works with storage blocked."""
import json

from harness import Session
from test_first_run import must_fail, seed

FAST = {
    "test_theme_control_saves_and_applies",
    "test_saved_theme_is_applied_before_first_stylesheet",
    "test_theme_works_with_storage_blocked_or_junk",
}

KEY = "septa.theme.v1"
BG = "getComputedStyle(document.body).backgroundColor"
LIGHT_BG, DARK_BG = "rgb(238, 241, 244)", "rgb(10, 17, 25)"
# records data-theme the moment the first stylesheet <link> reaches the DOM (the head script must already have run)
SPY = """(() => { window.__themeAtCss = 'unset';
  new MutationObserver(m => { for (const r of m) for (const n of r.addedNodes) if (n.nodeName === 'LINK' && n.rel === 'stylesheet' && window.__themeAtCss === 'unset')
    window.__themeAtCss = document.documentElement.getAttribute('data-theme'); }).observe(document, {childList: true, subtree: true}); })()"""


def metas(s):
    return s.page.evaluate("[...document.querySelectorAll('meta[name=theme-color]')].map(m => m.content + '|' + m.media)")


def pressed(s):
    return s.page.evaluate("[...document.querySelectorAll('#themeSeg button')].filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.dataset.themePick)")


def check_control(root):
    for scheme, other in (("dark", "light"), ("light", "dark")):
        with Session(root, color_scheme=scheme) as s:
            s.open()
            s.wait_live()
            assert s.page.evaluate("document.documentElement.hasAttribute('data-theme')") is False, "System is the default: no override"
            assert pressed(s) == ["system"]
            assert s.page.evaluate(BG) == (DARK_BG if scheme == "dark" else LIGHT_BG)
            assert s.page.get_attribute("#themeSeg", "role") == "group" and s.page.get_attribute("#themeSeg", "aria-label") == "Theme"
            assert [b.strip() for b in s.page.eval_on_selector_all("#themeSeg button", "e => e.map(b => b.textContent)")] == ["System", "Light", "Dark"]
            # choose the opposite of the device
            s.page.click("#themeSeg [data-theme-pick='%s']" % other)
            assert s.page.get_attribute("html", "data-theme") == other
            assert s.page.evaluate(BG) == (LIGHT_BG if other == "light" else DARK_BG), "the colours really change"
            assert pressed(s) == [other]
            assert s.page.evaluate("JSON.parse(localStorage.getItem('%s'))" % KEY) == other
            want = "#1f5fae" if other == "light" else "#111b27"
            assert [m.split("|")[0] for m in metas(s)] == [want, want], metas(s)
            # back to System: override and storage value go, the meta tags return to their device-dependent pair
            s.page.click("#themeSeg [data-theme-pick='system']")
            assert s.page.evaluate("document.documentElement.hasAttribute('data-theme')") is False
            assert s.page.evaluate("JSON.parse(localStorage.getItem('%s'))" % KEY) == "system"
            assert s.page.evaluate(BG) == (DARK_BG if scheme == "dark" else LIGHT_BG)
            assert metas(s) == ["#1f5fae|(prefers-color-scheme: light)", "#111b27|(prefers-color-scheme: dark)"], metas(s)
            # a reload remembers the last choice
            s.page.click("#themeSeg [data-theme-pick='dark']")
            s.open()
            s.wait_live()
            assert pressed(s) == ["dark"] and s.page.get_attribute("html", "data-theme") == "dark" and s.page.evaluate(BG) == DARK_BG
            assert not s.console_errors, s.console_errors


def test_theme_control_saves_and_applies(root):
    check_control(root)
    must_fail(check_control, root, ("js/panel.js", "if (pick) root.setAttribute('data-theme', t);", "if (pick) root.removeAttribute('data-theme');"))
    must_fail(check_control, root, ("js/panel.js", "store.set(KEY, t);", ""))


def check_before_paint(root):
    for choice in ("light", "dark"):
        with Session(root, color_scheme="dark" if choice == "light" else "light", init_scripts=[SPY, seed(KEY, json.dumps(choice))]) as s:
            s.open()
            s.wait_live()
            assert s.page.evaluate("window.__themeAtCss") == choice, ("theme set before the first stylesheet", s.page.evaluate("window.__themeAtCss"))
    with Session(root, init_scripts=[SPY]) as s:
        s.open()
        s.wait_live()
        assert s.page.evaluate("window.__themeAtCss") is None, "no saved choice: no override"


def test_saved_theme_is_applied_before_first_stylesheet(root):
    check_before_paint(root)
    must_fail(check_before_paint, root, ("index.html", "d.setAttribute(\"data-theme\",t);var m=", "var m="))


def check_storage_blocked(root):
    blocked = "Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('blocked', 'SecurityError'); }})"
    with Session(root, color_scheme="dark", init_scripts=[blocked]) as s:
        s.open()
        s.page.wait_for_selector("#themeSeg", state="attached")
        assert s.page.evaluate("document.documentElement.hasAttribute('data-theme')") is False
        s.page.evaluate("document.querySelector('#themeSeg [data-theme-pick=light]').click()")
        assert s.page.get_attribute("html", "data-theme") == "light", "the choice still works for this visit"
    for junk in ("{not json", '"purple"', "42", "null", '{"a":1}'):
        raw = "localStorage.setItem('%s', %s)" % (KEY, json.dumps(junk))
        with Session(root, color_scheme="dark", init_scripts=[raw]) as s:
            s.open()
            s.wait_live()
            assert s.page.evaluate("document.documentElement.hasAttribute('data-theme')") is False, junk
            assert pressed(s) == ["system"], junk
            assert s.page.evaluate(BG) == DARK_BG
            assert not s.console_errors, (junk, s.console_errors)


def test_theme_works_with_storage_blocked_or_junk(root):
    check_storage_blocked(root)
    must_fail(check_storage_blocked, root, ("index.html", "(function(){try{var t=JSON.parse(localStorage", "(function(){var t=JSON.parse(localStorage"))
