/* js/routing.js: trip planner data clients (bus network, Indego, routing service) with their caches, queue and fallbacks. No DOM. */
(function () {
  'use strict';
  var S = window.SEPTA;
  var isNum = S.util.isNum;
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
      } catch (x) {
        /* the error body is optional detail */
      }
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
      } catch (e) {
        /* aborting an already finished request is harmless */
      }
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
  S.routing.TP = TP;
  S.routing.buildNetIndex = buildNetIndex;
  S.routing.cancelPlan = cancelPlan;
  S.routing.cellOf = cellOf;
  S.routing.inRegion = inRegion;
  S.routing.loadIndego = loadIndego;
  S.routing.loadNetwork = loadNetwork;
  S.routing.resetPlannerCaches = resetPlannerCaches;
  S.routing.routeKey = routeKey;
  S.routing.routeLeg = routeLeg;
  S.routing.tpFail = tpFail;
})();
