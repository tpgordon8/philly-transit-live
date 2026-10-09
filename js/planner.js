/* js/planner.js: trip planner core: bus network, Indego, routing and plan building (no DOM). Part of the classic-script split of index.html (ARCHITECTURE.md section 14). */ /*@split*/
(function () {
  /*@split*/
  'use strict'; /*@split*/
  var S = window.SEPTA; /*@split*/
  var DROP_AFTER_MS = S.util.DROP_AFTER_MS,
    distM = S.util.distM,
    isNum = S.util.isNum,
    state = S.util.state,
    toRad = S.util.toRad; /*@split*/
  var collect = S.feed.collect,
    skipped = S.feed.skipped; /*@split*/
  /* ===== Trip planner core (ARCHITECTURE.md section 12) =====
   Data clients and planner functions only: no DOM, no storage. Routing and Indego go through the Worker first. The ONLY cases that
   fall back (once) to the direct provider URL are a network error, a Worker 404 (an older Worker) and a Worker 500/502/503/504; any other
   Worker answer, a 422 NoRoute included, is final. These run only when a caller (the planner UI) invokes them, so a user action
   works even when the page is idle-paused: they deliberately do not go through fetchOnce().
   Third parties receive only leg endpoints (routing service, via the Worker, rounded to 4 decimals there; unrounded 5 decimals in
   the direct fallback) or nothing (Indego, own static file). */
  var TP = {
    WALK_MPS: 1.25,
    BIKE_MPS: 3.6,
    CIRC: 1.3,
    WALK_MAX_M: 0.6 * 1609.344,
    BIKE_MAX_M: 2.0 * 1609.344,
    STN_NEAR_M: 0.15 * 1609.344,
    STN_START_M: 1200,
    UNLOCK_S: 90,
    DOCK_S: 60,
    BOARD_S: 60,
    MAX_CALLS: 14,
    MAX_FINALISTS: 6,
    PER_STRUCT_FINAL: 3,
    PER_STRUCT_OUT: 2,
    MAX_OUT: 5,
    MAX_DOMINATED: 3,
    MAX_INFLIGHT: 2,
    GAP_MS: 250,
    BOX: { latMin: 39.6, latMax: 40.4, lngMin: -75.9, lngMax: -74.5 },
    STALE_DAYS: 14,
    today: null,
    TIMEOUT_MS: 10000,
    RETRY_MS: 1500,
    GRID: 0.005,
    STATUS_TTL_MS: 60000,
    ROUTE_BASE: 'https://septa-proxy.tpgordon8.workers.dev/route/',
    INDEGO_BASE: 'https://septa-proxy.tpgordon8.workers.dev/indego/',
    ROUTE_DIRECT: 'https://routing.openstreetmap.de/routed-',
    INDEGO_DIRECT: 'https://gbfs.bcycle.com/bcycle_indego/',
    NET_URL: 'data/bus-network.json'
  };
  var tpNet = null,
    tpInfo = null,
    tpStatus = null,
    tpRoute = {},
    tpQueue = [],
    tpInflight = 0,
    tpLastStart = 0,
    tpTimer = null;
  /* The Philadelphia-region box the Worker accepts (worker/worker.js BBOX). Checked in the page before any call is made. */
  function inRegion(pt) {
    var b = TP.BOX;
    return (
      !!pt &&
      isNum(pt.lat) &&
      isNum(pt.lng) &&
      pt.lat >= b.latMin &&
      pt.lat <= b.latMax &&
      pt.lng >= b.lngMin &&
      pt.lng <= b.lngMax
    );
  }
  function tpFail(code, msg) {
    return { code: code, message: msg || code };
  }
  function resetPlannerCaches() {
    tpNet = null;
    tpInfo = null;
    tpStatus = null;
    tpRoute = {};
  }
  /* A plan's handle {dead, calls, ctls, keys}: its requests register an AbortController so cancelPlan can cut them short. */
  function tpCtl(ctx) {
    var ctl = new AbortController(),
      t = setTimeout(function () {
        ctl.abort();
      }, TP.TIMEOUT_MS);
    if (ctx) {
      (ctx.ctls || (ctx.ctls = [])).push(ctl);
    }
    return {
      signal: ctl.signal,
      done: function () {
        clearTimeout(t);
        if (ctx && ctx.ctls) {
          var i = ctx.ctls.indexOf(ctl);
          if (i >= 0) ctx.ctls.splice(i, 1);
        }
      }
    };
  }
  /* A 4xx answer other than 404/408/429 is an answer (OSRM sends HTTP 400 with {"code":"NoRoute"}), not an outage: the error is
   final (never retried or re-sent elsewhere) and carries the parsed body when there is one. */
  function tpFinal(r) {
    return r.text().then(function (t) {
      var e = new Error('HTTP ' + r.status);
      e.final = true;
      e.status = r.status;
      try {
        e.body = JSON.parse(t);
      } catch (x) {}
      throw e;
    });
  }
  function tpIsAnswer(st) {
    return st >= 400 && st < 500 && st !== 404 && st !== 408 && st !== 429;
  }
  function tpFetch(url, noStore, ctx) {
    var c = tpCtl(ctx);
    return fetch(url, noStore ? { signal: c.signal, cache: 'no-store' } : { signal: c.signal })
      .then(function (r) {
        if (tpIsAnswer(r.status)) return tpFinal(r);
        if (!r.ok) {
          var e = new Error('HTTP ' + r.status);
          e.status = r.status;
          throw e;
        }
        return r.json();
      })
      .finally(c.done);
  }
  /* 10 s timeout, one retry after 1.5 s (not after a final 4xx answer or once the plan is cancelled). Resolves parsed JSON. */
  function tpGetJson(url, noStore, ctx) {
    return tpFetch(url, noStore, ctx).catch(function (e) {
      if ((e && e.final) || (ctx && ctx.dead)) throw e;
      return new Promise(function (res) {
        setTimeout(res, TP.RETRY_MS);
      }).then(function () {
        if (ctx && ctx.dead) throw e;
        return tpFetch(url, noStore, ctx);
      });
    });
  }
  /* Worker first (one attempt, no retry). ONE fallback to the direct provider (tpGetJson, with its own retry) only when the Worker
   cannot be reached, answers 404 (an older Worker without the endpoint) or 500/502/503/504 (the Worker, or its upstream, is down),
   or sends a 200 that is not JSON. Every other Worker answer is final: 422 {"code":"NoRoute"} and other 4xx are answers, so the
   coordinates are not re-sent to the provider. A cancelled plan never falls back. */
  function tpGetVia(workerUrl, directUrl, noStore, ctx) {
    return tpFetch(workerUrl, noStore, ctx).catch(function (e) {
      if (ctx && ctx.dead) throw e;
      var st = e && e.status;
      if (e && e.final) throw e;
      if (st != null && st !== 404 && st !== 500 && st !== 502 && st !== 503 && st !== 504)
        throw Object.assign(e, { final: true });
      return tpGetJson(directUrl, noStore, ctx);
    });
  }
  function validateNetwork(n) {
    var bad = function (m) {
      throw new Error('bus-network: ' + m);
    };
    if (!n || typeof n !== 'object' || n.v !== 1) bad('v');
    if (!n.stops || typeof n.stops !== 'object' || Array.isArray(n.stops)) bad('stops');
    if (!Array.isArray(n.patterns)) bad('patterns');
    var id;
    for (id in n.stops) {
      var s = n.stops[id];
      if (!Array.isArray(s) || !isNum(s[0]) || !isNum(s[1])) bad('stop ' + id);
    }
    n.patterns.forEach(function (p) {
      if (
        !p ||
        typeof p.id !== 'string' ||
        typeof p.route !== 'string' ||
        !Array.isArray(p.stops) ||
        !Array.isArray(p.mins) ||
        p.stops.length < 2 ||
        p.mins.length !== p.stops.length
      )
        bad('pattern shape');
      if (p.hw != null && !isNum(p.hw)) bad('hw ' + p.id);
      for (var i = 0; i < p.stops.length; i++) {
        if (!n.stops[p.stops[i]]) bad('unknown stop in ' + p.id);
        if (!isNum(p.mins[i]) || (i && p.mins[i] < p.mins[i - 1])) bad('mins in ' + p.id);
      }
    });
  }
  function cellOf(v) {
    return Math.floor(v / TP.GRID);
  }
  function buildNetIndex(net) {
    var ix = { net: net, stops: {}, grid: {}, patterns: {}, byRoute: {} },
      id;
    for (id in net.stops) {
      var s = net.stops[id],
        st = { id: id, lat: s[0], lng: s[1], name: s[2] || '' },
        k = cellOf(st.lat) + ',' + cellOf(st.lng);
      ix.stops[id] = st;
      (ix.grid[k] || (ix.grid[k] = [])).push(st);
    }
    net.patterns.forEach(function (p) {
      ix.patterns[p.id] = p;
      (ix.byRoute[p.route] || (ix.byRoute[p.route] = [])).push(p);
    });
    return ix;
  }
  /* Resolves {net, index}. Cached for the page session; a failure is not cached, so the next call tries again. */
  function loadNetwork() {
    if (tpNet) return tpNet;
    var p = tpGetJson(TP.NET_URL)
      .then(function (j) {
        validateNetwork(j);
        return { net: j, index: buildNetIndex(j) };
      })
      .catch(function () {
        if (tpNet === p) tpNet = null;
        throw tpFail('network_unavailable', 'Bus schedule data could not be loaded.');
      });
    tpNet = p;
    return p;
  }
  /* Stations merged from information and status. A station counts as usable only through the GBFS flags:
   renting = installed and renting, returning = installed and returning. Resolves an array; array.asOf is the status time in ms. */
  function mergeIndego(info, status) {
    var st = {},
      out = [];
    ((status && status.data && status.data.stations) || []).forEach(function (s) {
      st[s.station_id] = s;
    });
    ((info && info.data && info.data.stations) || []).forEach(function (i) {
      var s = st[i.station_id];
      if (!s || !isNum(i.lat) || !isNum(i.lon)) return;
      var t = s.num_bikes_available_types || {},
        inst = s.is_installed === 1 || s.is_installed === true;
      out.push({
        id: i.station_id,
        name: i.name || '',
        lat: i.lat,
        lon: i.lon,
        bikes: s.num_bikes_available | 0,
        ebikes: t.electric | 0,
        classic: t.classic | 0,
        docks: s.num_docks_available | 0,
        installed: inst,
        renting: inst && (s.is_renting === 1 || s.is_renting === true),
        returning: inst && (s.is_returning === 1 || s.is_returning === true),
        asOf: (s.last_reported || (status && status.last_updated) || 0) * 1000
      });
    });
    out.asOf = ((status && status.last_updated) || 0) * 1000;
    return out;
  }
  function loadIndego(fresh) {
    var now = Date.now();
    if (!tpInfo) {
      var pi = tpGetVia(TP.INDEGO_BASE + 'information', TP.INDEGO_DIRECT + 'station_information.json').catch(
        function () {
          if (tpInfo === pi) tpInfo = null;
          throw 0;
        }
      );
      tpInfo = pi;
    }
    if (!tpStatus || fresh === true || now - tpStatus.t >= TP.STATUS_TTL_MS) {
      var ps = { t: now };
      ps.p = tpGetVia(TP.INDEGO_BASE + 'status', TP.INDEGO_DIRECT + 'station_status.json', true).catch(
        function () {
          if (tpStatus === ps) tpStatus = null;
          throw 0;
        }
      );
      tpStatus = ps;
    }
    return Promise.all([tpInfo, tpStatus.p]).then(
      function (r) {
        return mergeIndego(r[0], r[1]);
      },
      function () {
        throw tpFail('indego_unavailable', 'Indego bike data could not be loaded.');
      }
    );
  }
  /* ----- Routing client: at most 2 requests in flight and at least 250 ms between starts (the OSM routing service asks for about
   one request per second per client; most plan legs are served from the Worker's cache, which does not reach that service),
   in-memory cache by profile and 5 dp endpoints. A cancelled plan's queued calls are dropped without delaying the next plan. ----- */
  function tpPump() {
    while (tpInflight < TP.MAX_INFLIGHT && tpQueue.length) {
      var job = tpQueue[0];
      if (job.ctx && job.ctx.dead) {
        tpQueue.shift();
        job.reject(tpFail('routing_unavailable', 'Plan abandoned.'));
        continue;
      }
      var wait = tpLastStart + TP.GAP_MS - Date.now();
      if (wait > 0 && wait <= TP.GAP_MS) {
        if (!tpTimer)
          tpTimer = setTimeout(function () {
            tpTimer = null;
            tpPump();
          }, wait);
        return;
      }
      tpQueue.shift();
      tpLastStart = Date.now();
      tpInflight++;
      if (job.ctx) job.ctx.calls++;
      job
        .run()
        .then(job.resolve, job.reject)
        .then(function () {
          tpInflight--;
          tpPump();
        });
    }
  }
  /* Abandons a plan: queued calls are dropped now, in-flight requests are aborted (their slots free at once), and results that
   still arrive are ignored by the caller. Its entries in the route cache are removed so a later plan never inherits them. */
  function cancelPlan(ctx) {
    if (!ctx) return;
    ctx.dead = true;
    (ctx.ctls || []).slice().forEach(function (c) {
      try {
        c.abort();
      } catch (e) {}
    });
    (ctx.keys || []).forEach(function (k) {
      if (tpRoute[k.key] === k.p) delete tpRoute[k.key];
    });
    tpQueue
      .filter(function (j) {
        return j.ctx === ctx;
      })
      .forEach(function (j) {
        j.reject(tpFail('routing_unavailable', 'Plan abandoned.'));
      });
    tpQueue = tpQueue.filter(function (j) {
      return j.ctx !== ctx;
    });
  }
  /* OSRM codes that mean "the service looked and there is no path": NoRoute, and NoSegment (a point it cannot snap to a street). */
  function noRouteCode(c) {
    return c === 'NoRoute' || c === 'NoSegment';
  }
  function routeKey(profile, a, b) {
    return (
      profile +
      '|' +
      a.lat.toFixed(5) +
      ',' +
      a.lng.toFixed(5) +
      '|' +
      b.lat.toFixed(5) +
      ',' +
      b.lng.toFixed(5)
    );
  }
  function routeLeg(profile, a, b, ctx) {
    if (profile !== 'foot' && profile !== 'bike' && profile !== 'car')
      return Promise.reject(tpFail('routing_unavailable', 'profile'));
    var key = routeKey(profile, a, b);
    if (tpRoute[key]) return tpRoute[key];
    var url =
      TP.ROUTE_BASE +
      profile +
      '?from=' +
      a.lat.toFixed(5) +
      ',' +
      a.lng.toFixed(5) +
      '&to=' +
      b.lat.toFixed(5) +
      ',' +
      b.lng.toFixed(5);
    var direct =
      TP.ROUTE_DIRECT +
      profile +
      '/route/v1/driving/' +
      a.lng.toFixed(5) +
      ',' +
      a.lat.toFixed(5) +
      ';' +
      b.lng.toFixed(5) +
      ',' +
      b.lat.toFixed(5) +
      '?overview=full&geometries=geojson';
    var p = new Promise(function (resolve, reject) {
      tpQueue.push({
        ctx: ctx,
        resolve: resolve,
        reject: reject,
        run: function () {
          return tpGetVia(url, direct, false, ctx)
            .then(function (j) {
              if (j && noRouteCode(j.code))
                throw tpFail('no_route', 'There is no street route between those points.');
              var r = j && j.code === 'Ok' && j.routes && j.routes[0];
              if (
                !r ||
                !isNum(r.distance) ||
                !isNum(r.duration) ||
                !r.geometry ||
                !Array.isArray(r.geometry.coordinates) ||
                r.geometry.coordinates.length < 2
              )
                throw 0;
              return {
                meters: r.distance,
                seconds: r.duration,
                path: r.geometry.coordinates.map(function (c) {
                  return [c[1], c[0]];
                })
              };
            })
            .catch(function (e) {
              if (e && e.code === 'no_route') throw e;
              if (e && e.body && noRouteCode(e.body.code))
                throw tpFail('no_route', 'There is no street route between those points.');
              throw tpFail(
                'routing_unavailable',
                'Walking, biking or driving directions could not be loaded.'
              );
            });
        }
      });
      tpPump();
    });
    tpRoute[key] = p;
    if (ctx) (ctx.keys || (ctx.keys = [])).push({ key: key, p: p });
    p.catch(function () {
      if (tpRoute[key] === p) delete tpRoute[key];
    });
    return p;
  }
  /* ----- Pure planner functions ----- */
  function stPt(s) {
    return { lat: s.lat, lng: s.lon != null ? s.lon : s.lng, name: s.name };
  }
  function nearbyStops(index, point, meters) {
    var dLat = meters / 111195,
      dLng = meters / (111195 * Math.max(0.2, Math.cos(toRad(point.lat)))),
      out = [];
    for (var i = cellOf(point.lat - dLat); i <= cellOf(point.lat + dLat); i++)
      for (var j = cellOf(point.lng - dLng); j <= cellOf(point.lng + dLng); j++) {
        var cell = index.grid[i + ',' + j];
        if (!cell) continue;
        for (var k = 0; k < cell.length; k++) {
          var s = cell[k],
            d = distM(point, s);
          if (d <= meters) out.push({ id: s.id, lat: s.lat, lng: s.lng, name: s.name, d: d });
        }
      }
    return out.sort(function (a, b) {
      return a.d - b.d;
    });
  }
  /* need: 'bike' (renting and a bike present), 'dock' (returning and a free dock), or falsy (any installed station). */
  function nearbyStations(stations, point, meters, need) {
    var out = [];
    (stations || []).forEach(function (s) {
      if (!s.installed) return;
      if (need === 'bike' && !(s.renting && s.bikes > 0)) return;
      if (need === 'dock' && !(s.returning && s.docks > 0)) return;
      var d = distM(point, stPt(s));
      if (d <= meters) out.push(Object.assign({}, s, { d: d }));
    });
    return out.sort(function (a, b) {
      return a.d - b.d;
    });
  }
  function estMin(mode, m) {
    return (m * TP.CIRC) / (mode === 'bike' ? TP.BIKE_MPS : TP.WALK_MPS) / 60;
  }
  /* Pre-ranking estimate in minutes. parts: {mode:'walk'|'bike', meters} (straight line), {minutes} or {seconds}. */
  function estimateTotal(parts) {
    var t = 0;
    parts.forEach(function (p) {
      t += p.mode ? estMin(p.mode, p.meters) : (p.minutes || 0) + (p.seconds || 0) / 60;
    });
    return t;
  }
  function isBusKind(v) {
    return !!v && (v.kind === 'bus' || v.kind === 'trolley');
  }
  /* Wait at boarding index `bi` for a traveller arriving `tArr` minutes from now. A live vehicle counts when its next stop is
   at pattern index <= bi (scheduled running time to bi, its lateness assumed to persist) and it has not already passed
   (time >= tArr - 1). The earliest such vehicle sets the wait; otherwise half the headway; otherwise null. */
  function waitAtStop(pat, bi, tArr, vehicles) {
    var best = null;
    (vehicles || []).forEach(function (v) {
      if (!isBusKind(v) || String(v.route) !== String(pat.route) || !v.nextId) return;
      for (var i = bi; i >= 0; i--) if (pat.stops[i] === v.nextId) break;
      if (i < 0) return;
      var t = pat.mins[bi] - pat.mins[i];
      if (t < tArr - 1) return;
      if (!best || t < best.t) best = { t: t, v: v, i: i };
    });
    if (best)
      return {
        minutes: Math.max(0, best.t - tArr),
        basis: 'live',
        vehicleKey: best.v.key,
        stopsAway: bi - best.i
      };
    if (pat.hw == null) return null;
    return { minutes: pat.hw / 2, basis: 'typical', vehicleKey: null, stopsAway: null };
  }
  function bestBikePair(from, to, bikes, docks) {
    var best = null;
    bikes.forEach(function (s1) {
      docks.forEach(function (s2) {
        if (s1.id === s2.id) return;
        var e = estimateTotal([
          { mode: 'walk', meters: distM(from, stPt(s1)) },
          { seconds: TP.UNLOCK_S },
          { mode: 'bike', meters: distM(stPt(s1), stPt(s2)) },
          { seconds: TP.DOCK_S },
          { mode: 'walk', meters: distM(stPt(s2), to) }
        ]);
        if (!best || e < best.est) best = { s1: s1, s2: s2, est: e };
      });
    });
    return best;
  }
  /* Bus candidates, pre-ranked by estimated minutes (straight line x 1.3). Only routes with a live vehicle are considered.
   Boarding index < alighting index always. Best 2 pairs per (pattern, access, egress). */
  function buildBusCandidates(ix, O, D, stations, vehicles) {
    var running = {},
      out = [],
      dockNear = {},
      bikeNear = {};
    (vehicles || []).forEach(function (v) {
      if (isBusKind(v)) running[String(v.route)] = 1;
    });
    var nO = {},
      nD = {};
    nearbyStops(ix, O, TP.BIKE_MAX_M).forEach(function (s) {
      nO[s.id] = s.d;
    });
    nearbyStops(ix, D, TP.BIKE_MAX_M).forEach(function (s) {
      nD[s.id] = s.d;
    });
    var bikesO = stations ? nearbyStations(stations, O, TP.STN_START_M, 'bike').slice(0, 3) : [];
    var docksD = stations ? nearbyStations(stations, D, TP.STN_START_M, 'dock').slice(0, 3) : [];
    function near(memo, stop, need) {
      var k = stop.id;
      return (
        memo[k] || (memo[k] = stations ? nearbyStations(stations, stop, TP.STN_NEAR_M, need).slice(0, 3) : [])
      );
    }
    Object.keys(running).forEach(function (route) {
      (ix.byRoute[route] || []).forEach(function (pat) {
        var n = pat.stops.length,
          acc = [],
          egr = [],
          j;
        for (j = 0; j < n; j++) {
          var st = ix.stops[pat.stops[j]],
            a = {},
            e = {};
          if (nO[st.id] != null) {
            if (nO[st.id] <= TP.WALK_MAX_M) a.walk = { cost: estMin('walk', nO[st.id]) };
            if (bikesO.length) {
              var bp = bestBikePair(O, st, bikesO, near(dockNear, st, 'dock'));
              if (bp) a.bike = { cost: bp.est, s1: bp.s1, s2: bp.s2 };
            }
          }
          if (nD[st.id] != null) {
            if (nD[st.id] <= TP.WALK_MAX_M) e.walk = { cost: estMin('walk', nD[st.id]) };
            if (docksD.length) {
              var ep = bestBikePair(st, D, near(bikeNear, st, 'bike'), docksD);
              if (ep) e.bike = { cost: ep.est, s3: ep.s1, s4: ep.s2 };
            }
          }
          acc.push(a);
          egr.push(e);
        }
        ['walk', 'bike'].forEach(function (at) {
          ['walk', 'bike'].forEach(function (et) {
            var b1 = null,
              b2 = null,
              pairs = [];
            for (j = 0; j < n; j++) {
              if (egr[j][et]) {
                [b1, b2].forEach(function (b) {
                  if (b)
                    pairs.push({
                      bi: b.j,
                      ai: j,
                      val: b.val + egr[j][et].cost + pat.mins[j] + TP.BOARD_S / 60
                    });
                });
              }
              if (acc[j][at]) {
                var nb = { j: j, val: acc[j][at].cost - pat.mins[j] };
                if (!b1 || nb.val < b1.val) {
                  b2 = b1;
                  b1 = nb;
                } else if (!b2 || nb.val < b2.val) b2 = nb;
              }
            }
            pairs.sort(function (x, y) {
              return x.val - y.val;
            });
            pairs.slice(0, 2).forEach(function (p) {
              var A = acc[p.bi][at],
                E = egr[p.ai][et];
              out.push({
                pattern: pat,
                bi: p.bi,
                ai: p.ai,
                structure: at + '-bus-' + et,
                est: p.val,
                access: { type: at, s1: A.s1, s2: A.s2 },
                egress: { type: et, s3: E.s3, s4: E.s4 }
              });
            });
          });
        });
      });
    });
    out.sort(function (a, b) {
      return a.est - b.est;
    });
    var seen = {};
    return out.filter(function (c) {
      var k = c.pattern.route + '|' + c.pattern.stops[c.bi] + '|' + c.pattern.stops[c.ai] + '|' + c.structure;
      if (seen[k]) return false;
      seen[k] = 1;
      return true;
    });
  }
  function ceilMin(x) {
    return Math.ceil(x - 1e-9);
  }
  function clockText(ms) {
    try {
      return new Date(ms).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    } catch (e) {
      return '';
    }
  }
  /* The foot/bike/foot routing legs of a bike trip, as specs [{p, a, b}]. */
  function bikeSpecs(from, s1, s2, to) {
    return [
      { p: 'foot', a: from, b: stPt(s1) },
      { p: 'bike', a: stPt(s1), b: stPt(s2) },
      { p: 'foot', a: stPt(s2), b: to }
    ];
  }
  function candidateSpecs(c, ix, O, D) {
    var pat = c.pattern,
      b = ix.stops[pat.stops[c.bi]],
      a = ix.stops[pat.stops[c.ai]],
      bp = { lat: b.lat, lng: b.lng, name: b.name },
      ap = { lat: a.lat, lng: a.lng, name: a.name };
    var acc =
      c.access.type === 'walk' ? [{ p: 'foot', a: O, b: bp }] : bikeSpecs(O, c.access.s1, c.access.s2, bp);
    var egr =
      c.egress.type === 'walk' ? [{ p: 'foot', a: ap, b: D }] : bikeSpecs(ap, c.egress.s3, c.egress.s4, D);
    return { acc: acc, egr: egr, bp: bp, ap: ap, all: acc.concat(egr) };
  }
  function bikeNote() {
    return ['Includes ' + TP.UNLOCK_S + ' s to unlock and ' + TP.DOCK_S + ' s to dock.'];
  }
  /* Structured Indego station of a bike leg: the data the pins and the step text read, never parsed back out of a note. */
  function stationOf(s) {
    return {
      name: s.name || '',
      bikes: s.bikes | 0,
      ebikes: s.ebikes | 0,
      docks: s.docks | 0,
      asOf: s.asOf || null
    };
  }
  function mkLeg(mode, from, to, r, extraSec, basis, notes) {
    var raw = (r.seconds + extraSec) / 60;
    return {
      mode: mode,
      from: { lat: from.lat, lng: from.lng, name: from.name || '' },
      to: { lat: to.lat, lng: to.lng, name: to.name || '' },
      meters: Math.round(r.meters),
      minutes: ceilMin(raw),
      raw: raw,
      basis: basis,
      path: r.path.slice(),
      notes: notes || []
    };
  }
  function withStations(leg, s1, s2) {
    leg.stations = { from: stationOf(s1), to: stationOf(s2) };
    return leg;
  }
  /* Build the three legs of a bike trip from routed results [foot, bike, foot]. */
  function bikeTripLegs(rs, from, s1, s2, to) {
    return [
      mkLeg('walk', from, stPt(s1), rs[0], 0, 'routed', []),
      withStations(
        mkLeg('bike', stPt(s1), stPt(s2), rs[1], TP.UNLOCK_S + TP.DOCK_S, 'routed', bikeNote()),
        s1,
        s2
      ),
      mkLeg('walk', stPt(s2), to, rs[2], 0, 'routed', [])
    ];
  }
  function assembleBus(c, rs, spec, ix, veh) {
    var pat = c.pattern,
      k = 0,
      acc,
      egr,
      i;
    if (c.access.type === 'walk') {
      acc = [mkLeg('walk', spec.acc[0].a, spec.bp, rs[k], 0, 'routed', [])];
      k += 1;
    } else {
      acc = bikeTripLegs(rs.slice(k, k + 3), spec.acc[0].a, c.access.s1, c.access.s2, spec.bp);
      k += 3;
    }
    if (c.egress.type === 'walk') {
      egr = [mkLeg('walk', spec.ap, spec.egr[0].b, rs[k], 0, 'routed', [])];
    } else {
      egr = bikeTripLegs(rs.slice(k, k + 3), spec.ap, c.egress.s3, c.egress.s4, spec.egr[2].b);
    }
    var tArr = 0;
    acc.forEach(function (l) {
      tArr += l.raw;
    });
    var w = waitAtStop(pat, c.bi, tArr, veh);
    if (!w) return null;
    var ride = pat.mins[c.ai] - pat.mins[c.bi],
      raw = w.minutes + TP.BOARD_S / 60 + ride,
      path = [];
    for (i = c.bi; i <= c.ai; i++) {
      var s = ix.stops[pat.stops[i]];
      path.push([s.lat, s.lng]);
    }
    var notes = [
      w.basis === 'live'
        ? 'Wait is live: a tracked bus is ' +
          w.stopsAway +
          ' stop' +
          (w.stopsAway === 1 ? '' : 's') +
          ' upstream (scheduled running time, its current lateness is assumed to persist).'
        : 'Wait is typical, about half the ' + pat.hw + ' min headway; no tracked bus is upstream.',
      'Ride time is scheduled.',
      'Includes ' + TP.BOARD_S + ' s to board.'
    ];
    var bus = {
      mode: 'bus',
      from: spec.bp,
      to: spec.ap,
      meters: Math.round(distM(spec.bp, spec.ap)),
      minutes: ceilMin(raw),
      raw: raw,
      basis: w.basis,
      path: path,
      notes: notes,
      route: pat.route,
      kind: pat.kind || 'bus',
      head: pat.head || '',
      patternId: pat.id,
      stops: c.ai - c.bi,
      fromIdx: c.bi,
      toIdx: c.ai,
      waitMin: w.minutes,
      rideMin: ride,
      arriveMin: tArr,
      waitBasis: w.basis,
      rideBasis: 'scheduled',
      vehicleKey: w.vehicleKey
    };
    return acc.concat([bus], egr);
  }
  function optionOf(structure, legs) {
    var t = 0,
      m = 0;
    legs.forEach(function (l) {
      t += l.raw;
      m += l.meters;
    });
    /* Ranking and dominance use the exact sum `raw`; the shown total is its ceiling. Each leg shows its own rounded minutes, so
     the shown legs can add to more than the total (the card says so). */
    return { structure: structure, minutes: ceilMin(t), raw: t, meters: m, legs: legs };
  }
  /* 'Today' as a day number. Injectable for tests: opts.today or TP.today, as 'YYYYMMDD' or epoch ms; default is the local date. */
  function ymdIdx(s) {
    var m = /^(\d{4})(\d{2})(\d{2})$/.exec(String(s));
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) / 864e5 : null;
  }
  function tpTodayIdx(inj) {
    var v = inj != null ? inj : TP.today;
    if (typeof v === 'string' && ymdIdx(v) != null) return ymdIdx(v);
    var d = isNum(v) ? new Date(v) : new Date();
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 864e5;
  }
  /* The bus schedule's validity against today: null when fine, else {state:'expired'|'expiring', end, days}. */
  function scheduleState(feed, today) {
    var e = feed && ymdIdx(feed.end);
    if (e == null) return null;
    var days = e - today;
    if (days < 0) return { state: 'expired', end: feed.end, days: days };
    if (days <= TP.STALE_DAYS) return { state: 'expiring', end: feed.end, days: days };
    return null;
  }
  /* Routes that serve both ends of the trip (a pattern with a stop near the start before a stop near the finish) when none
   of them has a live vehicle; [] when at least one does, null when no route serves the trip at all. */
  function noLiveRoutes(ix, O, D, veh) {
    var nO = {},
      nD = {},
      serve = {},
      live = {};
    nearbyStops(ix, O, TP.BIKE_MAX_M).forEach(function (s) {
      nO[s.id] = 1;
    });
    nearbyStops(ix, D, TP.BIKE_MAX_M).forEach(function (s) {
      nD[s.id] = 1;
    });
    veh.forEach(function (v) {
      live[String(v.route)] = 1;
    });
    ix.net.patterns.forEach(function (p) {
      var first = -1,
        last = -1;
      p.stops.forEach(function (id, i) {
        if (nO[id] && first < 0) first = i;
        if (nD[id]) last = i;
      });
      if (first >= 0 && last > first) serve[p.route] = 1;
    });
    var rs = Object.keys(serve).sort();
    if (!rs.length) return null;
    return rs.some(function (r) {
      return live[r];
    })
      ? []
      : rs.slice(0, 4);
  }
  function planTrips(origin, dest, opts) {
    opts = opts || {};
    if (!origin || !dest || !isNum(origin.lat) || !isNum(origin.lng) || !isNum(dest.lat) || !isNum(dest.lng))
      return Promise.reject(tpFail('bad_input', 'Origin and destination need coordinates.'));
    if (!inRegion(origin) || !inRegion(dest))
      return Promise.reject(
        tpFail('out_of_area', 'That place is outside the area this planner covers (Philadelphia region).')
      );
    var O = { lat: origin.lat, lng: origin.lng, name: origin.name || 'Start' },
      D = { lat: dest.lat, lng: dest.lng, name: dest.name || 'Destination' };
    /* opts.ctx: the caller's cancel handle ({dead:false}); cancelPlan(ctx), or .cancel() on the returned promise, abandons the plan. */
    var ctx = opts.ctx && typeof opts.ctx === 'object' ? opts.ctx : {};
    if (!isNum(ctx.calls)) ctx.calls = 0;
    var notes = [];
    var today = tpTodayIdx(opts.today);
    /* Planner notes are structured: {code, ...data}. The UI words them. Legacy availability notes carry a ready-made `text`. */
    function note(code, extra) {
      for (var i = 0; i < notes.length; i++) if (notes[i].code === code) return;
      notes.push(Object.assign({ code: code }, extra || {}));
    }
    var pr = Promise.all([
      loadNetwork().then(
        function (x) {
          return x;
        },
        function () {
          return null;
        }
      ),
      loadIndego(true).then(
        function (x) {
          return x;
        },
        function () {
          return null;
        }
      )
    ]).then(function (r) {
      var nw = r[0],
        stations = r[1],
        veh,
        busUp = true;
      if (!stations)
        note('indego_unavailable', { text: 'Indego bike data unavailable, bike options hidden.' });
      if (opts.vehicles) veh = opts.vehicles;
      else {
        var src = typeof state !== 'undefined' && state && state.src ? state.src.bus : null;
        busUp = !!(src && src.ok && Date.now() - src.ok <= DROP_AFTER_MS && !src.stale && !skipped.bus);
        veh = busUp ? collect() : [];
        if (!busUp) note('bus_feed_unavailable', { text: 'Live bus data unavailable, bus options hidden.' });
      }
      veh = veh.filter(isBusKind);
      if (!nw) note('network_unavailable', { text: 'Bus schedule data unavailable, bus options hidden.' });
      else {
        var st = scheduleState(nw.net.feed, today);
        if (st) note('schedule_stale', st);
        if (busUp) {
          var nl = noLiveRoutes(nw.index, O, D, veh);
          if (nl && nl.length) note('no_live_bus', { routes: nl });
        }
      }
      /* Baseline structures: walk, car, walk-bike-walk. */
      var base = [],
        walkSpec = { p: 'foot', a: O, b: D },
        carSpec = { p: 'car', a: O, b: D },
        bikePair = null,
        bikeSpec = null;
      if (stations) {
        var bk = nearbyStations(stations, O, TP.STN_START_M, 'bike').slice(0, 3),
          dk = nearbyStations(stations, D, TP.STN_START_M, 'dock').slice(0, 3);
        bikePair = bestBikePair(O, D, bk, dk);
        if (bikePair) bikeSpec = bikeSpecs(O, bikePair.s1, bikePair.s2, D);
        else if (bk.length)
          note('no_indego_dock', { text: 'No free Indego dock near the destination, bike option hidden.' });
        else note('no_indego_bike', { text: 'No Indego bike available near the start, bike option hidden.' });
      }
      var keys = {};
      function addKeys(specs) {
        specs.forEach(function (s) {
          keys[routeKey(s.p, s.a, s.b)] = 1;
        });
      }
      addKeys([walkSpec, carSpec]);
      if (bikeSpec) addKeys(bikeSpec);
      /* Finalists: pre-ranked candidates in order, within the routing budget (unique legs) and the per-structure hedge. */
      var finals = [],
        perStruct = {},
        skipEst = null;
      if (nw && veh.length) {
        buildBusCandidates(nw.index, O, D, stations, veh).forEach(function (c) {
          if (finals.length >= TP.MAX_FINALISTS || (perStruct[c.structure] || 0) >= TP.PER_STRUCT_FINAL)
            return;
          var spec = candidateSpecs(c, nw.index, O, D),
            add = 0,
            seen = {};
          spec.all.forEach(function (s) {
            var k = routeKey(s.p, s.a, s.b);
            if (!keys[k] && !seen[k]) {
              seen[k] = 1;
              add++;
            }
          });
          if (Object.keys(keys).length + add > TP.MAX_CALLS) {
            if (skipEst == null) skipEst = c.est;
            return;
          }
          addKeys(spec.all);
          perStruct[c.structure] = (perStruct[c.structure] || 0) + 1;
          finals.push({ c: c, spec: spec });
        });
      }
      function go(s) {
        return routeLeg(s.p, s.a, s.b, ctx).then(
          function (v) {
            return { v: v };
          },
          function (e) {
            return { e: e };
          }
        );
      }
      var pWalk = go(walkSpec),
        pCar = go(carSpec),
        pBike = bikeSpec ? Promise.all(bikeSpec.map(go)) : null;
      var pFin = finals.map(function (f) {
        return Promise.all(f.spec.all.map(go));
      });
      function asOfOf() {
        return {
          indego: stations ? stations.asOf : null,
          network: nw ? { generated: nw.net.generated || null, feed: nw.net.feed || null } : null
        };
      }
      return pWalk.then(function (w) {
        if (w.e && w.e.code === 'no_route') {
          /* the routing service answered: there is no street path between the points */
          cancelPlan(ctx);
          return {
            options: [],
            notes: notes,
            bestMinutes: null,
            hiddenCount: 0,
            asOf: asOfOf(),
            stats: { routingCalls: ctx.calls, finalists: 0 }
          };
        }
        if (w.e) {
          cancelPlan(ctx);
          throw w.e;
        }
        return Promise.all([pCar, pBike || Promise.resolve(null), Promise.all(pFin)]).then(function (rest) {
          var options = [],
            car = rest[0],
            bk = rest[1];
          options.push(optionOf('walk', [mkLeg('walk', O, D, w.v, 0, 'routed', [])]));
          if (car.e) note('car_unavailable', { text: 'Car directions unavailable, car option hidden.' });
          else {
            var cl = mkLeg('car', O, D, car.v, 0, 'routed', [
              'No traffic or parking data: the time is for free-flowing roads and does not include finding parking.'
            ]);
            options.push(optionOf('car', [cl]));
          }
          if (bk) {
            if (
              bk.some(function (x) {
                return x.e;
              })
            )
              note('bike_unavailable', { text: 'Bike directions unavailable, bike option hidden.' });
            else
              options.push(
                optionOf(
                  'walk-bike-walk',
                  bikeTripLegs(
                    bk.map(function (x) {
                      return x.v;
                    }),
                    O,
                    bikePair.s1,
                    bikePair.s2,
                    D
                  )
                )
              );
          }
          var failed = 0,
            waitless = {};
          rest[2].forEach(function (rs, i) {
            if (
              rs.some(function (x) {
                return x.e;
              })
            ) {
              failed++;
              return;
            }
            var legs = assembleBus(
              finals[i].c,
              rs.map(function (x) {
                return x.v;
              }),
              finals[i].spec,
              nw.index,
              veh
            );
            if (legs) options.push(optionOf(finals[i].c.structure, legs));
            else waitless[finals[i].c.pattern.route] = 1;
          });
          /* Only when the call budget kept out a candidate that ranked ahead of one that was routed (or ahead of every one). */
          if (
            skipEst != null &&
            (!finals.length ||
              finals.some(function (f) {
                return f.c.est > skipEst;
              }))
          )
            note('routing_limit');
          if (failed) note('routing_failed', { count: failed });
          if (Object.keys(waitless).length) {
            var nl0 = null;
            notes.forEach(function (n) {
              if (n.code === 'no_live_bus') nl0 = n;
            });
            var rl = Object.keys(waitless).sort();
            if (nl0)
              nl0.routes = nl0.routes.concat(
                rl.filter(function (x) {
                  return nl0.routes.indexOf(x) < 0;
                })
              );
            else note('no_live_bus', { routes: rl });
          }
          options.sort(function (a, b) {
            return a.raw - b.raw;
          });
          /* An option that is not a single-mode baseline and takes at least as long as the best walk-only or bike-only
           trip is "dominated": shown after the main list, never hidden silently. Car is never a reference. */
          var ref = null,
            refKind = '';
          options.forEach(function (o) {
            if (o.structure === 'walk' && (!ref || o.raw < ref.raw)) {
              ref = o;
              refKind = 'walking';
            }
            if (o.structure === 'walk-bike-walk' && (!ref || o.raw < ref.raw)) {
              ref = o;
              refKind = 'biking';
            }
          });
          var best = null;
          options.forEach(function (o) {
            if (o.structure !== 'car' && (best == null || o.raw < best)) best = o.raw;
          });
          options.forEach(function (o) {
            var base = o.structure === 'walk' || o.structure === 'walk-bike-walk' || o.structure === 'car';
            o.dominated = !base && !!ref && o.raw >= ref.raw;
            if (o.dominated) o.dominatedReason = 'slower than ' + refKind + ' the whole way';
          });
          var per = {},
            res = [],
            hid = 0;
          options.forEach(function (o) {
            if (o.dominated || res.length >= TP.MAX_OUT || (per[o.structure] || 0) >= TP.PER_STRUCT_OUT)
              return;
            per[o.structure] = (per[o.structure] || 0) + 1;
            res.push(o);
          });
          options.forEach(function (o) {
            if (!o.dominated || hid >= TP.MAX_DOMINATED || (per[o.structure] || 0) >= TP.PER_STRUCT_OUT)
              return;
            per[o.structure] = (per[o.structure] || 0) + 1;
            hid++;
            res.push(o);
          });
          if (
            options.some(function (o) {
              return o.structure.indexOf('bus') >= 0;
            }) &&
            !res.some(function (o) {
              return o.structure.indexOf('bus') >= 0 && !o.dominated;
            })
          )
            note('no_bus_beats_baseline', { baseline: refKind });
          return {
            options: res,
            notes: notes,
            bestMinutes: best == null ? null : ceilMin(best),
            hiddenCount: hid,
            asOf: asOfOf(),
            stats: { routingCalls: ctx.calls, finalists: finals.length }
          };
        });
      });
    });
    pr.cancel = function () {
      cancelPlan(ctx);
    };
    pr.ctx = ctx;
    return pr;
  }
  /* ===== end Trip planner core ===== */

  S.planner.TP = TP;
  S.planner.resetPlannerCaches = resetPlannerCaches;
  S.planner.buildNetIndex = buildNetIndex;
  S.planner.loadNetwork = loadNetwork; /*@split*/
  S.planner.loadIndego = loadIndego;
  S.planner.routeLeg = routeLeg;
  S.planner.nearbyStops = nearbyStops;
  S.planner.nearbyStations = nearbyStations; /*@split*/
  S.planner.estimateTotal = estimateTotal;
  S.planner.waitAtStop = waitAtStop;
  S.planner.buildBusCandidates = buildBusCandidates;
  S.planner.clockText = clockText; /*@split*/
  S.planner.planTrips = planTrips;
  S.planner.cancelPlan = cancelPlan;
  S.planner.inRegion = inRegion; /*@split*/
})(); /*@split*/
