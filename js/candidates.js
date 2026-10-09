/* js/candidates.js: trip planner bus candidates (nearby stops and stations, wait estimates, pairing a boarding with an alighting stop). Pure functions, no DOM. */
(function () {
  'use strict';
  var S = window.SEPTA;
  var TP = S.routing.TP,
    cellOf = S.routing.cellOf;
  var distM = S.util.distM,
    toRad = S.util.toRad;
  var M_PER_DEG = 111195; /* metres per degree of latitude */
  var MIN_COS_LAT = 0.2; /* floor for cos(latitude) when widening the longitude box */
  /* ----- Pure planner functions ----- */
  function stPt(s) {
    return { lat: s.lat, lng: s.lon != null ? s.lon : s.lng, name: s.name };
  }
  function nearbyStops(index, point, meters) {
    var dLat = meters / M_PER_DEG,
      dLng = meters / (M_PER_DEG * Math.max(MIN_COS_LAT, Math.cos(toRad(point.lat)))),
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
  S.candidates.bestBikePair = bestBikePair;
  S.candidates.buildBusCandidates = buildBusCandidates;
  S.candidates.estimateTotal = estimateTotal;
  S.candidates.isBusKind = isBusKind;
  S.candidates.nearbyStations = nearbyStations;
  S.candidates.nearbyStops = nearbyStops;
  S.candidates.stPt = stPt;
  S.candidates.waitAtStop = waitAtStop;
})();
