/* js/stops.js: stop-board ETA math, stop links, stop card and live stop board. */
(function () {
  'use strict';
  var S = window.SEPTA;
  function alertRow() {
    return S.alerts.alertRow.apply(null, arguments);
  }
  function updateAlertRow() {
    return S.alerts.updateAlertRow.apply(null, arguments);
  }
  var angDiff = S.util.angDiff,
    bearing = S.util.bearing,
    distM = S.util.distM,
    distMi = S.util.distMi;
  /* ----- Stop board math. SEPTA publishes no bus predictions here, so an ETA exists only when it can be computed from
   measured data: straight-line distance (padded 15 %) over speed measured from successive GPS reports. ----- */
  var speedHist = {},
    HIST_WINDOW_S = 120,
    HIST_MAX = 6,
    MIN_SPAN_S = 20,
    STILL_MPS = 0.9,
    MAX_MPS = 31,
    ROAD_PAD = 1.15,
    ROUGH_DEG = 45,
    ROUGH_MAX_MI = 1.5; /* a rough ETA is offered only within this distance of the stop */
  /* Keep a short GPS history per vehicle: only new timestamps, only the last 120 s of feed time, at most 6 samples,
   and nothing for vehicles that left the feed. Called with every vehicle from each successful TransitView refresh. */
  function updateSpeedHist(list) {
    var newest = 0,
      seen = {},
      i,
      v,
      h,
      last,
      k;
    for (i = 0; i < list.length; i++) if (list[i].ts > newest) newest = list[i].ts;
    for (i = 0; i < list.length; i++) {
      v = list[i];
      seen[v.key] = 1;
      h = speedHist[v.key] || [];
      last = h[h.length - 1];
      if (isFinite(v.ts) && (!last || v.ts > last.ts)) h.push({ ts: v.ts, lat: v.lat, lng: v.lng });
      h = h.filter(function (x) {
        return newest - x.ts <= HIST_WINDOW_S;
      });
      if (h.length > HIST_MAX) h = h.slice(h.length - HIST_MAX);
      if (h.length) speedHist[v.key] = h;
      else delete speedHist[v.key];
    }
    for (k in speedHist) if (!seen[k]) delete speedHist[k];
  }
  /* Meters per second between the oldest and newest sample, or null when it can't be trusted, 0 when not moving. */
  function speedMps(key) {
    var h = speedHist[key];
    if (!h || h.length < 2) return null;
    var a = h[0],
      b = h[h.length - 1],
      span = b.ts - a.ts;
    if (!(span >= MIN_SPAN_S)) return null;
    for (var i = 1; i < h.length; i++) {
      var dt = h[i].ts - h[i - 1].ts;
      if (dt > 0 && distM(h[i - 1], h[i]) / dt > MAX_MPS) return null; /* a GPS jump between two reports */
    }
    var sp = distM(a, b) / span;
    if (sp > MAX_MPS) return null;
    return sp < STILL_MPS ? 0 : sp;
  }
  /* The bus whose very next stop is this stop gets a plain estimate. A bus heading toward the stop (within 45 degrees,
   1.5 mi, its own next stop known and different) gets a ROUGH one, flagged rough:true. Both need a measured speed. */
  function etaFor(v, stop) {
    if (!v || !stop) return { min: null, note: 'not its next stop yet', rough: false };
    var isNext = v.nextId === stop.id,
      rough = false;
    if (!isNext) {
      var d = distMi(v, stop);
      rough =
        !!v.nextId &&
        d <= ROUGH_MAX_MI &&
        v.heading != null &&
        angDiff(v.heading, bearing(v, stop)) <= ROUGH_DEG;
      if (!rough) return { min: null, note: 'not its next stop yet', rough: false };
    }
    var sp = speedMps(v.key);
    if (sp == null) return { min: null, note: 'measuring speed', rough: false };
    if (sp === 0) return { min: null, note: 'not moving', rough: false };
    return {
      min: Math.max(1, Math.ceil((distM(v, stop) * ROAD_PAD) / sp / 60)),
      note: rough ? 'rough: not its next stop yet' : '',
      rough: rough
    };
  }
  S.stops.speedHist = speedHist;
  S.stops.updateSpeedHist = updateSpeedHist;
  S.stops.speedMps = speedMps;
  S.stops.etaFor = etaFor;
  if (S.halt) return;
  var $ = S.util.$,
    DROP_AFTER_MS = S.util.DROP_AFTER_MS,
    el = S.util.el;
  var lateInfo = S.util.lateInfo,
    num = S.util.num,
    state = S.util.state;
  var collect = S.feed.collect,
    septa = S.feed.septa;
  var map = S.map.map,
    mapEl = S.map.mapEl,
    select = S.map.select,
    setCenter = S.panel.setCenter;
  /* ----- Shareable stop links (#stop=<id>&route=<route>) -----
   Stop lists come from the Worker (Stops?route=), are cached per route in memory, and never include anything personal. */
  var stopCache = {},
    stopLayer = null,
    stopSeq = 0;
  var STOP_ID_RE = /^[0-9]{1,8}$/,
    STOP_RT_RE = /^[A-Za-z0-9]{1,6}$/;
  function loadStops(route) {
    if (!stopCache[route]) {
      stopCache[route] = septa('Stops?route=' + route)
        .then(function (j) {
          if (!Array.isArray(j)) throw new Error('bad stops');
          return j;
        })
        .catch(function (e) {
          delete stopCache[route];
          throw e;
        });
    }
    return stopCache[route];
  }
  function setHash(h) {
    try {
      history.replaceState(null, '', location.pathname + h);
    } catch (e) {
      /* history can be blocked (sandboxed frames); the link is a convenience */
    }
  }
  function stopLink(st) {
    return location.origin + location.pathname + '#stop=' + st.id + '&route=' + st.route;
  }
  function clearStop() {
    stopSeq++;
    state.stop = null;
    if (stopLayer) {
      stopLayer.remove();
      stopLayer = null;
    }
    $('#stopCard').hidden = true;
    $('#stopCard').replaceChildren();
    try {
      history.replaceState(null, '', location.pathname);
    } catch (e) {
      /* history can be blocked (sandboxed frames); the link is a convenience */
    }
  }
  var stopOpener = null;
  /* Close the stop card and put focus back where it came from (the opener if it is still on screen, else the map). */
  function closeStop() {
    var o = stopOpener,
      had = $('#stopCard').contains(document.activeElement);
    stopOpener = null;
    clearStop();
    if (had) {
      /* The vehicle card is rebuilt while the stop opens, so the opener is usually a fresh copy with the same id. */
      if (o && !o.isConnected && o.id) o = document.getElementById(o.id);
      var t = o && o.isConnected && o.getClientRects().length ? o : mapEl;
      t.focus({ preventScroll: true });
    }
  }
  function renderStopCard(st, err, retry) {
    var box = $('#stopCard');
    box.hidden = false;
    box.replaceChildren();
    box.setAttribute('aria-label', st ? 'Stop ' + st.name : 'Stop details');
    var close = el('button', 'btn small ghost', 'Close');
    close.type = 'button';
    close.id = 'stopClose';
    close.setAttribute('aria-label', 'Close stop');
    close.addEventListener('click', closeStop);
    if (err) {
      box.appendChild(el('div', 'err', err));
      var r = el('div', 'row');
      if (retry) {
        var rb = el('button', 'btn small', 'Retry');
        rb.type = 'button';
        rb.id = 'stopRetry';
        rb.addEventListener('click', retry);
        r.appendChild(rb);
      }
      r.appendChild(close);
      box.appendChild(r);
      return;
    }
    box.appendChild(el('b', null, st.name));
    box.appendChild(el('div', 'sub', 'Stop ' + st.id + ' · Route ' + st.route));
    var row = el('div', 'row');
    var cp = el('button', 'btn small ghost', 'Copy link');
    cp.type = 'button';
    cp.id = 'copyStop';
    var live = el('div', 'live');
    live.id = 'stopLive';
    live.setAttribute('aria-live', 'polite');
    live.setAttribute('role', 'status');
    cp.addEventListener('click', function () {
      var url = stopLink(st);
      function manual() {
        var old = box.querySelector('#stopUrl');
        if (old) old.remove();
        var inp = el('input');
        inp.id = 'stopUrl';
        inp.readOnly = true;
        inp.value = url;
        inp.setAttribute('aria-label', 'Stop link');
        box.insertBefore(inp, live);
        inp.focus();
        inp.select();
        live.textContent = 'Copy this link';
      }
      try {
        navigator.clipboard.writeText(url).then(function () {
          live.textContent = 'Link copied';
        }, manual);
      } catch (e) {
        manual();
      }
    });
    row.appendChild(cp);
    row.appendChild(close);
    box.appendChild(row);
    box.appendChild(live);
    var board = el('div', 'sboard');
    board.id = 'stopBoard';
    box.appendChild(board);
    box.appendChild(alertRow(st));
    updateAlertRow();
    renderStopBoard();
  }
  function drawStopMarker(st) {
    if (stopLayer) {
      stopLayer.remove();
    }
    stopLayer = L.marker([st.lat, st.lng], {
      icon: L.divIcon({
        className: 'pin stop-pin',
        html: '<span class="stp"></span>',
        iconSize: [24, 24],
        iconAnchor: [12, 12]
      }),
      title: 'Stop: ' + st.name,
      keyboard: false,
      interactive: false,
      zIndexOffset: 900
    }).addTo(map);
  }
  /* ----- Stop board: buses on this stop's route, with ETAs only where they can be measured ----- */
  var BOARD_MAX = 5,
    HEAD_MI = 1.5,
    HEAD_DEG = 60;
  function boardRows(stop, all) {
    var a = [],
      b = [];
    all.forEach(function (v) {
      if (v.kind === 'train' || v.kind === 'subway' || v.route !== stop.route) return;
      var d = distMi(v, stop);
      if (v.nextId === stop.id) {
        a.push({ v: v, d: d, eta: etaFor(v, stop) });
        return;
      }
      if (d <= HEAD_MI && v.heading != null && angDiff(v.heading, bearing(v, stop)) <= HEAD_DEG)
        b.push({ v: v, d: d, eta: etaFor(v, stop) });
    });
    a.sort(function (x, y) {
      var ex = x.eta.min,
        ey = y.eta.min;
      if (ex == null && ey != null) return 1;
      if (ex != null && ey == null) return -1;
      if (ex !== ey && ex != null) return ex - ey;
      return x.d - y.d;
    });
    b.sort(function (x, y) {
      return x.d - y.d;
    });
    return { a: a.slice(0, BOARD_MAX), b: b.slice(0, Math.max(0, BOARD_MAX - a.length)) };
  }
  function boardMi(d) {
    return Math.max(0.1, d).toFixed(1) + ' mi';
  }
  function boardRow(r) {
    var v = r.v,
      btn = el('button', 'sbrow');
    btn.type = 'button';
    btn.dataset.key = v.key;
    btn.appendChild(el('span', 'rbadge k-' + v.kind, v.badge));
    var mid = el('span', 'sbmid');
    mid.appendChild(el('span', 'sbdir', v.direction || 'Direction not reported'));
    mid.appendChild(el('span', 'sbdist', boardMi(r.d) + ' away'));
    var li = lateInfo(v.late);
    mid.appendChild(el('span', 'pill ' + li.cls, li.txt));
    btn.appendChild(mid);
    var eta = el('span', 'sbeta');
    eta.appendChild(
      el(
        'b',
        r.eta.rough ? 'rough' : r.eta.min == null ? 'none' : null,
        r.eta.min == null ? '—' : (r.eta.rough ? '~' : '') + r.eta.min + ' min'
      )
    );
    if (r.eta.note) eta.appendChild(el('small', null, r.eta.note));
    btn.appendChild(eta);
    return btn;
  }
  function renderStopBoard() {
    var box = $('#stopBoard'),
      st = state.stop;
    if (!box || !st) return;
    var card = $('#stopCard'),
      top = card.scrollTop,
      fk = null,
      ae = document.activeElement;
    if (ae && box.contains(ae) && ae.dataset) fk = ae.dataset.key;
    var b = state.src.bus,
      now = Date.now();
    box.replaceChildren();
    if (!b.ok || now - b.ok > DROP_AFTER_MS) {
      box.appendChild(el('div', 'sbmsg', 'Live data unavailable. No arrival times are shown.'));
      return;
    }
    var rows = boardRows(st, collect());
    if (!rows.a.length && !rows.b.length) {
      box.appendChild(
        el('div', 'sbmsg', 'No buses on route ' + st.route + ' are heading to this stop right now.')
      );
    } else {
      [
        ['Arriving next', rows.a],
        ['Heading toward this stop', rows.b]
      ].forEach(function (g) {
        if (!g[1].length) return;
        box.appendChild(el('div', 'sbh', g[0]));
        g[1].forEach(function (r) {
          box.appendChild(boardRow(r));
        });
      });
    }
    if (b.stale) box.appendChild(el('div', 'sbstale', 'Positions may be out of date'));
    box.appendChild(el('div', 'sbfine', 'Estimates from distance and recent speed, not SEPTA predictions.'));
    var age = el('div', 'sbfine');
    age.id = 'boardAge';
    box.appendChild(age);
    updateBoardAge();
    card.scrollTop = top;
    if (fk) {
      var f = null;
      box.querySelectorAll('button[data-key]').forEach(function (x) {
        if (x.dataset.key === fk) f = x;
      });
      if (f) f.focus({ preventScroll: true });
    }
  }
  function updateBoardAge() {
    var n = $('#boardAge'),
      b = state.src.bus;
    if (n && b.ok) n.textContent = 'Updated ' + Math.max(0, Math.round((Date.now() - b.ok) / 1000)) + 's ago';
  }
  $('#stopCard').addEventListener('click', function (e) {
    var r = e.target.closest('.sbrow');
    if (r && r.dataset.key) select(r.dataset.key);
  });
  function openStop(route, id, opts) {
    route = String(route == null ? '' : route);
    id = String(id == null ? '' : id);
    if (!STOP_ID_RE.test(id) || !STOP_RT_RE.test(route)) return;
    var seq = ++stopSeq,
      focusCard = function () {
        if (opts && opts.focus) $('#stopCard').focus({ preventScroll: true });
      };
    stopOpener = (opts && opts.opener) || null;
    loadStops(route).then(
      function (list) {
        if (seq !== stopSeq) return;
        var f = null;
        for (var i = 0; i < list.length; i++)
          if (String(list[i].stopid) === id) {
            f = list[i];
            break;
          }
        var lat = f && num(f.lat),
          lng = f && num(f.lng);
        if (!f || lat == null || lng == null) {
          state.stop = null;
          if (stopLayer) {
            stopLayer.remove();
            stopLayer = null;
          }
          renderStopCard(null, "That stop couldn't be found on route " + route + '.');
          focusCard();
          return;
        }
        var st = { id: id, name: String(f.stopname || 'Stop ' + id), lat: lat, lng: lng, route: route };
        state.stop = st;
        drawStopMarker(st);
        renderStopCard(st);
        focusCard();
        map.setView([lat, lng], Math.max(map.getZoom(), 16));
        setCenter({ lat: lat, lng: lng, label: st.name }, false, true);
        setHash('#stop=' + id + '&route=' + route);
      },
      function () {
        if (seq !== stopSeq) return;
        state.stop = null;
        if (stopLayer) {
          stopLayer.remove();
          stopLayer = null;
        }
        renderStopCard(null, "Couldn't load stops right now.", function () {
          openStop(route, id, { focus: true, opener: opts && opts.opener });
        });
        focusCard();
      }
    );
  }
  function stopFromHash(user) {
    var p;
    try {
      p = new URLSearchParams(location.hash.slice(1));
    } catch (e) {
      return;
    }
    var id = p.get('stop'),
      route = p.get('route');
    if (id == null || route == null || !STOP_ID_RE.test(id) || !STOP_RT_RE.test(route)) return;
    if (state.stop && state.stop.id === id && state.stop.route === route) return;
    openStop(route, id, user === true ? { focus: true } : null);
  }
  window.addEventListener('hashchange', function () {
    stopFromHash(true);
  });
  S.stops.STOP_ID_RE = STOP_ID_RE;
  S.stops.STOP_RT_RE = STOP_RT_RE;
  S.stops.closeStop = closeStop;
  S.stops.renderStopBoard = renderStopBoard;
  S.stops.updateBoardAge = updateBoardAge;
  S.stops.openStop = openStop;
  S.stops.stopFromHash = stopFromHash;
})();
