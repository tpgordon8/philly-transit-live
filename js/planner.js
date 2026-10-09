/* js/planner.js: trip planner (plans bike, bus and walk structures from the candidates and the routing client, ranks them). No DOM. */
(function () {
  'use strict';
  var S = window.SEPTA;
  var DROP_AFTER_MS = S.util.DROP_AFTER_MS,
    distM = S.util.distM,
    isNum = S.util.isNum,
    state = S.util.state;
  var TP = S.routing.TP,
    cancelPlan = S.routing.cancelPlan,
    inRegion = S.routing.inRegion,
    loadIndego = S.routing.loadIndego,
    loadNetwork = S.routing.loadNetwork,
    routeKey = S.routing.routeKey,
    routeLeg = S.routing.routeLeg,
    tpFail = S.routing.tpFail;
  var bestBikePair = S.candidates.bestBikePair,
    buildBusCandidates = S.candidates.buildBusCandidates,
    isBusKind = S.candidates.isBusKind,
    nearbyStations = S.candidates.nearbyStations,
    nearbyStops = S.candidates.nearbyStops,
    stPt = S.candidates.stPt,
    waitAtStop = S.candidates.waitAtStop;
  var collect = S.feed.collect,
    skipped = S.feed.skipped;
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
      var walkSpec = { p: 'foot', a: O, b: D },
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

  S.planner.clockText = clockText;
  S.planner.planTrips = planTrips;
})();
