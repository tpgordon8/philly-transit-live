"""Planner routing and Indego go through the Worker first, with ONE fallback to the direct provider
(ARCHITECTURE.md 13.2 WP1). The mock Worker and the mock providers live in tests/harness.py (Mocks.worker_mode etc.)."""
from harness import Session

FAST = {
    "test_w_worker_first_no_direct_calls",
    "test_w_route_falls_back_once_on_worker_5xx_or_network_error",
    "test_w_worker_404_older_worker_falls_back",
    "test_w_worker_422_noroute_is_an_answer_not_an_outage",
    "test_w_cancel_plan_drops_queue_aborts_inflight_and_frees_slots",
}
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
        for mode in ("http502", "abort"):
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
        s.mocks.worker_mode = "http502"
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
        for mode in ("http502", "abort"):
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


def test_w_worker_404_older_worker_falls_back(root):
    """A Worker that predates /route and /indego answers 404; the page must still plan through the direct provider."""
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.worker_mode = "http404"
        r = s.page.evaluate(ROUTE_JS, [A, B])
        assert "meters" in r, r
        i = s.page.evaluate(INDEGO_JS)
        assert i.get("n", 0) > 0, i
        assert len(s.mocks.direct_routing_hits) == 1 and len(s.mocks.direct_indego_hits) >= 1


def test_w_worker_422_noroute_is_an_answer_not_an_outage(root):
    """B1: OSRM sends HTTP 400 for NoRoute; the Worker passes it on as 422. The page must read it and must NOT re-send the
    coordinates to the third party."""
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.worker_mode = "noroute"
        r = s.page.evaluate(ROUTE_JS, [A, B])
        assert r == {"err": "no_route"}, r
        assert len(s.mocks.worker_route_hits) == 1
        assert s.mocks.direct_routing_hits == [], "a 422 answer must never be re-sent to the provider"
        # the same through a provider that answers 400 {code: NoRoute} behind a healthy Worker
        s.mocks.worker_mode = "ok"
        s.mocks.routing_mode = "noroute"
        s.mocks.worker_route_hits.clear()
        s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches()")
        assert s.page.evaluate(ROUTE_JS, [A, B]) == {"err": "no_route"}
        assert len(s.mocks.worker_route_hits) == 1 and s.mocks.direct_routing_hits == []


def test_w_worker_500_and_other_non_listed_statuses_are_final(root):
    """Only a network error, 404 and 502/503/504 fall back; a plain 500 from the Worker does not."""
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.worker_mode = "http500"
        assert s.page.evaluate(ROUTE_JS, [A, B]) == {"err": "routing_unavailable"}
        assert len(s.mocks.worker_route_hits) == 1 and s.mocks.direct_routing_hits == []


