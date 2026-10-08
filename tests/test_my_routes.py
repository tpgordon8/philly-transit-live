"""Task 1.1: "My routes" preset (septa.routes.v1) — star routes, map shows only starred by default, toggle shows all."""
import json

from harness import Session

KEY = "septa.routes.v1"


def badges(s):
    return s.page.evaluate("[...document.querySelectorAll('.veh-wrap .rt')].map(e => e.textContent.trim())")


def counts(s):
    return s.page.evaluate("[...document.querySelectorAll('[data-n]')].map(e => +e.textContent)")


def star_first_marker(s):
    route = s.page.evaluate("""() => { const w = document.querySelector('.veh-wrap'); w.click();
        return w.querySelector('.rt').textContent.trim(); }""")
    s.page.click("#starBtn")
    return route


def stored(s):
    return json.loads(s.page.evaluate(f"localStorage.getItem('{KEY}')"))


def boot(s):
    s.open()
    s.wait_live()


def test_default_no_stars_shows_all_and_hint(root):
    with Session(root) as s:
        boot(s)
        n = s.markers()
        assert n >= 20
        assert s.page.locator("#myToggle").count() == 0
        assert "Tap a vehicle, then star its route to build your own view." in s.page.inner_text("#myRoutes")
        assert not s.console_errors, s.console_errors


def test_star_filters_map_and_counts(root):
    with Session(root) as s:
        boot(s)
        total = s.markers()
        before = counts(s)
        route = star_first_marker(s)
        assert s.page.get_attribute("#starBtn", "aria-pressed") == "true"
        assert s.page.get_attribute("#starBtn", "aria-label") == f"Unstar route {route}"
        assert s.page.inner_text("#starBtn").strip() == "Starred"
        assert s.page.inner_text("#myToggle").strip() == "Showing my routes (1)"
        assert s.page.get_attribute("#myToggle", "aria-pressed") == "true"
        b = badges(s)
        assert 0 < len(b) < total and set(b) == {route}, (route, set(b))
        assert sum(counts(s)) == len(b), "mode chip counts must match the map"
        assert sum(counts(s)) < sum(before)
        assert not s.console_errors, s.console_errors


def test_star_persists_across_reload(root):
    with Session(root) as s:
        boot(s)
        route = star_first_marker(s)
        assert stored(s) == {"stars": [route], "onlyMine": True}
        s.page.reload()
        s.wait_live()
        assert set(badges(s)) == {route}
        assert s.page.inner_text("#myToggle").strip() == "Showing my routes (1)"
        assert not s.console_errors, s.console_errors


def test_toggle_shows_all_again(root):
    with Session(root) as s:
        boot(s)
        total = s.markers()
        star_first_marker(s)
        s.page.click("#myToggle")
        assert s.page.inner_text("#myToggle").strip() == "Showing all routes"
        assert s.page.get_attribute("#myToggle", "aria-pressed") == "false"
        assert s.markers() == total
        assert stored(s)["onlyMine"] is False
        s.page.click("#myToggle")
        assert s.page.inner_text("#myToggle").strip() == "Showing my routes (1)"
        assert s.markers() < total


def test_remove_chip_unstars(root):
    with Session(root) as s:
        boot(s)
        total = s.markers()
        route = star_first_marker(s)
        btn = s.page.locator("#myRoutes [data-remove]")
        assert btn.count() == 1
        assert btn.get_attribute("aria-label") == f"Remove route {route} from my routes"
        btn.click()
        assert s.markers() == total
        assert s.page.locator("#myToggle").count() == 0
        assert stored(s)["stars"] == []


def test_empty_state_when_starred_route_not_running(root):
    with Session(root) as s:
        boot(s)
        total = s.markers()
        route = star_first_marker(s)
        bus = s.worker.data["TransitView"]["bus"]
        s.worker.data["TransitView"]["bus"] = [b for b in bus if str(b["route_id"]) != route]
        s.tick(15000)
        assert s.markers() == 0
        box = s.page.locator("#empty")
        assert box.is_visible()
        txt = box.text_content()
        assert "Quiet around here" in txt
        assert "None of your starred routes are running nearby right now." in txt
        assert s.page.inner_text("#emptyAct").strip() == "Show all routes"
        s.page.click("#emptyAct")
        assert s.markers() > 0 and s.page.locator("#empty").is_hidden()
        assert stored(s)["onlyMine"] is False
        assert s.markers() <= total
        assert not s.console_errors, s.console_errors


def test_corrupt_storage_behaves_as_no_stars(root):
    for junk in ("not json", '{"stars":"x","onlyMine":5}', "[1,2]", "null"):
        with Session(root, init_scripts=[f"localStorage.setItem('{KEY}', {json.dumps(junk)})"]) as s:
            boot(s)
            assert s.markers() >= 20, junk
            assert s.page.locator("#myToggle").count() == 0, junk
            assert "Tap a vehicle" in s.page.inner_text("#myRoutes")
            assert not s.console_errors, (junk, s.console_errors)


def test_mobile_no_horizontal_scroll_with_three_routes(root):
    with Session(root, viewport=(390, 844)) as s:
        boot(s)
        routes = s.page.evaluate("[...new Set([...document.querySelectorAll('.veh-wrap .rt')].map(e => e.textContent.trim()))].slice(0, 3)")
        assert len(routes) == 3
        s.page.evaluate("(r) => localStorage.setItem('septa.routes.v1', JSON.stringify({stars: r, onlyMine: true}))", routes)
        s.page.reload()
        s.wait_live()
        assert s.page.locator("#myRoutes [data-remove]").count() == 3
        sw = s.page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth, document.body.scrollWidth]")
        assert sw[0] <= sw[1] and sw[2] <= sw[1], f"horizontal scroll: {sw}"
        assert not s.console_errors, s.console_errors
