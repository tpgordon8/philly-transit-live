"""Planner routing and Indego go through the Worker first, with ONE fallback to the direct provider
(ARCHITECTURE.md 13.2 WP1). The mock Worker and the mock providers live in tests/harness.py (Mocks.worker_mode etc.)."""
from harness import Session
from test_planner_core import HOOK, open_session

A = {"lat": 39.94, "lng": -75.16}
B = {"lat": 39.95, "lng": -75.15}
ROUTE_JS = """async ([a, b]) => { try { const r = await window.__SEPTA_TEST__.routeLeg('foot', a, b); return {meters: r.meters}; }
    catch (e) { return {err: e && e.code ? e.code : String(e)}; } }"""
INDEGO_JS = """async () => { const T = window.__SEPTA_TEST__; T.resetPlannerCaches();
    try { const r = await T.loadIndego(true); return {n: r.length}; } catch (e) { return {err: e && e.code ? e.code : String(e)}; } }"""


def test_w_worker_first_no_direct_calls(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        r = s.page.evaluate(ROUTE_JS, [A, B])
        assert r["meters"] > 0, r
        i = s.page.evaluate(INDEGO_JS)
        assert i["n"] > 0, i
        assert len(s.mocks.worker_route_hits) == 1 and s.mocks.worker_route_hits[0]["profile"] == "foot"
        assert s.mocks.worker_route_hits[0]["raw"].endswith("/route/foot?from=39.94000,-75.16000&to=39.95000,-75.15000"), s.mocks.worker_route_hits
        assert sorted(s.mocks.worker_indego_hits) == ["information", "status"], s.mocks.worker_indego_hits
        assert s.mocks.direct_routing_hits == [] and s.mocks.direct_indego_hits == [], "no direct provider call while the Worker answers"
        assert not s.unexpected and not s.septa_direct


def test_w_all_profiles_through_worker(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        for prof in ("foot", "bike", "car"):
            r = s.page.evaluate("async ([a, b, p]) => (await window.__SEPTA_TEST__.routeLeg(p, a, b)).meters", [A, B, prof])
            assert r > 0
        assert [h["profile"] for h in s.mocks.worker_route_hits] == ["foot", "bike", "car"]
        assert s.mocks.direct_routing_hits == []


def test_w_route_falls_back_once_on_worker_5xx_or_network_error(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        for mode in ("http500", "abort"):
            s.mocks.worker_mode = mode
            s.mocks.worker_route_hits.clear()
            s.mocks.direct_routing_hits.clear()
            s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches()")
            r = s.page.evaluate(ROUTE_JS, [A, B])
            assert r.get("meters", 0) > 0, (mode, r)
            assert len(s.mocks.worker_route_hits) == 1, (mode, "the Worker is tried once, not retried")
            assert len(s.mocks.direct_routing_hits) == 1, (mode, "exactly one fallback call")
            assert s.mocks.direct_routing_hits[0]["profile"] == "foot"


def test_w_route_worker_and_provider_both_down(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.worker_mode = "http500"
        s.mocks.routing_mode = "http500"
        r = s.page.evaluate(ROUTE_JS, [A, B])
        assert r == {"err": "routing_unavailable"}, r
        assert len(s.mocks.worker_route_hits) == 1
        assert len(s.mocks.direct_routing_hits) == 2, "fallback keeps the direct client's own single retry, nothing more"


def test_w_route_provider_down_behind_healthy_worker_falls_back(root):
    # Worker answers 502 (its upstream failed): that is a 5xx, so the page asks the provider directly once.
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.routing_mode = "http500"
        r = s.page.evaluate(ROUTE_JS, [A, B])
        assert r == {"err": "routing_unavailable"}
        assert len(s.mocks.worker_route_hits) == 1 and len(s.mocks.direct_routing_hits) == 2


def test_w_worker_4xx_is_final_no_fallback(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.worker_mode = "http400"
        r = s.page.evaluate(ROUTE_JS, [A, B])
        assert r == {"err": "routing_unavailable"}, r
        i = s.page.evaluate(INDEGO_JS)
        assert i == {"err": "indego_unavailable"}, i
        assert s.mocks.direct_routing_hits == [] and s.mocks.direct_indego_hits == [], "a 4xx from the Worker is not retried elsewhere"


def test_w_indego_falls_back_once(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        for mode in ("http500", "abort"):
            s.mocks.worker_mode = mode
            s.mocks.worker_indego_hits.clear()
            s.mocks.direct_indego_hits.clear()
            i = s.page.evaluate(INDEGO_JS)
            assert i.get("n", 0) > 0, (mode, i)
            assert sorted(s.mocks.worker_indego_hits) == ["information", "status"], mode
            assert sorted(s.mocks.direct_indego_hits) == ["station_information", "station_status"], (mode, s.mocks.direct_indego_hits)


def test_w_plan_still_works_with_worker_down(root):
    from test_planner_core import O, D, plan, ok
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.worker_mode = "abort"
        res = ok(plan(s, O, D, []))
        assert any(o["structure"] == "walk" for o in res["options"]), [o["structure"] for o in res["options"]]
        assert s.mocks.direct_routing_hits, "fallback carried the routing"