def test_w_direct_fallback_reads_osrm_noroute_without_retry(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.worker_mode = "abort"
        s.mocks.routing_mode = "noroute"
        assert s.page.evaluate(ROUTE_JS, [A, B]) == {"err": "no_route"}
        assert len(s.mocks.direct_routing_hits) == 1, "an HTTP 400 NoRoute answer is final: no retry"
        assert s.mocks.direct_routing_hits[0]["from"] == (A["lat"], A["lng"]), "the fallback carries the page's 5 dp coordinates"


PACE_JS = """async () => {
    const T = window.__SEPTA_TEST__, f = window.fetch, starts = [];
    let live = 0, peak = 0;
    window.fetch = function (u, o) {
        if (!String(u).includes('/route/')) return f.call(window, u, o);
        starts.push(performance.now()); live++; peak = Math.max(peak, live);
        return new Promise(res => setTimeout(res, 120)).then(() => { live--; return f.call(window, u, o); });
    };
    const ctx = {};
    const ps = [];
    for (let i = 0; i < 6; i++) ps.push(T.routeLeg('foot', {lat: 39.94 + i * 0.001, lng: -75.16}, {lat: 39.95, lng: -75.15}, ctx));
    await Promise.all(ps);
    window.fetch = f;
    return {gaps: starts.slice(1).map((t, i) => t - starts[i]), peak, n: starts.length};
}"""


def test_w_routing_queue_is_paced(root):
    """S2: at most 2 in flight and at least 250 ms between starts (FOSSGIS asks for about 1 request per second)."""
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        r = s.page.evaluate(PACE_JS)
        assert r["n"] == 6 and r["peak"] <= 2, r
        assert all(g >= 235 for g in r["gaps"]), r["gaps"]
        assert s.page.evaluate("window.__SEPTA_TEST__.TP.MAX_INFLIGHT") == 2 and s.page.evaluate("window.__SEPTA_TEST__.TP.GAP_MS") == 250


CANCEL_JS = """async () => {
    const T = window.__SEPTA_TEST__, f = window.fetch, started = [];
    let aborted = 0, hang = true;
    window.fetch = function (u, o) {
        if (!String(u).includes('/route/')) return f.call(window, u, o);
        started.push(performance.now());
        if (!hang) return f.call(window, u, o);
        return new Promise((res, rej) => o.signal.addEventListener('abort', () => { aborted++; rej(new DOMException('x', 'AbortError')); }));
    };
    const pt = i => ({lat: 39.94 + i * 0.001, lng: -75.16});
    const A = {}, codes = [];
    const ps = [];
    for (let i = 0; i < 6; i++) ps.push(T.routeLeg('foot', pt(i), {lat: 39.96, lng: -75.15}, A).then(() => 'ok', e => e && e.code));
    await new Promise(r => setTimeout(r, 700));
    const before = started.length;
    T.cancelPlan(A);
    const outcomes = await Promise.all(ps);
    hang = false;
    const t0 = performance.now(), n0 = started.length;
    const B = {};
    const r = await T.routeLeg('foot', pt(9), {lat: 39.96, lng: -75.15}, B);
    window.fetch = f;
    return {before, outcomes, aborted, startedAfter: started.length - n0, bStartDelay: started[n0] - t0, meters: r.meters, deadFlag: A.dead};
}"""


def test_w_cancel_plan_drops_queue_aborts_inflight_and_frees_slots(root):
    """S5: a cancelled plan's queued calls are dropped (never fetched), its in-flight requests are aborted, and the next plan
    starts at once instead of waiting behind them."""
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        r = s.page.evaluate(CANCEL_JS)
        assert r["before"] == 2, r                              # two slots, both hung
        assert r["outcomes"] == ["routing_unavailable"] * 6, r  # in-flight and queued all ended
        assert r["aborted"] == 2, r                             # the two in-flight requests were aborted
        assert r["startedAfter"] == 1, r                        # nothing queued from the dead plan was ever fetched
        assert r["bStartDelay"] < 400 and r["meters"] > 0, r    # the new plan did not wait behind dead items
        assert r["deadFlag"] is True


def test_w_out_of_region_points_never_reach_the_network(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        n = s.page.evaluate("""async () => { const T = window.__SEPTA_TEST__, out = [];
            for (const [o, d] of [[{lat: 40.7, lng: -74.0}, {lat: 39.95, lng: -75.15}], [{lat: 39.95, lng: -75.15}, {lat: 39.5, lng: -75.15}],
                                  [{lat: 39.95, lng: -75.95}, {lat: 39.95, lng: -75.15}], [{lat: 39.95, lng: -75.15}, {lat: 39.95, lng: -74.4}]]) {
                try { await T.planTrips(o, d, {vehicles: []}); out.push('planned'); } catch (e) { out.push(e && e.code); } }
            out.push(T.inRegion({lat: 40.4, lng: -75.9}), T.inRegion({lat: 39.6, lng: -74.5}), T.inRegion({lat: 40.41, lng: -75}), T.inRegion({lat: NaN, lng: -75}));
            return out; }""")
        assert n == ["out_of_area"] * 4 + [True, True, False, False], n
        assert s.mocks.worker_route_hits == [] and s.mocks.direct_routing_hits == [] and s.mocks.worker_indego_hits == []
