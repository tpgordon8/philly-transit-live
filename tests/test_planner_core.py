"""Trip planner core (ARCHITECTURE.md section 12): data clients and pure planner functions, no UI.

Everything is hermetic: Indego GBFS (real snapshot in fixtures), the OSM routing service (deterministic fake: straight-line
x 1.25, foot 1.25 m/s, bike 3.6 m/s, car 8 m/s) and a synthetic bus network (tests/fixtures/bus-network.test.json) come from
tests/harness.py. Live vehicles are passed in through opts.vehicles, shaped like normBuses output.
"""
import copy
import json
import math

from harness import FIX, Session, haversine_m

# Fast subset run by `tests/run.py --fast`; every other test_* function here is full-only (see README).
FAST = {
    "test_a_load_network_rejects_malformed_and_indexes_good",
    "test_a_route_leg_client",
    "test_c_walk_bus_walk_stops_ride_and_live_wait",
    "test_e_legs_sum_to_total_and_have_paths",
}

HOOK = "window.__SEPTA_TEST__ = true"
NET = json.loads((FIX / "bus-network.test.json").read_text())
STOPS = NET["stops"]
PAT = {p["id"]: p for p in NET["patterns"]}
NB = PAT["X47-0-1"]          # S1..S13 northbound, mins 0,1,2.5,3.5,5,6,7.5,8.5,10,11,12.5,13.5,15, hw 10
MLNG = 111195 * math.cos(math.radians(39.945))

# Walk-bus-walk scenario: start 20 m west of stop S5 (index 4), finish 20 m west of stop S12 (index 11).
O = {"lat": 39.94, "lng": -75.15824}
D = {"lat": 39.9575, "lng": -75.15824}


def hav(a, b):
    return haversine_m(a[0], a[1], b[0], b[1])


def stop_ll(sid):
    return STOPS[sid][0], STOPS[sid][1]


def veh(key, route, next_id, lat=39.94, lng=-75.158):
    return {"key": key, "kind": "bus", "route": route, "lat": lat, "lng": lng, "nextId": next_id, "late": 0, "vid": key}


def open_session(s, network=NET):
    s.mocks.network = copy.deepcopy(network)
    s.worker.data["TransitView"] = {"bus": []}
    s.open()
    s.wait_live()


def plan(s, o, d, vehicles=None):
    return s.page.evaluate("""async ([o, d, v]) => {
        const T = window.__SEPTA_TEST__;
        try { return {ok: await T.planTrips(o, d, v === null ? {} : {vehicles: v})}; }
        catch (e) { return {err: e && e.code ? e.code : String(e)}; }
    }""", [o, d, vehicles])


def ok(res):
    assert "ok" in res, res
    return res["ok"]


def by_structure(plan_ok, structure):
    return [o for o in plan_ok["options"] if o["structure"] == structure]


def no_bikes(s):
    s.mocks.set_all(bikes=0, docks=0)


def station(s, name):
    return next(x for x in s.mocks.stations() if x["name"] == name)


def sll(st):
    return st["lat"], st["lon"]


def walk_min(a, b):
    return hav(a, b) * 1.25 / 1.25 / 60


