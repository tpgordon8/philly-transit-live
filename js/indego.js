/* js/indego.js: Indego bike stations on the map (ARCHITECTURE.md 15.5). A mode chip, a layer of station markers, a hint when the
   map is zoomed out, and a small station card. Data comes from S.routing.loadIndego (the trip planner's client: Worker first, cached). */
(function () {
  'use strict';
  var S = window.SEPTA;
  S.indego = S.indego || {};
  if (S.halt) return;
  var $ = S.util.$,
    el = S.util.el,
    state = S.util.state;
  var map = S.map.map,
    mapEl = S.map.mapEl,
    animOK = S.map.animOK,
    CARD_NARROW = S.map.CARD_NARROW;
  var MIN_ZOOM = 14 /* stations show from this zoom */,
    FULL_ZOOM = 16 /* from here every station in view is drawn; below it the nearest MAX_MARKERS to the centre */,
    MAX_MARKERS = 150,
    POLL_MS = 60000 /* status refresh while the layer is on, the tab is visible and the rider is active */,
    DIM_AFTER_MS = 180000; /* markers dim when the last good answer is this old and a refresh has failed */
  var stage = $('#stage'),
    chipInput = document.querySelector('#modes input[data-mode="indego"]'),
    countEl = $('#indegoN');
  var layer = L.layerGroup().addTo(map);
  var markers = new Map(); /* station id -> Leaflet marker */
  var data = null /* merged station list from the last good answer */,
    byId = {},
    fetchedAt = 0,
    feedAsOf = 0,
    failedAt = 0 /* time of the latest failed refresh, 0 after a good one */,
    inflight = false,
    pollTimer = null,
    selected = null /* id of the station whose card is open */,
    lastOn = false;

  /* ----- Hint pill and live region ----- */
  var hint = el('div', 'ind-hint');
  hint.id = 'indegoHint';
  hint.setAttribute('role', 'status');
  hint.hidden = true;
  var card = el('div');
  card.id = 'indegoCard';
  card.hidden = true;
  card.tabIndex = -1;
  card.setAttribute('role', 'region');
  card.setAttribute('aria-label', 'Indego station details');
  var live = el('div', 'sr-only');
  live.id = 'indegoLive';
  live.setAttribute('role', 'status');
  live.setAttribute('aria-live', 'polite');
  stage.appendChild(hint);
  stage.appendChild(card);
  stage.appendChild(live);

  function isOn() {
    return !!state.filters.indego;
  }
  function zoomOK() {
    return map.getZoom() >= MIN_ZOOM;
  }
  function plural(n, one, many) {
    return n + ' ' + (n === 1 ? one : many);
  }

  /* ----- Station facts ----- */
  /* Bikes you can take and docks you can return to: a station that is not renting counts as 0 bikes, one that is not taking returns as 0 docks. */
  function bikesOf(s) {
    return s.renting ? s.bikes : 0;
  }
  function docksOf(s) {
    return s.returning ? s.docks : 0;
  }
  function availCls(n) {
    return n === 0 ? 'av-none' : n <= 2 ? 'av-low' : 'av-ok';
  }
  function labelOf(s) {
    var b = bikesOf(s),
      d = docksOf(s);
    return (
      'Indego station ' +
      s.name +
      ', ' +
      plural(b, 'bike', 'bikes') +
      ', ' +
      plural(d, 'open dock', 'open docks') +
      (s.installed ? '' : ', out of service')
    );
  }
  function isDim() {
    return !!failedAt && !!fetchedAt && Date.now() - fetchedAt > DIM_AFTER_MS;
  }
  var BIKE =
    '<svg class="ind-ic" viewBox="0 0 16 12" width="14" height="11" aria-hidden="true"><circle cx="3.5" cy="8.5" r="2.7"/><circle cx="12.5" cy="8.5" r="2.7"/><path d="M3.5 8.5L6.5 3H9.5M6.5 3L9 8.5H12.5M9 8.5L11 3H12.8"/><path class="ind-slash" d="M1 11.5L15 .5"/></svg>';
  function markerInner(s) {
    return BIKE + '<span class="ind-n">' + bikesOf(s) + '</span>';
  }
  function sigOf(s) {
    return bikesOf(s) + '|' + docksOf(s) + '|' + (s.installed ? 1 : 0) + '|' + s.name;
  }

  /* ----- Markers ----- */
  function applyDim() {
    var d = isDim();
    markers.forEach(function (m) {
      var e = m.getElement();
      if (e) e.classList.toggle('stale', d);
    });
  }
  function makeMarker(s) {
    var m = L.marker([s.lat, s.lon], {
      icon: L.divIcon({
        className: 'ind-wrap',
        html: '<span class="ind-b ' + availCls(bikesOf(s)) + '">' + markerInner(s) + '</span>',
        iconSize: [44, 44],
        iconAnchor: [22, 38]
      }),
      keyboard: true,
      zIndexOffset: -300
    });
    m.on('click', function () {
      openCard(s.id);
    });
    m.addTo(layer);
    var e = m.getElement();
    if (e) {
      e.setAttribute('role', 'button');
      e.tabIndex = 0;
      e.dataset.sig = sigOf(s);
      e.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
          ev.preventDefault();
          ev.stopPropagation();
          openCard(s.id, { focus: true });
        }
      });
    }
    return m;
  }
  function updateMarker(m, s) {
    var e = m.getElement();
    if (!e) return;
    var lbl = labelOf(s);
    if (e.getAttribute('aria-label') !== lbl) e.setAttribute('aria-label', lbl);
    if (e.getAttribute('title') !== s.name) e.setAttribute('title', s.name);
    var sig = sigOf(s);
    if (e.dataset.sig !== sig) {
      e.dataset.sig = sig;
      var b = e.querySelector('.ind-b');
      b.className = 'ind-b ' + availCls(bikesOf(s));
      b.innerHTML = markerInner(s);
    }
    e.classList.toggle('sel', selected === s.id);
    e.classList.toggle('out', !s.installed);
    m.setZIndexOffset(selected === s.id ? 600 : -300);
  }
  function clearMarkers() {
    layer.clearLayers();
    markers.clear();
  }
  /* The stations to draw: those inside the visible map; below zoom FULL_ZOOM only the MAX_MARKERS nearest the centre. */
  function render() {
    var on = isOn() && zoomOK() && !!data;
    if (!on) {
      clearMarkers();
      setCount('');
      renderHint();
      return;
    }
    var b = map.getBounds().pad(0.05),
      c = map.getCenter(),
      k = Math.cos((c.lat * Math.PI) / 180);
    var view = data.filter(function (s) {
      return b.contains([s.lat, s.lon]);
    });
    setCount(view.length);
    var show = view;
    if (map.getZoom() < FULL_ZOOM && view.length > MAX_MARKERS) {
      var dist = function (s) {
        var dx = (s.lon - c.lng) * k,
          dy = s.lat - c.lat;
        return dx * dx + dy * dy;
      };
      show = view
        .slice()
        .sort(function (a, z) {
          return dist(a) - dist(z);
        })
        .slice(0, MAX_MARKERS);
    }
    var keep = new Set();
    show.forEach(function (s) {
      keep.add(s.id);
    });
    if (selected && byId[selected]) {
      keep.add(selected);
      if (show.indexOf(byId[selected]) < 0) show = show.concat(byId[selected]);
    }
    markers.forEach(function (m, id) {
      if (!keep.has(id)) {
        layer.removeLayer(m);
        markers.delete(id);
      }
    });
    show.forEach(function (s) {
      var m = markers.get(s.id);
      if (!m) {
        m = makeMarker(s);
        markers.set(s.id, m);
      }
      updateMarker(m, s);
    });
    applyDim();
    renderHint();
  }
  function setCount(n) {
    if (countEl && countEl.textContent !== String(n)) countEl.textContent = n;
  }

  /* ----- Hint pill: zoom hint, or the data note when bike data cannot be loaded ----- */
  function hintText() {
    if (!isOn()) return '';
    if (!zoomOK()) return 'Zoom in to see Indego stations';
    if (failedAt && !data) return 'Indego bike data unavailable';
    if (failedAt) return 'Indego bike data unavailable. Showing the last known bikes.';
    return '';
  }
  function renderHint() {
    var t = hintText();
    if (hint.textContent !== t) hint.textContent = t;
    hint.hidden = !t;
  }

  /* ----- Data ----- */
  function load(fresh) {
    if (inflight) return;
    inflight = true;
    S.routing.loadIndego(fresh === true).then(
      function (list) {
        inflight = false;
        data = list;
        byId = {};
        list.forEach(function (s) {
          if (!s.name) s.name = 'Indego station';
          byId[s.id] = s;
        });
        fetchedAt = Date.now();
        feedAsOf =
          list.asOf > 0 && Math.abs(fetchedAt - list.asOf) < 3600000
            ? Math.min(list.asOf, fetchedAt)
            : fetchedAt;
        failedAt = 0;
        render();
        if (selected) fillCard();
      },
      function () {
        inflight = false;
        failedAt = Date.now();
        render();
        if (selected) fillCard();
      }
    );
  }
  function wantPoll() {
    return isOn() && zoomOK() && !document.hidden && !S.feed.idleNow();
  }
  /* Status refresh runs only while the chip is on, the map is zoomed in, the tab is visible and the rider has been active within the
     hour (the vehicle feed's idle pause). A visible tab with no timer starts one and asks at once; the routing client reuses an answer under a minute old. */
  function syncPolling() {
    if (wantPoll()) {
      if (!pollTimer) {
        pollTimer = setInterval(function () {
          if (wantPoll()) load(true);
          else syncPolling();
        }, POLL_MS);
        load(false);
      }
    } else if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }
  function sync() {
    lastOn = isOn();
    if (!lastOn || !zoomOK()) closeCard();
    syncPolling();
    render();
  }

  /* ----- Station card ----- */
  function ageText() {
    var s = Math.max(0, Math.round((Date.now() - (feedAsOf || fetchedAt)) / 1000));
    if (s < 90) return 'Updated ' + s + ' s ago';
    var m = Math.round(s / 60);
    return m < 90 ? 'Updated ' + m + ' min ago' : 'Updated over an hour ago';
  }
  function cardFields() {
    return {
      head: $('#indegoHead'),
      badge: $('#indegoBadge'),
      sum: $('#indegoSum'),
      types: $('#indegoTypes'),
      note: $('#indegoNote'),
      age: $('#indegoAge'),
      dir: $('#indegoDir')
    };
  }
  function buildCard() {
    card.replaceChildren();
    var head = el('div', 'dh');
    var badge = el('span', 'ind-b ind-badge');
    badge.id = 'indegoBadge';
    var dt = el('div', 'dt');
    var hd = el('b');
    hd.id = 'indegoHead';
    hd.tabIndex = -1;
    dt.appendChild(hd);
    dt.appendChild(el('span', null, 'Indego bike share'));
    var close = el('button', 'btn small ghost', 'Close');
    close.type = 'button';
    close.id = 'indegoClose';
    close.setAttribute('aria-label', 'Close station details');
    close.addEventListener('click', function () {
      closeCard({ focus: true });
    });
    head.appendChild(badge);
    head.appendChild(dt);
    head.appendChild(close);
    var body = el('div', 'ind-body');
    var sum = el('p', 'ind-sum');
    sum.id = 'indegoSum';
    var types = el('p', 'ind-sub');
    types.id = 'indegoTypes';
    var note = el('p', 'ind-note');
    note.id = 'indegoNote';
    var age = el('p', 'ind-sub');
    age.id = 'indegoAge';
    var dir = el('button', 'btn small primary', 'Walk here');
    dir.type = 'button';
    dir.id = 'indegoDir';
    dir.addEventListener('click', directions);
    [sum, types, note, age, dir].forEach(function (n) {
      body.appendChild(n);
    });
    card.appendChild(head);
    card.appendChild(body);
  }
  function fillCard() {
    var s = byId[selected];
    if (!s) return;
    var f = cardFields(),
      b = bikesOf(s),
      d = docksOf(s);
    f.head.textContent = s.name;
    f.badge.className = 'ind-b ind-badge ' + availCls(b);
    f.badge.innerHTML = markerInner(s);
    f.sum.textContent = plural(b, 'bike', 'bikes') + ', ' + plural(d, 'open dock', 'open docks');
    var split = s.ebikes + s.classic === s.bikes && b > 0;
    f.types.textContent = split ? s.ebikes + ' electric, ' + s.classic + ' classic' : '';
    f.types.hidden = !split;
    f.note.textContent = !s.installed
      ? 'This station is out of service right now.'
      : !s.renting
        ? 'Bikes cannot be taken from this station right now.'
        : !s.returning
          ? 'Bikes cannot be returned to this station right now.'
          : '';
    f.note.hidden = !f.note.textContent;
    f.age.textContent = ageText() + (isDim() ? '. May be out of date.' : '');
    f.dir.setAttribute('aria-label', 'Walk to ' + s.name);
  }
  /* On a phone the card covers most of the short map; pan once so the marker sits in the strip above it (as the vehicle card does). */
  function panAboveCard(id) {
    var m = markers.get(id);
    if (!m || card.hidden) return;
    var mr = mapEl.getBoundingClientRect(),
      cr = card.getBoundingClientRect(),
      ban = $('#banner');
    var top = 4,
      bottom = cr.top - mr.top - 4,
      tail = 38,
      lo = top + tail,
      hi = bottom - (44 - tail) - 4;
    if (!ban.hidden) lo = Math.max(lo, ban.getBoundingClientRect().bottom - mr.top + 4 + tail);
    if (hi < lo) hi = lo = (lo + hi) / 2;
    var p = map.latLngToContainerPoint(m.getLatLng());
    var cy = p.y < lo || p.y > hi ? (lo + hi) / 2 : p.y;
    var cx = Math.min(Math.max(p.x, 44), mr.width - 44);
    var dx = Math.round(p.x - cx),
      dy = Math.round(p.y - cy);
    if (dx || dy) map.panBy([dx, dy], { animate: animOK() });
  }
  function openCard(id, opts) {
    var s = byId[id];
    if (!s) return;
    /* One card at a time: the vehicle card and the stop card close first. */
    S.map.clearSelection();
    S.stops.closeStop();
    var prev = selected;
    selected = id;
    if (prev && prev !== id) {
      var pm = markers.get(prev);
      if (pm) updateMarker(pm, byId[prev]);
    }
    buildCard();
    card.hidden = false;
    var m = markers.get(id);
    if (m) updateMarker(m, s);
    fillCard();
    live.textContent = labelOf(s) + '. Station details opened.';
    if (opts && opts.focus) $('#indegoHead').focus();
    if (CARD_NARROW.matches) panAboveCard(id);
  }
  function closeCard(opts) {
    if (!selected) return;
    var id = selected,
      had = card.contains(document.activeElement);
    selected = null;
    card.hidden = true;
    card.replaceChildren();
    live.textContent = '';
    var m = markers.get(id);
    if (m) updateMarker(m, byId[id]);
    if (had || (opts && opts.focus)) {
      var e = m && m.getElement();
      if (e) e.focus({ preventScroll: true });
    }
  }
  function directions() {
    var s = byId[selected];
    if (!s || !S.trip || !S.trip.setDestination) return;
    S.trip.setDestination({ lat: s.lat, lng: s.lon, name: s.name.slice(0, 40) });
    closeCard();
    if (S.sheet && S.sheet.setOpen) S.sheet.setOpen(true);
    var from = $('#tripFrom'),
      go = $('#tripGo'),
      target = from.value.trim() ? go : from;
    target.focus();
    target.scrollIntoView({ block: 'nearest' });
  }

  /* ----- Wiring ----- */
  map.on('moveend zoomend resize', function () {
    sync();
  });
  map.on('click', function () {
    closeCard();
  });
  var modes = $('#modes');
  if (modes)
    modes.addEventListener('change', function (e) {
      if (e.target === chipInput) sync();
    });
  document.addEventListener('visibilitychange', syncPolling);
  /* Escape closes the station card and puts focus back on its marker. The vehicle and stop cards never share the screen with it. */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented || !selected) return;
    var a = document.activeElement;
    if (a === document.body || card.contains(a) || mapEl.contains(a)) {
      e.preventDefault();
      closeCard({ focus: true });
    }
  });
  /* Opening a vehicle card or a stop card closes this one. */
  if (window.MutationObserver) {
    var mo = new MutationObserver(function () {
      if (selected && (!$('#detail').hidden || !$('#stopCard').hidden)) closeCard();
    });
    ['#detail', '#stopCard'].forEach(function (sel) {
      var n = $(sel);
      if (n) mo.observe(n, { attributes: true, attributeFilter: ['hidden'] });
    });
  }
  /* A once-a-second check: the chip can also change without a click (Show all modes), dimming and the card's age move with the clock,
     and polling restarts when the rider comes back from an idle pause. No network here. */
  setInterval(function () {
    if (isOn() !== lastOn) sync();
    else syncPolling();
    if (!isOn()) return;
    if (markers.size) applyDim();
    if (selected && !document.hidden) {
      var a = $('#indegoAge');
      if (a) a.textContent = ageText() + (isDim() ? '. May be out of date.' : '');
    }
    renderHint();
  }, 1000);
  sync();
  S.indego.sync = sync;
})();
