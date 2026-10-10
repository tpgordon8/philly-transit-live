/* js/nearby.js: Nearby stops. After a search or Use my location, the nearest bus and trolley stops are listed under the search area.
   The stops come from data/bus-network.json (the planner's file), loaded through S.routing.loadNetwork on the first such search, never at
   page load, and kept in memory for the session (one fetch, about 279 KB gzipped). A row opens the existing stop card. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var $ = S.util.$,
    el = S.util.el,
    distMi = S.util.distMi,
    M_PER_MI = S.util.M_PER_MI;
  var NEAR_MAX = 5,
    NEAR_RADII_M = [
      400, 800, 1600
    ] /* widened until NEAR_MAX stops are found; nothing is listed beyond a mile */,
    NEAR_CHIPS = 6,
    FT_PER_MI = 5280,
    FT_STEP = 50 /* distances under 950 ft are rounded to this */,
    FT_MAX = 950;
  var seq = 0,
    byStopCache = null; /* {index, by: stop id -> [{route, kind}]} for the loaded network */
  function routeOrder(a, b) {
    var x = parseInt(a.route, 10),
      y = parseInt(b.route, 10);
    if (isNaN(x) !== isNaN(y)) return isNaN(x) ? 1 : -1;
    return x - y || (a.route < b.route ? -1 : a.route > b.route ? 1 : 0);
  }
  /* Stop id -> the routes that serve it, numbered routes first in numeric order. Built once per loaded network. */
  function routesByStop(index) {
    if (byStopCache && byStopCache.index === index) return byStopCache.by;
    var by = {};
    index.net.patterns.forEach(function (p) {
      p.stops.forEach(function (id) {
        var list = by[id] || (by[id] = []);
        if (
          !list.some(function (r) {
            return r.route === p.route;
          })
        )
          list.push({ route: p.route, kind: p.kind === 'trolley' ? 'trolley' : 'bus' });
      });
    });
    for (var id in by) by[id].sort(routeOrder);
    byStopCache = { index: index, by: by };
    return by;
  }
  function miles(m) {
    var ft = (m / M_PER_MI) * FT_PER_MI;
    if (ft < FT_MAX) return Math.max(FT_STEP, Math.round(ft / FT_STEP) * FT_STEP) + ' ft';
    return (ft / FT_PER_MI).toFixed(1) + ' mi';
  }
  /* The route to open: the one with the tracked bus nearest the stop, else the first. */
  function pickRoute(stop, routes, vehicles) {
    var best = null,
      bd = Infinity;
    vehicles.forEach(function (v) {
      if (v.kind === 'train' || v.kind === 'subway') return;
      var d = distMi(v, stop);
      if (
        d < bd &&
        routes.some(function (r) {
          return r.route === String(v.route);
        })
      ) {
        best = String(v.route);
        bd = d;
      }
    });
    return best || routes[0].route;
  }
  function nearest(index, c) {
    var by = routesByStop(index),
      out = [];
    for (var i = 0; i < NEAR_RADII_M.length && out.length < NEAR_MAX; i++)
      out = S.candidates.nearbyStops(index, c, NEAR_RADII_M[i]).filter(function (s) {
        return !!by[s.id];
      });
    return out.slice(0, NEAR_MAX).map(function (s) {
      return { s: s, routes: by[s.id] };
    });
  }
  function row(x, vehicles) {
    var s = x.s,
      route = pickRoute(s, x.routes, vehicles),
      li = el('li'),
      b = el('button', 'near-row'),
      dist = miles(s.d),
      shown = x.routes.slice(0, NEAR_CHIPS),
      chips = el('span', 'near-rts');
    b.type = 'button';
    b.setAttribute(
      'aria-label',
      s.name +
        ', ' +
        dist +
        ', route' +
        (x.routes.length === 1 ? ' ' : 's ') +
        x.routes
          .map(function (r) {
            return r.route;
          })
          .join(', ')
    );
    b.appendChild(el('span', 'near-nm', s.name || 'Stop ' + s.id));
    b.appendChild(el('span', 'near-d', dist));
    shown.forEach(function (r) {
      chips.appendChild(el('span', 'rbadge near-chip k-' + r.kind, r.route));
    });
    if (x.routes.length > shown.length)
      chips.appendChild(el('span', 'near-more', '+' + (x.routes.length - shown.length) + ' more'));
    b.appendChild(chips);
    b.addEventListener('click', function () {
      S.map.clearSelection(); /* the vehicle card would hide the stop card on a narrow map */
      S.stops.openStop(route, s.id, { focus: true, opener: b });
    });
    li.appendChild(b);
    return li;
  }
  /* The live region doubles as the visible line while loading or after a failure; after a good load it stays for screen readers only. */
  function status(text, visible) {
    var p = $('#nearStatus');
    p.textContent = text;
    p.classList.toggle('sr-only', !visible);
  }
  function render(index, c) {
    var rows = nearest(index, c),
      list = $('#nearList'),
      v = S.feed.collect();
    list.replaceChildren();
    rows.forEach(function (x) {
      list.appendChild(row(x, v));
    });
    $('#nearHint').hidden = !rows.length;
    if (rows.length) status(rows.length + (rows.length === 1 ? ' nearby stop' : ' nearby stops'), false);
    else status('No bus or trolley stops within a mile of here', true);
  }
  /* c: the new search point. Called whenever the saved search location changes (panel.js setCenter). */
  function show(c) {
    var mine = ++seq;
    $('#nearSec').hidden = false;
    $('#nearList').replaceChildren();
    $('#nearHint').hidden = true;
    status('Finding nearby stops', true);
    S.routing.loadNetwork().then(
      function (n) {
        if (mine === seq) render(n.index, c);
      },
      function () {
        if (mine !== seq) return;
        status('Nearby stops unavailable right now', true);
      }
    );
  }
  S.nearby.show = show;
})();