# ---------------------------------------------------------------- (a) network client and stop index
def test_a_load_network_rejects_malformed_and_indexes_good(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        bads = {}
        n = copy.deepcopy(NET); n["v"] = 2; bads["version"] = n
        n = copy.deepcopy(NET); del n["patterns"]; bads["no patterns"] = n
        n = copy.deepcopy(NET); n["patterns"][0]["mins"] = n["patterns"][0]["mins"][:-1]; bads["mins length"] = n
        n = copy.deepcopy(NET); n["patterns"][0]["stops"][2] = "NOPE"; bads["unknown stop"] = n
        n = copy.deepcopy(NET); n["patterns"][0]["mins"][3] = 0; bads["mins decreasing"] = n
        n = copy.deepcopy(NET); n["stops"]["S1"] = ["x", 1, "bad"]; bads["bad coords"] = n
        for name, bad in bads.items():
            s.mocks.network = bad
            code = s.page.evaluate("""async () => { const T = window.__SEPTA_TEST__; T.resetPlannerCaches();
                try { await T.loadNetwork(); return 'resolved'; } catch (e) { return e.code; } }""")
            assert code == "network_unavailable", (name, code)
        # a failure is not cached: the next call with a good file succeeds
        s.mocks.network = NET
        info = s.page.evaluate("""async () => { const T = window.__SEPTA_TEST__; const r = await T.loadNetwork();
            return {stops: Object.keys(r.index.stops).length, patterns: Object.keys(r.index.patterns).length,
                    routes: Object.keys(r.index.byRoute).sort(), gen: r.net.generated}; }""")
        assert info["stops"] == len(STOPS) and info["patterns"] == len(PAT)
        assert info["routes"] == ["X45", "X47", "X99"] and info["gen"] == NET["generated"]
        hits = s.mocks.network_hits
        s.page.evaluate("window.__SEPTA_TEST__.loadNetwork()")
        assert s.mocks.network_hits == hits, "the parsed network is cached for the page session"
        assert not s.unexpected, s.unexpected


def test_a_network_http_failure_rejects(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.network_mode = "http500"
        code = s.page.evaluate("""async () => { const T = window.__SEPTA_TEST__; T.resetPlannerCaches();
            try { await T.loadNetwork(); return 'resolved'; } catch (e) { return e.code; } }""")
        assert code == "network_unavailable"
        assert s.mocks.network_hits == 2, "one retry"


def test_a_nearby_stops_radius(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        pts = [(39.9400, -75.1582), (39.9477, -75.1550), (39.9301, -75.1610), (39.9650, -75.1500), (39.9475, -75.1545)]
        for lat, lng in pts:
            for radius in (50, 200, 300, 600, 1000, 2500):
                got = s.page.evaluate("""async ([lat, lng, r]) => { const T = window.__SEPTA_TEST__; const x = await T.loadNetwork();
                    return T.nearbyStops(x.index, {lat, lng}, r).map(s => [s.id, s.d]); }""", [lat, lng, radius])
                want = sorted((hav((lat, lng), stop_ll(i)), i) for i in STOPS if hav((lat, lng), stop_ll(i)) <= radius)
                assert [g[0] for g in got] == [w[1] for w in want], (lat, lng, radius, len(got), len(want))
                assert all(abs(g[1] - w[0]) < 0.5 for g, w in zip(got, want))
        # exact boundary: a radius just under / just over the distance to S5
        d = hav((39.94, -75.15824), stop_ll("S5"))
        for r, expect in ((d - 0.5, False), (d + 0.5, True)):
            got = s.page.evaluate("""async ([r]) => { const T = window.__SEPTA_TEST__; const x = await T.loadNetwork();
                return T.nearbyStops(x.index, {lat: 39.94, lng: -75.15824}, r).map(s => s.id); }""", [r])
            assert ("S5" in got) == expect, (r, got)


# ---------------------------------------------------------------- clients: Indego and routing
def test_a_indego_client_merge_flags_and_freshness(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        a, b = s.mocks.stations()[0], s.mocks.stations()[1]
        s.mocks.set_station(a["station_id"], bikes=4, docks=7)
        s.mocks.set_station(b["station_id"], bikes=3, docks=2, renting=False)
        st = s.page.evaluate("async () => { const r = await window.__SEPTA_TEST__.loadIndego(true); return {n: r.length, asOf: r.asOf, s: r}; }")
        assert st["n"] == len(s.mocks.stations()) and st["asOf"] > 0
        ma = next(x for x in st["s"] if x["id"] == a["station_id"])
        assert (ma["bikes"], ma["docks"], ma["ebikes"] + ma["classic"]) == (4, 7, 4) and ma["name"] == a["name"]
        assert ma["lat"] == a["lat"] and ma["lon"] == a["lon"] and ma["renting"] and ma["returning"]
        mb = next(x for x in st["s"] if x["id"] == b["station_id"])
        assert mb["renting"] is False and mb["returning"] is True
        # not-installed stations are never usable
        s.mocks.set_station(a["station_id"], installed=False)
        near = s.page.evaluate("""async ([lat, lng]) => { const T = window.__SEPTA_TEST__; const r = await T.loadIndego(true);
            return [T.nearbyStations(r, {lat, lng}, 30, 'bike').map(x => x.id), T.nearbyStations(r, {lat, lng}, 30, null).map(x => x.id)]; }""",
                               [a["lat"], a["lon"]])
        assert a["station_id"] not in near[0] and a["station_id"] not in near[1]
        # information is cached for the session, status per call with fresh and reused under 60 s otherwise
        assert s.mocks.indego_hits.count("station_information") == 1
        before = s.mocks.indego_hits.count("station_status")
        s.page.evaluate("window.__SEPTA_TEST__.loadIndego(false)")
        assert s.mocks.indego_hits.count("station_status") == before, "under 60 s old is reused"
        s.page.evaluate("window.__SEPTA_TEST__.loadIndego(true)")
        assert s.mocks.indego_hits.count("station_status") == before + 1
        s.page.clock.fast_forward(61000)
        s.page.evaluate("window.__SEPTA_TEST__.loadIndego(false)")
        assert s.mocks.indego_hits.count("station_status") == before + 2, "older than 60 s is fetched again"


def test_a_indego_failure_rejects(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        for mode in ("http500", "abort"):
            s.mocks.indego_mode = mode
            code = s.page.evaluate("""async () => { const T = window.__SEPTA_TEST__; T.resetPlannerCaches();
                try { await T.loadIndego(true); return 'resolved'; } catch (e) { return e.code; } }""")
            assert code == "indego_unavailable", (mode, code)


def test_a_route_leg_client(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        a, b = {"lat": 39.9400, "lng": -75.1600}, {"lat": 39.9500, "lng": -75.1500}
        want_m = hav((a["lat"], a["lng"]), (b["lat"], b["lng"])) * 1.25
        for prof, mps in (("foot", 1.25), ("bike", 3.6), ("car", 8.0)):
            r = s.page.evaluate("([a, b, p]) => window.__SEPTA_TEST__.routeLeg(p, a, b)", [a, b, prof])
            assert abs(r["meters"] - want_m) < 1 and abs(r["seconds"] - want_m / mps) < 0.5, (prof, r)
            assert r["path"][0] == [a["lat"], a["lng"]] and r["path"][-1] == [b["lat"], b["lng"]] and len(r["path"]) == 3
        assert [h["profile"] for h in s.mocks.routing_hits] == ["foot", "bike", "car"]
        assert s.mocks.routing_hits[0]["from"] == (a["lat"], a["lng"]) and s.mocks.routing_hits[0]["to"] == (b["lat"], b["lng"])
        # cache: same pair, and endpoints that round to the same 5 dp, do not hit the service again
        s.page.evaluate("([a, b]) => window.__SEPTA_TEST__.routeLeg('foot', a, b)", [a, b])
        a2 = {"lat": a["lat"] + 0.000001, "lng": a["lng"] - 0.000001}
        s.page.evaluate("([a, b]) => window.__SEPTA_TEST__.routeLeg('foot', a, b)", [a2, b])
        assert len(s.mocks.routing_hits) == 3
        # the reverse direction and other profiles are different keys
        s.page.evaluate("([a, b]) => window.__SEPTA_TEST__.routeLeg('foot', b, a)", [a, b])
        assert len(s.mocks.routing_hits) == 4
        # at most three requests in flight
        s.page.evaluate("""() => { window.__maxIn = 0; window.__in = 0; const f = window.fetch;
            window.fetch = function (u, o) { if (!String(u).includes('routing.openstreetmap.de') && !String(u).includes('/route/')) return f.call(window, u, o);
                window.__in++; window.__maxIn = Math.max(window.__maxIn, window.__in);
                return f.call(window, u, o).finally(() => { window.__in--; }); }; }""")
        n = s.page.evaluate("""async () => { const T = window.__SEPTA_TEST__; const ps = [];
            for (let i = 0; i < 10; i++) ps.push(T.routeLeg('foot', {lat: 39.9 + i * 0.001, lng: -75.1}, {lat: 39.91, lng: -75.12 + i * 0.001}));
            const r = await Promise.all(ps); return r.length; }""")
        assert n == 10 and s.page.evaluate("window.__maxIn") <= 3 and s.page.evaluate("window.__maxIn") >= 2
        assert len(s.mocks.routing_hits) == 14


def test_a_route_leg_failures(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        a, b = {"lat": 39.94, "lng": -75.16}, {"lat": 39.95, "lng": -75.15}
        for mode in ("http500", "abort"):
            s.mocks.routing_mode = mode
            s.mocks.routing_hits.clear()
            code = s.page.evaluate("""async ([a, b]) => { try { await window.__SEPTA_TEST__.routeLeg('foot', a, b); return 'resolved'; }
                catch (e) { return e.code; } }""", [a, b])
            assert code == "routing_unavailable" and len(s.mocks.routing_hits) == 2, (mode, code, s.mocks.routing_hits)
        # a failure is not cached
        s.mocks.routing_mode = "ok"
        r = s.page.evaluate("([a, b]) => window.__SEPTA_TEST__.routeLeg('foot', a, b)", [a, b])
        assert r["meters"] > 0


# ---------------------------------------------------------------- (b) bike structure
def pick_bike_scenario(s):
    """Stations around a start and a finish, with the nearest ones deliberately empty."""
    o, d = (39.9400, -75.1620), (39.9575, -75.1620)
    sts = s.mocks.stations()
    near_o = sorted(sts, key=lambda x: hav(o, sll(x)))
    near_d = sorted(sts, key=lambda x: hav(d, sll(x)))
    return o, d, near_o, near_d


def test_b_bike_only_picks_nearest_with_bike_and_dock_with_overheads(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        o, d, near_o, near_d = pick_bike_scenario(s)
        no_bikes(s)
        # the nearest to the start has no bike; the second nearest does. Same idea at the finish for docks.
        s1 = near_o[1]
        s2 = near_d[1]
        s.mocks.set_station(s1["station_id"], bikes=5, docks=0)
        s.mocks.set_station(s2["station_id"], bikes=0, docks=6)
        res = ok(plan(s, {"lat": o[0], "lng": o[1]}, {"lat": d[0], "lng": d[1]}, []))
        bk = by_structure(res, "walk-bike-walk")
        assert len(bk) == 1, res["options"]
        legs = bk[0]["legs"]
        assert [l["mode"] for l in legs] == ["walk", "bike", "walk"]
        assert legs[0]["to"]["name"] == s1["name"] and legs[1]["from"]["name"] == s1["name"]
        assert legs[1]["to"]["name"] == s2["name"] and legs[2]["from"]["name"] == s2["name"]
        assert (legs[0]["to"]["lat"], legs[0]["to"]["lng"]) == sll(s1)
        # exact minutes: routed seconds, with 90 s unlock and 60 s dock inside the bike leg
        bike_sec = hav(sll(s1), sll(s2)) * 1.25 / 3.6
        assert legs[1]["minutes"] == math.ceil((bike_sec + 150) / 60 - 1e-9), (legs[1]["minutes"], bike_sec)
        assert legs[0]["minutes"] == math.ceil(walk_min(o, sll(s1)) - 1e-9)
        assert legs[2]["minutes"] == math.ceil(walk_min(sll(s2), d) - 1e-9)
        assert any("unlock" in n and "dock" in n for n in legs[1]["notes"]), legs[1]["notes"]
        assert not any("Indego counts" in n for n in legs[1]["notes"]), "counts are data on the leg, not note text"
        for side, st_ in (("from", s1), ("to", s2)):
            got = legs[1]["stations"][side]
            sid = next(x for x in s.mocks.indego_status["data"]["stations"] if x["station_id"] == st_["station_id"])
            assert got == {"name": st_["name"], "bikes": sid["num_bikes_available"], "ebikes": sid["num_bikes_available_types"]["electric"],
                           "docks": sid["num_docks_available"], "asOf": got["asOf"]} and got["asOf"] > 0, (side, got)
        assert legs[1]["stations"]["from"]["bikes"] == 5 and legs[1]["stations"]["to"]["docks"] == 6
        assert "stations" not in legs[0] and "stations" not in legs[2]
        assert all(l["basis"] == "routed" for l in legs)
        hits = [(h["profile"], h["from"], h["to"]) for h in s.mocks.routing_hits]
        assert ("foot", o, sll(s1)) in hits and ("bike", sll(s1), sll(s2)) in hits and ("foot", sll(s2), d) in hits
        # walk and car are always there
        assert by_structure(res, "walk") and by_structure(res, "car")
        assert res["asOf"]["indego"] > 0


def test_b_nearest_wins_among_several(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        o, d, near_o, near_d = pick_bike_scenario(s)
        no_bikes(s)
        n = near_o[0]
        far = [x for x in near_o[1:] if hav(o, sll(x)) > hav(o, sll(n)) and hav(d, sll(x)) > hav(d, sll(n))][:2]
        for x in [n] + far:
            s.mocks.set_station(x["station_id"], bikes=2)
        m = near_d[0]
        far_d = [x for x in near_d[1:] if hav(d, sll(x)) > hav(d, sll(m)) and hav(o, sll(x)) > hav(o, sll(m))][:2]
        for x in [m] + far_d:
            s.mocks.set_station(x["station_id"], docks=3)
        res = ok(plan(s, {"lat": o[0], "lng": o[1]}, {"lat": d[0], "lng": d[1]}, []))
        legs = by_structure(res, "walk-bike-walk")[0]["legs"]
        assert legs[0]["to"]["name"] == n["name"], (legs[0]["to"]["name"], n["name"])
        assert legs[2]["from"]["name"] == m["name"]


def test_b_bike_dropped_without_bikes_or_docks(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        o, d, near_o, near_d = pick_bike_scenario(s)
        # no bike anywhere (docks everywhere)
        s.mocks.set_all(bikes=0, docks=5)
        res = ok(plan(s, {"lat": o[0], "lng": o[1]}, {"lat": d[0], "lng": d[1]}, []))
        assert not by_structure(res, "walk-bike-walk")
        assert any(n["code"] == "no_indego_bike" and "No Indego bike available near the start" in n["text"] for n in res["notes"]), res["notes"]
        assert by_structure(res, "walk") and by_structure(res, "car")
        # bikes everywhere, no dock anywhere
        s.mocks.set_all(bikes=5, docks=0)
        res = ok(plan(s, {"lat": o[0], "lng": o[1]}, {"lat": d[0], "lng": d[1]}, []))
        assert not by_structure(res, "walk-bike-walk")
        assert any(n["code"] == "no_indego_dock" and "No free Indego dock near the destination" in n["text"] for n in res["notes"]), res["notes"]
        # a station that has bikes but whose renting flag is off does not count
        s.mocks.set_all(bikes=0, docks=5)
        for x in near_o[:6]:
            s.mocks.set_station(x["station_id"], bikes=4, renting=False)
        res = ok(plan(s, {"lat": o[0], "lng": o[1]}, {"lat": d[0], "lng": d[1]}, []))
        assert not by_structure(res, "walk-bike-walk"), "is_renting=0 stations are not usable"


def test_b_indego_unavailable_keeps_walk_car_and_bus(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.indego_mode = "http500"
        res = ok(plan(s, O, D, [veh("a", "X47", "S1")]))
        structs = {o["structure"] for o in res["options"]}
        assert {"walk", "car", "walk-bus-walk"} <= structs, structs
        assert not any("bike" in x for x in structs)
        assert any(n["code"] == "indego_unavailable" and "Indego bike data unavailable" in n["text"] for n in res["notes"]), res["notes"]
        assert res["asOf"]["indego"] is None


# ---------------------------------------------------------------- (c) bus only
def bus_leg(option):
    return next(l for l in option["legs"] if l["mode"] == "bus")


def expected_wait(pat, bi, t_arr, vehicles):
    best = None
    for v in vehicles:
        if v["route"] != pat["route"]:
            continue
        idx = [i for i in range(bi + 1) if pat["stops"][i] == v["nextId"]]
        if not idx:
            continue
        t = pat["mins"][bi] - pat["mins"][idx[-1]]
        if t < t_arr - 1:
            continue
        if best is None or t < best[0]:
            best = (t, v["key"])
    return (max(0, best[0] - t_arr), best[1]) if best else None


def test_c_walk_bus_walk_stops_ride_and_live_wait(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        vs = [veh("vA", "X47", "S1"), veh("vB", "X47", "S3"), veh("vC", "X47", "S6"), veh("vD", "X47", "M10"), veh("vE", "X45", "E1")]
        res = ok(plan(s, O, D, vs))
        wbw = [o for o in by_structure(res, "walk-bus-walk") if bus_leg(o)["route"] == "X47"]
        assert wbw, [o["structure"] for o in res["options"]]
        opt = wbw[0]          # the fastest X47 option
        legs = opt["legs"]
        assert [l["mode"] for l in legs] == ["walk", "bus", "walk"]
        bus = legs[1]
        assert bus["patternId"] == "X47-0-1" and bus["route"] == "X47" and bus["head"] == "North Terminal"
        assert (bus["fromIdx"], bus["toIdx"], bus["stops"]) == (4, 11, 7), bus
        assert bus["from"]["name"] == STOPS["S5"][2] and bus["to"]["name"] == STOPS["S12"][2]
        # ride minutes come from mins
        assert bus["rideMin"] == NB["mins"][11] - NB["mins"][4] == 8.5
        # the wait is the earliest upstream vehicle at or after our arrival: vB (next stop S3), not vA, not vC (already past)
        t_arr = walk_min(stop_ll("S5"), (O["lat"], O["lng"]))
        assert abs(bus["arriveMin"] - t_arr) < 0.02, (bus["arriveMin"], t_arr)
        want, key = expected_wait(NB, 4, bus["arriveMin"], vs)
        assert key == "vB"
        assert bus["basis"] == "live" and bus["vehicleKey"] == "vB" and bus["waitBasis"] == "live"
        assert abs(bus["waitMin"] - want) < 1e-9 and abs(bus["waitMin"] - (NB["mins"][4] - NB["mins"][2] - bus["arriveMin"])) < 1e-9
        assert bus["minutes"] == math.ceil(bus["waitMin"] + 1 + 8.5 - 1e-9)
        assert any("Includes 60 s to board" in n for n in bus["notes"]) and any("scheduled" in n for n in bus["notes"])
        # straight segments through the stops between boarding and alighting
        assert bus["path"] == [list(stop_ll(f"S{i}")) for i in range(5, 13)]
        assert all(l["basis"] == "routed" for l in (legs[0], legs[2]))
        assert legs[2]["to"]["lat"] == D["lat"] and legs[0]["from"]["lat"] == O["lat"]


def test_c_typical_wait_without_upstream_vehicle(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        # one vehicle already past the boarding stop, one heading the other way: the route is running, nothing is upstream
        vs = [veh("p", "X47", "S7"), veh("q", "X47", "M10")]
        res = ok(plan(s, O, D, vs))
        opt = next(o for o in by_structure(res, "walk-bus-walk") if bus_leg(o)["route"] == "X47")
        bus = bus_leg(opt)
        assert bus["basis"] == "typical" and bus["vehicleKey"] is None and bus["waitBasis"] == "typical"
        assert bus["waitMin"] == NB["hw"] / 2 == 5
        assert bus["minutes"] == math.ceil(5 + 1 + bus["rideMin"] - 1e-9)
        assert any("typical" in n for n in bus["notes"])
        # a vehicle upstream but too early (it will already have passed when we arrive): typical as well
        far = {"lat": O["lat"], "lng": O["lng"] - 0.0047}      # about 400 m further west, 6+ minutes of walking
        res = ok(plan(s, far, D, [veh("early", "X47", "S3")]))
        for o in res["options"]:
            if o["structure"] == "walk-bus-walk" and bus_leg(o)["route"] == "X47":
                b = bus_leg(o)
                want = expected_wait(PAT[b["patternId"]], b["fromIdx"], b["arriveMin"], [veh("early", "X47", "S3")])
                if want is None:
                    assert b["basis"] == "typical" and b["waitMin"] == 5
                else:
                    assert b["basis"] == "live" and abs(b["waitMin"] - want[0]) < 1e-9
                assert b["arriveMin"] > 5, b["arriveMin"]


def test_c_not_running_pattern_dropped_and_control(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        res = ok(plan(s, O, D, [veh("a", "X47", "S1"), veh("b", "X45", "E1")]))
        assert not any(l.get("route") == "X99" for o in res["options"] for l in o["legs"])
        # control: X99 stops are in reach of this trip, so a live X99 vehicle makes a candidate
        o2, d2 = {"lat": 39.9352, "lng": -75.1576}, {"lat": 39.9475, "lng": -75.1576}
        cands = s.page.evaluate("""async ([o, d, v]) => { const T = window.__SEPTA_TEST__; const x = await T.loadNetwork();
            return T.buildBusCandidates(x.index, o, d, null, v).map(c => c.pattern.id); }""", [o2, d2, [veh("z", "X99", "Z1")]])
        assert "X99-0-1" in cands, cands
        none = s.page.evaluate("""async ([o, d, v]) => { const T = window.__SEPTA_TEST__; const x = await T.loadNetwork();
            return T.buildBusCandidates(x.index, o, d, null, v).map(c => c.pattern.id); }""", [o2, d2, [veh("z", "X47", "S1")]])
        assert "X99-0-1" not in none and "X47-0-1" in none


def test_c_never_boards_backwards(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        vs = [veh("n", "X47", "S1"), veh("m", "X47", "M13"), veh("e", "X45", "E1"), veh("f", "X45", "F13")]
        res = ok(plan(s, O, D, vs))
        used = {l["patternId"] for o in res["options"] for l in o["legs"] if l["mode"] == "bus"}
        assert used and used <= {"X47-0-1", "X45-0-1"}, used
        # every candidate the planner builds is in pattern order
        cands = s.page.evaluate("""async ([o, d, v]) => { const T = window.__SEPTA_TEST__; const x = await T.loadNetwork();
            return T.buildBusCandidates(x.index, o, d, null, v).map(c => [c.pattern.id, c.bi, c.ai]); }""", [O, D, vs])
        assert cands and all(b < a for _, b, a in cands) and not any(p.endswith("-1-1") for p, _, _ in cands), cands
        # the opposite trip uses the southbound patterns, in their own order
        res2 = ok(plan(s, D, O, vs))
        used2 = {l["patternId"] for o in res2["options"] for l in o["legs"] if l["mode"] == "bus"}
        assert used2 and used2 <= {"X47-1-1", "X45-1-1"}, used2
        for o in res2["options"]:
            for l in o["legs"]:
                if l["mode"] == "bus":
                    assert l["fromIdx"] < l["toIdx"] and l["stops"] == l["toIdx"] - l["fromIdx"]


# ---------------------------------------------------------------- (d) bike + bus combinations
OW = {"lat": 39.9475, "lng": -75.1745}     # far west: no stop within walking range, Indego '19th & Lombard' nearby
DW = {"lat": 39.9575, "lng": -75.1745}     # far west: Indego '21st & Winter' and '20th & Race' nearby


def test_d_bike_bus_walk(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        a = station(s, "19th & Lombard")
        b = station(s, "9th & Locust")
        s.mocks.set_station(a["station_id"], bikes=3, docks=0)
        s.mocks.set_station(b["station_id"], bikes=0, docks=4)
        vs = [veh("v", "X47", "S1")]
        res = ok(plan(s, OW, D, vs))
        opts = by_structure(res, "bike-bus-walk")
        assert opts, [o["structure"] for o in res["options"]]
        legs = opts[0]["legs"]
        assert [l["mode"] for l in legs] == ["walk", "bike", "walk", "bus", "walk"], [l["mode"] for l in legs]
        assert legs[0]["to"]["name"] == a["name"] and legs[1]["to"]["name"] == b["name"] and legs[2]["from"]["name"] == b["name"]
        bus = legs[3]
        assert bus["fromIdx"] == 7 and bus["from"]["name"] == STOPS["S8"][2], bus
        assert bus["toIdx"] > bus["fromIdx"]
        # arrival at the stop = sum of the three raw access legs, which includes unlock and dock
        bike_sec = hav(sll(a), sll(b)) * 1.25 / 3.6
        arr = walk_min(OW_ll(), sll(a)) + (bike_sec + 150) / 60 + walk_min(sll(b), stop_ll("S8"))
        assert abs(bus["arriveMin"] - arr) < 0.02, (bus["arriveMin"], arr)
        assert any("unlock" in n for n in legs[1]["notes"])
        # no walk-only access exists from here, and nothing else offers a bus
        assert not by_structure(res, "walk-bus-walk")
        # dropped: no dock near any stop within reach
        s.mocks.set_all(bikes=0, docks=0)
        s.mocks.set_station(a["station_id"], bikes=3)
        res = ok(plan(s, OW, D, vs))
        assert not [o for o in res["options"] if "bus" in o["structure"]], [o["structure"] for o in res["options"]]
        # dropped: no bike near the start
        s.mocks.set_station(a["station_id"], bikes=0)
        s.mocks.set_station(b["station_id"], docks=4)
        res = ok(plan(s, OW, D, vs))
        assert not [o for o in res["options"] if "bus" in o["structure"]]


def OW_ll():
    return OW["lat"], OW["lng"]


def test_d_walk_bus_bike(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        s3 = station(s, "11th & Wood")           # 135 m from S12
        s4 = station(s, "21st & Winter, Franklin Institute")
        s.mocks.set_station(s3["station_id"], bikes=4, docks=0)
        s.mocks.set_station(s4["station_id"], bikes=0, docks=5)
        vs = [veh("v", "X47", "S1")]
        res = ok(plan(s, O, DW, vs))
        opts = by_structure(res, "walk-bus-bike")
        assert opts, [o["structure"] for o in res["options"]]
        legs = opts[0]["legs"]
        assert [l["mode"] for l in legs] == ["walk", "bus", "walk", "bike", "walk"], [l["mode"] for l in legs]
        bus = legs[1]
        assert bus["toIdx"] == 11 and bus["to"]["name"] == STOPS["S12"][2], bus
        assert legs[2]["to"]["name"] == s3["name"] and legs[3]["to"]["name"] == s4["name"]
        bike_sec = hav(sll(s3), sll(s4)) * 1.25 / 3.6
        assert legs[3]["minutes"] == math.ceil((bike_sec + 150) / 60 - 1e-9)
        assert not by_structure(res, "walk-bus-walk")
        # dropped when no bike can be taken at the alighting side, or no dock near the finish
        s.mocks.set_station(s3["station_id"], bikes=0)
        res = ok(plan(s, O, DW, vs))
        assert not [o for o in res["options"] if "bus" in o["structure"]]
        s.mocks.set_station(s3["station_id"], bikes=4)
        s.mocks.set_station(s4["station_id"], docks=0)
        res = ok(plan(s, O, DW, vs))
        assert not [o for o in res["options"] if "bus" in o["structure"]]


# ---------------------------------------------------------------- (e) legs sum, (g) ranking
def check_options(res):
    opts = res["options"]
    main = [o for o in opts if not o["dominated"]]
    dom = [o for o in opts if o["dominated"]]
    assert 1 <= len(main) <= 5 and len(dom) <= 3 and len(opts) == len(main) + len(dom)
    assert opts == main + dom, "dominated options come after the main list"
    for grp in (main, dom):
        mins = [o["minutes"] for o in grp]
        assert mins == sorted(mins), mins
    assert res["hiddenCount"] == len(dom)
    per = {}
    for o in opts:
        per[o["structure"]] = per.get(o["structure"], 0) + 1
        assert o["minutes"] == sum(l["minutes"] for l in o["legs"]), o
        for l in o["legs"]:
            assert l["mode"] in ("walk", "bike", "bus", "car")
            assert isinstance(l["minutes"], int) and l["minutes"] >= 0
            assert l["basis"] in ("routed", "scheduled", "live", "typical")
            assert len(l["path"]) >= 2 and all(len(p) == 2 for p in l["path"])
            assert l["from"]["lat"] and l["to"]["lng"] and isinstance(l["notes"], list) and l["meters"] >= 0
    assert max(per.values()) <= 2, per


def test_e_legs_sum_to_total_and_have_paths(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        vs = [veh("a", "X47", "S1"), veh("b", "X47", "S3"), veh("c", "X45", "E2"), veh("d", "X45", "F10")]
        s.mocks.set_all(bikes=4, docks=4)
        for o, d, v in ((O, D, vs), (D, O, vs), (OW, DW, vs), (O, DW, vs), (OW, D, vs), (O, D, [])):
            res = ok(plan(s, o, d, v))
            check_options(res)
        # a one-minute walk, and zero-length edge: start equals finish
        res = ok(plan(s, O, {"lat": O["lat"] + 0.0001, "lng": O["lng"]}, vs))
        check_options(res)


def test_g_ranking_and_caps(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.set_all(bikes=4, docks=4)
        vs = [veh("a", "X47", "S1"), veh("b", "X47", "S3"), veh("c", "X45", "E2")]
        n_wbw = s.page.evaluate("""async ([o, d, v]) => { const T = window.__SEPTA_TEST__; const x = await T.loadNetwork();
            const st = await T.loadIndego(true);
            return T.buildBusCandidates(x.index, o, d, st, v).filter(c => c.structure === 'walk-bus-walk').length; }""", [O, D, vs])
        assert n_wbw >= 3, "the scenario really has more walk-bus-walk candidates than may be shown"
        res = ok(plan(s, O, D, vs))
        check_options(res)
        assert len([o for o in res["options"] if not o["dominated"]]) == 5, [(o["structure"], o["minutes"], o["dominated"]) for o in res["options"]]
        structs = [o["structure"] for o in res["options"]]
        assert structs.count("walk-bus-walk") <= 2
        # a sparse world has fewer than five
        s.mocks.set_all(bikes=0, docks=0)
        res = ok(plan(s, O, D, []))
        assert [o["structure"] for o in res["options"]] in (["car", "walk"],), res["options"]


# ---------------------------------------------------------------- (f) routing budget, cache and failure
def pair_key(h):
    return (h["profile"], round(h["from"][0], 5), round(h["from"][1], 5), round(h["to"][0], 5), round(h["to"][1], 5))


def test_f_routing_call_cap_and_cache(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.set_all(bikes=6, docks=6)
        vs = [veh("a", "X47", "S1"), veh("b", "X47", "S3"), veh("c", "X45", "E2"), veh("d", "X45", "F10"), veh("e", "X47", "M9")]
        # far apart enough that bike access and egress are attractive everywhere
        res = ok(plan(s, OW, DW, vs))
        n = len(s.mocks.routing_hits)
        assert 5 <= n <= 14, n
        assert res["stats"]["routingCalls"] == n
        keys = [pair_key(h) for h in s.mocks.routing_hits]
        assert len(keys) == len(set(keys)), "the same pair is never requested twice"
        check_options(res)
        # dense: several attractive bus finalists plus the bike structure
        s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches()")
        s.mocks.routing_hits.clear()
        res = ok(plan(s, {"lat": 39.9330, "lng": -75.1595}, {"lat": 39.9590, "lng": -75.1565}, vs))
        n = len(s.mocks.routing_hits)
        assert n <= 14 and res["stats"]["finalists"] >= 3, (n, res["stats"])
        assert n >= 10, "the scenario is dense enough to stress the cap"
        keys = [pair_key(h) for h in s.mocks.routing_hits]
        assert len(keys) == len(set(keys))
        # same plan again: everything is cached
        before = len(s.mocks.routing_hits)
        ok(plan(s, {"lat": 39.9330, "lng": -75.1595}, {"lat": 39.9590, "lng": -75.1565}, vs))
        assert len(s.mocks.routing_hits) == before, "second identical plan makes no routing calls"


def test_f_routing_failure_rejects_plan(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.routing_mode = "abort"
        res = plan(s, O, D, [veh("a", "X47", "S1")])
        assert res == {"err": "routing_unavailable"}, res
        s.mocks.routing_mode = "http500"
        s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches()")
        assert plan(s, O, D, [veh("a", "X47", "S1")]) == {"err": "routing_unavailable"}
        # and it recovers when the service does
        s.mocks.routing_mode = "ok"
        assert ok(plan(s, O, D, [veh("a", "X47", "S1")]))["options"]


# ---------------------------------------------------------------- (h) honesty
def live_bus_record(vid, route, next_id, ts, lat=39.94, lng=-75.158):
    return {"lat": str(lat), "lng": str(lng), "label": vid, "route_id": route, "trip": "1", "VehicleID": vid, "BlockID": "1",
            "Direction": "Northbound", "destination": "North Terminal", "heading": 0, "late": 0, "next_stop_id": next_id,
            "next_stop_name": None, "next_stop_sequence": 1, "estimated_seat_availability": "NOT_AVAILABLE", "Offset": 0,
            "Offset_sec": "0", "timestamp": ts}


def test_h_stale_or_dropped_bus_data_hides_bus_options(root):
    with Session(root, init_scripts=[HOOK]) as s:
        s.mocks.network = copy.deepcopy(NET)
        ts = int(s.worker.data["TransitView"]["bus"][0]["timestamp"])
        s.worker.data["TransitView"] = {"bus": [live_bus_record("9001", "X47", "S3", ts), live_bus_record("9002", "X47", "S6", ts)]}
        s.open()
        s.wait_live()
        no_bikes(s)
        # fresh feed: the page's own live vehicles are used (opts.vehicles not passed), and the live vehicle is named
        res = ok(plan(s, O, D, None))
        opts = [o for o in by_structure(res, "walk-bus-walk") if bus_leg(o)["route"] == "X47"]
        assert opts and bus_leg(opts[0])["basis"] == "live" and bus_leg(opts[0])["vehicleKey"] == "b9001", res["options"]
        assert not any(n["code"] == "bus_feed_unavailable" for n in res["notes"])
        # the feed fails: stale after 22 s, dropped after 120 s. Both hide every bus option and say so.
        s.worker.mode = "http502"
        s.tick(40000)
        assert s.page.evaluate("window.__SEPTA_TEST__.TP !== undefined")
        for label in ("stale", "dropped"):
            res = ok(plan(s, O, D, None))
            assert not [o for o in res["options"] if "bus" in o["structure"]], (label, res["options"])
            assert any(n["code"] == "bus_feed_unavailable" and n["text"] == "Live bus data unavailable, bus options hidden." for n in res["notes"]), (label, res["notes"])
            assert by_structure(res, "walk") and by_structure(res, "car")
            s.tick(130000)


def test_h_live_label_only_with_a_vehicle(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.set_all(bikes=4, docks=4)
        for vs in ([veh("a", "X47", "S2"), veh("b", "X45", "E4")], [veh("p", "X47", "S9"), veh("q", "X45", "F3")], []):
            keys = {v["key"] for v in vs}
            res = ok(plan(s, O, D, vs))
            for o in res["options"]:
                for l in o["legs"]:
                    if l["mode"] == "bus":
                        if l["basis"] == "live":
                            assert l["vehicleKey"] in keys and l["waitBasis"] == "live"
                        else:
                            assert l["basis"] == "typical" and l["vehicleKey"] is None
                    else:
                        assert l["basis"] == "routed" and l["mode"] in ("walk", "bike", "car")
            if not vs:
                assert not [o for o in res["options"] if "bus" in o["structure"]]


# ---------------------------------------------------------------- (i) idle pause
def test_i_works_while_idle_paused(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        s.page.clock.fast_forward(61 * 60000)
        s.tick(15000)
        assert s.page.locator("#idleBar").is_visible(), "the page is idle-paused"
        worker_hits = len(s.worker.hits)
        res = ok(plan(s, O, D, [veh("a", "X47", "S1")]))
        assert res["options"] and any(o["structure"] == "walk-bus-walk" for o in res["options"])
        assert len(s.mocks.routing_hits) >= 3 and s.mocks.indego_hits and s.mocks.network_hits == 1
        assert len(s.worker.hits) == worker_hits, "planning never touches the Worker"
        assert s.page.locator("#idleBar").is_visible(), "planning does not count as use"
        assert not s.unexpected and not s.septa_direct


def test_i_nothing_runs_on_its_own_and_nothing_is_stored(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.tick(60000)
        assert s.mocks.routing_hits == [] and s.mocks.indego_hits == [] and s.mocks.network_hits == 0
        before = s.page.evaluate("JSON.stringify(Object.entries(localStorage))")
        ok(plan(s, O, D, [veh("a", "X47", "S1")]))
        assert s.page.evaluate("JSON.stringify(Object.entries(localStorage))") == before
        assert not s.unexpected and not s.console_errors, (s.unexpected, s.console_errors)


# ---------------------------------------------------------------- dominated options
def test_j_dominated_flag_bike_is_best(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.set_all(bikes=5, docks=5)
        vs = [veh("a", "X47", "S1"), veh("b", "X45", "E1")]
        # start and finish are on the same street: biking (about 11 min) beats a bus ride that needs 4+ minutes of waiting
        res = ok(plan(s, O, D, vs))
        check_options(res)
        bike = by_structure(res, "walk-bike-walk")[0]
        walk = by_structure(res, "walk")[0]
        ref = min(bike["minutes"], walk["minutes"])
        assert bike["minutes"] < walk["minutes"] and res["bestMinutes"] == min(o["minutes"] for o in res["options"] if o["structure"] != "car")
        flagged = [o for o in res["options"] if o["dominated"]]
        assert flagged, [(o["structure"], o["minutes"]) for o in res["options"]]
        for o in res["options"]:
            if o["structure"] in ("walk", "walk-bike-walk", "car"):
                assert o["dominated"] is False and "dominatedReason" not in o
            else:
                assert o["dominated"] == (o["minutes"] >= ref), (o["structure"], o["minutes"], ref)
            if o["dominated"]:
                assert o["dominatedReason"] == "slower than biking the whole way"
        # a car that is slower than everything is still not dominated
        assert by_structure(res, "car")[0]["dominated"] is False


def test_j_not_dominated_without_bikes_when_bus_beats_walking(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        res = ok(plan(s, O, D, [veh("a", "X47", "S2"), veh("b", "X45", "E3")]))
        check_options(res)
        walk = by_structure(res, "walk")[0]
        buses = [o for o in res["options"] if "bus" in o["structure"]]
        assert buses and all(o["minutes"] < walk["minutes"] for o in buses)
        assert all(o["dominated"] is False for o in res["options"]) and res["hiddenCount"] == 0
        # a bus that is slower than walking is flagged, with the walking reason
        short = {"lat": O["lat"], "lng": O["lng"]}, {"lat": O["lat"] + 0.0012, "lng": O["lng"]}
        res = ok(plan(s, short[0], short[1], [veh("a", "X47", "S1")]))
        for o in res["options"]:
            if "bus" in o["structure"]:
                assert o["dominated"] and o["dominatedReason"] == "slower than walking the whole way"


def test_j_ordering_and_caps_with_dominated(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.set_all(bikes=5, docks=5)
        vs = [veh("a", "X47", "S1"), veh("b", "X47", "S3"), veh("c", "X45", "E2"), veh("d", "X45", "F10")]
        for o, d in ((O, D), (OW, DW), (O, DW), ({"lat": 39.9330, "lng": -75.1595}, {"lat": 39.9590, "lng": -75.1565})):
            res = ok(plan(s, o, d, vs))
            check_options(res)
            assert len(res["options"]) <= 8
            ref = min(x["minutes"] for x in res["options"] if x["structure"] in ("walk", "walk-bike-walk"))
            assert all(x["dominated"] == (x["structure"] not in ("walk", "walk-bike-walk", "car") and x["minutes"] >= ref) for x in res["options"])
        # many dominated candidates: only three come back, still two per structure at most
        res = ok(plan(s, O, {"lat": O["lat"] + 0.0012, "lng": O["lng"]}, vs))
        check_options(res)
        assert res["hiddenCount"] <= 3


# ---------------------------------------------------------------- (k) WP2: structured notes, stations, schedule validity
def plan_o(s, o, d, vehicles, **opts):
    """plan() with extra planner options (today, ...)."""
    return s.page.evaluate("""async ([o, d, v, extra]) => {
        const T = window.__SEPTA_TEST__;
        try { return {ok: await T.planTrips(o, d, Object.assign({vehicles: v}, extra))}; }
        catch (e) { return {err: e && e.code ? e.code : String(e)}; }
    }""", [o, d, vehicles, opts])


def codes(res):
    return [n["code"] for n in res["notes"]]


def note_of(res, code):
    return next(n for n in res["notes"] if n["code"] == code)


def test_k_every_note_is_structured_with_a_code(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.set_all(bikes=0, docks=5)
        s.mocks.indego_mode = "http500"
        res = ok(plan_o(s, O, D, [veh("a", "X47", "S1")], today="20260601"))
        assert res["notes"] and all(isinstance(n, dict) and isinstance(n["code"], str) for n in res["notes"]), res["notes"]
        assert "indego_unavailable" in codes(res)
        assert not any("could not be completed" in json.dumps(n) for n in res["notes"])


def test_k_schedule_stale_boundaries_and_injectable_today(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        vs = [veh("a", "X47", "S1")]
        assert NET["feed"]["end"] == "20261231"
        # more than 14 days left: no note
        for today in ("20260101", "20261201", "20261216"):
            res = ok(plan_o(s, O, D, vs, today=today))
            assert "schedule_stale" not in codes(res), today
        # the last 15 days up to and including the end date: expiring, with the days left
        for today, days in (("20261217", 14), ("20261224", 7), ("20261231", 0)):
            n = note_of(ok(plan_o(s, O, D, vs, today=today)), "schedule_stale")
            assert (n["state"], n["days"], n["end"]) == ("expiring", days, "20261231"), (today, n)
        # past the end: expired
        for today, days in (("20270101", -1), ("20280101", -366)):
            n = note_of(ok(plan_o(s, O, D, vs, today=today)), "schedule_stale")
            assert (n["state"], n["days"]) == ("expired", days), (today, n)
        # today can also be set once for the page (TP.today) and as epoch milliseconds
        s.page.evaluate("window.__SEPTA_TEST__.TP.today = '20270301'")
        assert note_of(ok(plan(s, O, D, vs)), "schedule_stale")["state"] == "expired"
        s.page.evaluate("window.__SEPTA_TEST__.TP.today = null")
        ms = s.page.evaluate("new Date(2026, 11, 20, 12, 0).getTime()")
        assert note_of(ok(plan_o(s, O, D, vs, today=ms)), "schedule_stale")["days"] == 11
        # the feed object is always reported for the UI line
        assert ok(plan_o(s, O, D, vs, today="20260601"))["asOf"]["network"]["feed"] == NET["feed"]
        # a network file without feed dates produces no stale note
        n2 = copy.deepcopy(NET); del n2["feed"]
        s.mocks.network = n2
        s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches()")
        assert "schedule_stale" not in codes(ok(plan_o(s, O, D, vs, today="20990101")))


def test_k_routing_limit_when_the_call_budget_skips_candidates(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        vs = [veh("a", "X47", "S1")]
        res = ok(plan_o(s, O, D, vs, today="20260601"))
        assert "routing_limit" not in codes(res) and by_structure(res, "walk-bus-walk")
        s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches(); window.__SEPTA_TEST__.TP.MAX_CALLS = 3")
        res = ok(plan_o(s, O, D, vs, today="20260601"))
        assert codes(res).count("routing_limit") == 1, res["notes"]
        assert by_structure(res, "walk") and by_structure(res, "car"), "the baselines are still returned"
        assert res["stats"]["routingCalls"] <= 3


def test_k_routing_failed_when_bus_legs_cannot_be_routed(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        vs = [veh("a", "X47", "S1")]
        res = ok(plan_o(s, O, D, vs, today="20260601"))
        assert "routing_failed" not in codes(res)
        # the routing service refuses every leg that starts at stop S12 (a bus exit), answers everything else
        s.page.evaluate("""() => { const f = window.fetch; window.fetch = function (u, o) {
            if (String(u).includes('route/v1/driving/-75.15800,39.95750;') || String(u).includes('/route/') && String(u).includes('from=39.95750,-75.15800&')) return Promise.resolve(new Response('{}', {status: 500}));
            return f.call(window, u, o); }; }""")
        s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches()")
        res = ok(plan_o(s, O, D, vs, today="20260601"))
        n = note_of(res, "routing_failed")
        assert n["count"] >= 1 and "routing_limit" not in codes(res), res["notes"]
        assert by_structure(res, "walk") and by_structure(res, "car")
        assert not any(l.get("toIdx") == 11 for o in res["options"] for l in o["legs"] if l["mode"] == "bus"), "options using S12 were left out"


def test_k_no_live_bus_names_routes_that_serve_the_trip(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        # nothing tracked: the routes that serve both ends are named
        res = ok(plan_o(s, O, D, [], today="20260601"))
        n = note_of(res, "no_live_bus")
        assert "X47" in n["routes"] and set(n["routes"]) <= {"X47", "X45", "X99"}, n
        assert not [o for o in res["options"] if "bus" in o["structure"]]
        # only a bus on a route outside the network is tracked: still no live bus for the trip
        assert "no_live_bus" in codes(ok(plan_o(s, O, D, [veh("z", "ZZ9", "Z1")], today="20260601")))
        # a live bus on a serving route: no note
        assert "no_live_bus" not in codes(ok(plan_o(s, O, D, [veh("a", "X47", "S1")], today="20260601")))
        # a trip no route serves at all is not a "no live bus" case
        far_o, far_d = {"lat": 39.99, "lng": -75.05}, {"lat": 39.995, "lng": -75.04}
        assert "no_live_bus" not in codes(ok(plan_o(s, far_o, far_d, [], today="20260601")))
        # a tracked bus is past the stop and the schedule has no headway: no wait can be shown, so the route counts as not live
        n2 = copy.deepcopy(NET)
        for p in n2["patterns"]:
            p["hw"] = None
        s.mocks.network = n2
        s.page.evaluate("window.__SEPTA_TEST__.resetPlannerCaches()")
        res = ok(plan_o(s, O, D, [veh("p", "X47", "S7")], today="20260601"))
        assert "X47" in note_of(res, "no_live_bus")["routes"]
        assert not [o for o in res["options"] if "bus" in o["structure"]]


def test_k_no_bus_beats_baseline(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        short = {"lat": O["lat"] + 0.0012, "lng": O["lng"]}
        res = ok(plan_o(s, O, short, [veh("a", "X47", "S1")], today="20260601"))
        assert any("bus" in o["structure"] for o in res["options"]), "dominated buses are still listed"
        assert note_of(res, "no_bus_beats_baseline")["baseline"] == "walking"
        # a bus that does beat walking: no note
        res = ok(plan_o(s, O, D, [veh("a", "X47", "S2")], today="20260601"))
        assert "no_bus_beats_baseline" not in codes(res)
        # no bus option at all is a different situation
        assert "no_bus_beats_baseline" not in codes(ok(plan_o(s, O, D, [], today="20260601")))
        # with bikes, the reference can be biking
        s.mocks.set_all(bikes=5, docks=5)
        res = ok(plan_o(s, O, D, [veh("a", "X47", "S1")], today="20260601"))
        if all(o["dominated"] for o in res["options"] if "bus" in o["structure"]):
            assert note_of(res, "no_bus_beats_baseline")["baseline"] in ("walking", "biking")


def test_k_station_objects_on_every_bike_leg(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        s.mocks.set_all(bikes=4, docks=3)
        res = ok(plan_o(s, O, D, [veh("a", "X47", "S2")], today="20260601"))
        seen = 0
        for o in res["options"]:
            for l in o["legs"]:
                if l["mode"] == "bike":
                    seen += 1
                    st = l["stations"]
                    assert st["from"]["name"] == l["from"]["name"] and st["to"]["name"] == l["to"]["name"], (st, l["from"], l["to"])
                    assert (st["from"]["bikes"], st["from"]["ebikes"]) == (4, 2) and st["to"]["docks"] == 3, st
                    assert st["from"]["asOf"] > 0 and st["to"]["asOf"] > 0
                    assert set(st["from"]) == {"name", "bikes", "ebikes", "docks", "asOf"}
                    assert not any("Indego counts" in n for n in l["notes"])
                else:
                    assert "stations" not in l
        assert seen >= 2, "a bike-only trip and bike legs inside bus trips"
        assert any(o["structure"] != "walk-bike-walk" and any(l["mode"] == "bike" for l in o["legs"]) for o in res["options"])


def test_k_no_route_answer_means_no_trip_found(root):
    with Session(root, init_scripts=[HOOK]) as s:
        open_session(s)
        no_bikes(s)
        s.page.evaluate("""() => { const f = window.fetch; window.fetch = function (u, o) {
            if (String(u).includes('/route/foot') || String(u).includes('routed-foot')) return Promise.resolve(new Response('{"code":"NoRoute","routes":[]}', {status: 200, headers: {'content-type': 'application/json'}}));
            return f.call(window, u, o); }; }""")
        res = ok(plan_o(s, O, D, [veh("a", "X47", "S1")], today="20260601"))
        assert res["options"] == [] and res["bestMinutes"] is None, res
        # an unreachable service is still an error, not "no trip"
        s.page.evaluate("""() => { window.fetch = function () { return Promise.resolve(new Response('{}', {status: 500})); }; window.__SEPTA_TEST__.resetPlannerCaches(); }""")
        assert plan_o(s, O, D, [veh("a", "X47", "S1")], today="20260601") == {"err": "routing_unavailable"}
