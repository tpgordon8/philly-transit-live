/* js/trip.js: trip planner interface: form, results list and map drawing. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var $ = S.util.$,
    el = S.util.el,
    fmtMi = S.util.fmtMi,
    isNum = S.util.isNum,
    state = S.util.state,
    M_PER_MI = S.util.M_PER_MI;
  var NARROW = S.map.NARROW,
    geocode = S.panel.geocode,
    getPosition = S.panel.getPosition,
    map = S.map.map,
    mapEl = S.map.mapEl;
  var cancelPlan = S.routing.cancelPlan,
    clockText = S.planner.clockText,
    inRegion = S.routing.inRegion,
    planTrips = S.planner.planTrips;
  /* ----- Trip planner UI (ARCHITECTURE.md section 12) -----
   Everything lives in memory: no localStorage key, nothing is written to prefs, and nothing here touches the 15 s refresh or the
   vehicle markers. Routing and Indego requests are made by planTrips (js/planner.js, through the Worker); this file only calls it,
   and hands it a cancel handle (trip.ctx) that Clear trip and a new plan use to abandon the old plan's requests. The map drawing
   is one Leaflet layer group, separate from `markers`. */
  var tripLayer = L.layerGroup().addTo(map);
  var OUT_MSG = 'That place is outside the area this planner covers (Philadelphia region).';
  var trip = { seq: 0, ctx: null, busy: false, res: null, sel: 0, last: null, autoShown: false, view: null };
  var PHONE = window.matchMedia('(max-width:480px)');
  var fieldPt = {
    from: null,
    to: null
  }; /* {kind:'center'} | {pt:{lat,lng,name}}; cleared when the user edits the text */
  var TRIP_REDUCED = function () {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  };
  function tripFieldEl(w) {
    return $(w === 'from' ? '#tripFrom' : '#tripTo');
  }
  function tripErr(w, msg) {
    var p = $(w === 'from' ? '#tripFromErr' : '#tripToErr'),
      inp = tripFieldEl(w);
    p.textContent = msg || '';
    p.hidden = !msg;
    if (msg) {
      inp.setAttribute('aria-describedby', p.id);
      inp.setAttribute('aria-invalid', 'true');
    } else {
      inp.removeAttribute('aria-describedby');
      inp.removeAttribute('aria-invalid');
    }
  }
  function tripSetField(w, text, fp) {
    tripFieldEl(w).value = text;
    fieldPt[w] = fp || null;
    tripErr(w, '');
  }
  ['from', 'to'].forEach(function (w) {
    tripFieldEl(w).addEventListener('input', function () {
      fieldPt[w] = null;
      tripErr(w, '');
    });
  });
  function tripRenderPlaces() {
    var h = state.places.home,
      chips = $('#tripChips');
    $('#tripFromHome').hidden = !h;
    $('#tripToHome').hidden = !h;
    chips.replaceChildren();
    var all = [];
    if (h) all.push({ label: 'Home', p: h, title: 'Home: ' + h.name });
    state.places.list.forEach(function (p) {
      all.push({ label: p.name, p: p, title: p.name });
    });
    all.slice(0, 6).forEach(function (x) {
      var b = el('button', 'btn small', x.label);
      b.type = 'button';
      b.title = x.title;
      b.addEventListener('click', function () {
        tripSetField('to', x.p.name, { pt: { lat: x.p.lat, lng: x.p.lng, name: x.p.name } });
      });
      chips.appendChild(b);
    });
    chips.hidden = !all.length;
  }
  $('#tripFromHome').addEventListener('click', function () {
    var h = state.places.home;
    if (h) tripSetField('from', h.name, { pt: { lat: h.lat, lng: h.lng, name: h.name } });
  });
  $('#tripToHome').addEventListener('click', function () {
    var h = state.places.home;
    if (h) tripSetField('to', h.name, { pt: { lat: h.lat, lng: h.lng, name: h.name } });
  });
  $('#tripSwap').addEventListener('click', function () {
    var a = $('#tripFrom').value,
      b = $('#tripTo').value,
      fa = fieldPt.from,
      fb = fieldPt.to;
    tripSetField('from', b, fb);
    tripSetField('to', a, fa);
  });
  $('#tripLocate').addEventListener('click', function () {
    var btn = $('#tripLocate');
    btn.disabled = true;
    tripErr('from', '');
    getPosition()
      .then(function (p) {
        tripSetField('from', 'Your location', {
          pt: { lat: p.coords.latitude, lng: p.coords.longitude, name: 'Your location' }
        });
      })
      .catch(function () {
        tripErr('from', "Location isn't available here. Type an address instead.");
      })
      .finally(function () {
        btn.disabled = false;
      });
  });
  /* Resolves {pt} or {err}. Typed text is geocoded like the search box (plus ", Philadelphia, PA" when it has no comma). */
  function tripResolve(w, text) {
    var fp = fieldPt[w];
    /* Every point is checked against the region the Worker serves before any routing call is made. */
    function chk(pt) {
      return inRegion(pt) ? { pt: pt } : { err: OUT_MSG };
    }
    if (fp && fp.kind === 'center')
      return Promise.resolve(chk({ lat: state.center.lat, lng: state.center.lng, name: 'Map center' }));
    if (fp && fp.pt) return Promise.resolve(chk(fp.pt));
    if (!text) {
      if (w === 'from') {
        tripSetField('from', 'Map center', { kind: 'center' });
        return Promise.resolve(chk({ lat: state.center.lat, lng: state.center.lng, name: 'Map center' }));
      }
      return Promise.resolve({ err: 'Enter a destination.' });
    }
    return geocode(text, { philly: true }).then(
      function (r) {
        if (!r || !isNum(r.lat) || !isNum(r.lng)) return { err: "Couldn't find that address." };
        return chk({ lat: r.lat, lng: r.lng, name: text.slice(0, 40) });
      },
      function () {
        return { err: 'Address lookup failed. Check your connection and try again.' };
      }
    );
  }
  function tripBusy(on) {
    trip.busy = on;
    $('#tripGo').disabled = on;
    $('#tripResults').setAttribute('aria-busy', on ? 'true' : 'false');
    ['#replan', '#tripRetry'].forEach(function (id) {
      var b = $(id);
      if (b) b.disabled = on;
    });
  }
  $('#tripForm').addEventListener('submit', function (e) {
    e.preventDefault();
    if (trip.busy) return;
    startTrip(null);
  });
  /* fixed: {o,d} to repeat a plan with the same points (Re-plan, Retry); null reads the form. */
  function startTrip(fixed) {
    var seq = ++trip.seq,
      box = $('#tripResults');
    /* A new plan abandons the previous one: its queued routing calls are dropped and its requests aborted, so it cannot hold up this one. */
    if (trip.ctx) cancelPlan(trip.ctx);
    var ctx = (trip.ctx = { dead: false, calls: 0 });
    tripErr('from', '');
    tripErr('to', '');
    trip.res = null;
    trip.fit = null;
    tripLayer.clearLayers();
    tripBusy(true);
    box.hidden = false;
    box.replaceChildren(el('p', 'tp-mute', 'Planning...'));
    $('#tripLive').textContent = 'Planning your trip';
    /* Clearing while a plan is in flight cancels it: the sequence number moves on and the late answer is ignored. */
    var cb = el('button', 'btn', 'Clear trip');
    cb.type = 'button';
    cb.id = 'tripClear';
    cb.addEventListener('click', tripClear);
    box.appendChild(cb);
    box.setAttribute('aria-busy', 'true');
    /* From, then To: Nominatim allows about one lookup per second (geocode itself spaces them), so they are never sent together. */
    var pts = fixed
      ? Promise.resolve(fixed)
      : tripResolve('from', $('#tripFrom').value.trim()).then(function (a) {
          if (seq !== trip.seq) return null;
          return tripResolve('to', $('#tripTo').value.trim()).then(function (b) {
            if (seq !== trip.seq) return null;
            if (a.err || b.err) {
              if (a.err) tripErr('from', a.err);
              if (b.err) tripErr('to', b.err);
              $('#tripLive').textContent = '';
              tripFieldEl(a.err ? 'from' : 'to').focus();
              return null;
            }
            return { o: a.pt, d: b.pt };
          });
        });
    pts.then(function (p) {
      if (seq !== trip.seq) return;
      if (!p) {
        tripBusy(false);
        box.replaceChildren();
        box.hidden = true;
        box.setAttribute('aria-busy', 'false');
        return;
      }
      trip.last = p;
      return planTrips(p.o, p.d, { ctx: ctx }).then(
        function (res) {
          if (seq !== trip.seq) return;
          tripBusy(false);
          if (!res.options.length) {
            tripFail('No trip found. Try different points.', false, 'tripNone');
            return;
          }
          trip.res = res;
          var first = 0;
          for (var i = 0; i < res.options.length; i++)
            if (res.options[i].structure !== 'car') {
              first = i;
              break;
            }
          trip.sel = first;
          trip.at = Date.now();
          tripRender();
          tripDraw();
        },
        function (err) {
          if (seq !== trip.seq) return;
          tripBusy(false);
          if (err && err.code === 'out_of_area') tripFail(OUT_MSG, false, 'tripOut');
          else if (err && err.code === 'routing_unavailable')
            tripFail("Couldn't reach the routing service. Try again.", true);
          else tripFail("Couldn't plan that trip. Try again.", true);
        }
      );
    });
  }
  /* The map centre and zoom from before the plan was drawn; Clear trip and the failure states put the map back there. */
  function tripRestoreView() {
    var v = trip.view;
    trip.view = null;
    trip.fit = null;
    if (v) map.setView(v.center, v.zoom, { animate: !TRIP_REDUCED() });
  }
  function tripFail(msg, retry, id) {
    var box = $('#tripResults');
    box.hidden = false;
    box.setAttribute('aria-busy', 'false');
    box.replaceChildren();
    trip.res = null;
    tripLayer.clearLayers();
    tripRestoreView();
    var m = el('p', 'tp-msg', msg);
    m.setAttribute('role', 'alert');
    m.tabIndex = -1;
    if (id) m.id = id;
    box.appendChild(m);
    if (retry) {
      var b = el('button', 'btn', 'Retry');
      b.type = 'button';
      b.id = 'tripRetry';
      b.style.marginTop = '8px';
      b.addEventListener('click', function () {
        if (!trip.busy && trip.last) startTrip(trip.last);
      });
      box.appendChild(b);
    }
    $('#tripLive').textContent = '';
    m.focus(); /* planning is over: focus goes to the message, with the Retry control right after it */
  }
  function tripClear() {
    trip.seq++;
    trip.res = null;
    trip.last = null;
    if (trip.ctx) cancelPlan(trip.ctx);
    tripBusy(false);
    tripLayer.clearLayers();
    tripRestoreView();
    var box = $('#tripResults');
    box.replaceChildren();
    box.hidden = true;
    box.setAttribute('aria-busy', 'false');
    $('#tripLive').textContent = '';
    $('#tripGo').focus();
  }
  /* ----- Rendering ----- */
  function tripModeWord(o) {
    var m = {};
    o.legs.forEach(function (l) {
      m[l.mode] = 1;
    });
    if (m.bus) return m.bike ? 'bike and bus' : 'bus';
    return m.bike ? 'bike' : 'walk';
  }
  function tripLegWord(l) {
    if (l.mode === 'bus') return (l.kind === 'trolley' ? 'Trolley ' : 'Bus ') + l.route;
    return (l.mode === 'car' ? 'Drive' : l.mode === 'bike' ? 'Bike' : 'Walk') + ' ' + l.minutes;
  }
  function tripFastest(res) {
    var best = null,
      bi = -1;
    res.options.forEach(function (o, i) {
      var v = o.raw != null ? o.raw : o.minutes;
      if (o.structure !== 'car' && !o.dominated && (best == null || v < best)) {
        best = v;
        bi = i;
      }
    });
    return bi;
  }
  function tripAgo(ms) {
    var n = Math.max(0, Math.round((Date.now() - ms) / 60000));
    return n >= 120 ? Math.round(n / 60) + ' h ago' : n < 1 ? 'under 1 min ago' : n + ' min ago';
  }
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function tripDateText(ymd) {
    var m = /^(\d{4})(\d{2})(\d{2})$/.exec(String(ymd));
    return m ? MONTHS[+m[2] - 1] + ' ' + +m[3] + ', ' + m[1] : String(ymd || '');
  }
  /* One plain sentence per note code; availability notes (indego, car, bike, feeds) arrive with their own text. */
  function tripNoteText(n) {
    var rs = (n.routes || []).join(', ');
    switch (n.code) {
      case 'routing_limit':
        return "To stay within the free routing service's limits, the planner checked only the most promising bus options, so a slower-looking bus trip may be missing.";
      case 'routing_failed':
        return (
          (n.count === 1 ? 'Directions for one bus option' : 'Directions for ' + n.count + ' bus options') +
          ' could not be loaded, so ' +
          (n.count === 1 ? 'it was' : 'they were') +
          ' left out. Re-plan to try again.'
        );
      case 'no_live_bus':
        return (
          'No bus is being tracked right now on ' +
          (rs ? 'route' + (n.routes.length === 1 ? ' ' : 's ') + rs : 'the routes that serve this trip') +
          ', so there is no live wait to show for them.'
        );
      case 'no_bus_beats_baseline':
        return (
          'Buses run between these points, but none is faster than ' +
          (n.baseline || 'walking') +
          ' the whole way.'
        );
      case 'schedule_stale':
        return n.state === 'expired'
          ? 'The bus schedule data ended on ' +
              tripDateText(n.end) +
              ', so bus ride times may be out of date.'
          : 'The bus schedule data ends on ' +
              tripDateText(n.end) +
              ' (' +
              (n.days === 0 ? 'today' : n.days === 1 ? 'tomorrow' : 'in ' + n.days + ' days') +
              '); bus ride times may soon be out of date.';
      default:
        return n.text || '';
    }
  }
  function tripStep(l, asOf) {
    var li = el('li'),
      mi = fmtMi(l.meters / M_PER_MI),
      a = l.from.name || 'start',
      b = l.to.name || 'end';
    function sub(t) {
      li.appendChild(el('span', 'tp-sub', t));
    }
    if (l.mode === 'bus') {
      var wait = Math.round(l.waitMin),
        ws = wait < 1 ? 'under 1 min' : 'about ' + wait + ' min';
      li.appendChild(
        document.createTextNode(
          (l.kind === 'trolley' ? 'Trolley ' : 'Bus ') +
            l.route +
            (l.head ? ' toward ' + l.head : '') +
            ', ' +
            l.stops +
            ' stop' +
            (l.stops === 1 ? '' : 's') +
            ', ' +
            l.minutes +
            ' min, from ' +
            a +
            ' to ' +
            b
        )
      );
      sub(
        l.waitBasis === 'live'
          ? 'Wait: next bus tracked live, ' + ws + '.'
          : 'Wait: waits ' + ws + ' on average (schedule frequency, no bus tracked).'
      );
      sub('Ride: ' + Math.round(l.rideMin) + ' min, ' + (l.rideBasis || 'scheduled') + '.');
      return li;
    }
    li.appendChild(
      document.createTextNode(
        (l.mode === 'car' ? 'Drive' : l.mode === 'bike' ? 'Bike' : 'Walk') +
          ' ' +
          l.minutes +
          ' min, ' +
          mi +
          ' from ' +
          a +
          ' to ' +
          b
      )
    );
    (l.notes || []).forEach(sub);
    var st = l.mode === 'bike' && l.stations;
    if (st) {
      var ts = [st.from.asOf, st.to.asOf].filter(Boolean),
        at = ts.length ? Math.min.apply(null, ts) : asOf,
        pl = function (n, w) {
          return n + ' ' + w + (n === 1 ? '' : 's');
        };
      sub(
        'Indego counts as of ' +
          (at ? tripAgo(at) : 'an unknown time') +
          ': ' +
          pl(st.from.bikes, 'bike') +
          ' (' +
          st.from.ebikes +
          ' electric) at ' +
          st.from.name +
          ', ' +
          pl(st.to.docks, 'free dock') +
          ' at ' +
          st.to.name +
          '.'
      );
    }
    return li;
  }
  function tripRender() {
    var box = $('#tripResults'),
      res = trip.res,
      fast = tripFastest(res);
    box.hidden = false;
    box.setAttribute('aria-busy', 'false');
    box.replaceChildren();
    var h = el('h3', null, 'Trip options');
    h.id = 'tripHeading';
    h.tabIndex = -1;
    box.appendChild(h);
    if (res.bestMinutes != null && fast >= 0) {
      var fo = res.options[fast];
      box.appendChild(
        el('p', 'tp-top', 'Fastest without a car: ' + tripModeWord(fo) + ', ' + fo.minutes + ' min')
      );
    }
    res.notes.forEach(function (n) {
      box.appendChild(
        el('p', n.code === 'schedule_stale' ? 'tp-warn' : 'tp-mute', tripNoteText(n))
      ).dataset.code = n.code;
    });
    var acts = el('div', 'tp-acts'),
      rp = el('button', 'btn', 'Re-plan');
    rp.type = 'button';
    rp.id = 'replan';
    rp.addEventListener('click', function () {
      if (!trip.busy && trip.last) startTrip(trip.last);
    });
    var sm = el('button', 'btn', 'Show on map');
    sm.type = 'button';
    sm.id = 'showMap';
    sm.addEventListener('click', tripShowMap);
    var cl = el('button', 'btn', 'Clear trip');
    cl.type = 'button';
    cl.id = 'tripClear';
    cl.addEventListener('click', tripClear);
    acts.appendChild(rp);
    acts.appendChild(sm);
    acts.appendChild(cl);
    box.appendChild(acts);
    box.appendChild(
      el(
        'p',
        'tp-mute',
        'Planned at ' +
          clockText(trip.at) +
          '. Bike counts and bus waits change quickly; re-plan before you leave.'
      )
    );
    var list = el('div', 'tp-list');
    list.id = 'tripList';
    list.setAttribute('role', 'group');
    list.setAttribute('aria-label', 'Trip options');
    var more = el('div', 'tp-list');
    more.id = 'tripMoreList';
    more.hidden = true;
    var asOf = res.asOf && res.asOf.indego,
      nMore = 0;
    res.options.forEach(function (o, i) {
      var wrap = el('div', 'tp-opt'),
        b = el('button', 'tp-card');
      b.type = 'button';
      b.dataset.i = i;
      b.setAttribute('aria-pressed', i === trip.sel ? 'true' : 'false');
      var l1 = el('span', 'tp-l1');
      l1.appendChild(el('span', 'tp-min', o.minutes + ' min'));
      if (i === fast) l1.appendChild(el('span', 'tp-badge', 'Fastest'));
      if (o.structure === 'car') l1.appendChild(el('span', 'tp-badge drive', 'Drive'));
      b.appendChild(l1);
      b.appendChild(el('span', 'tp-l2', o.legs.map(tripLegWord).join(' · ')));
      if (o.structure === 'car') b.appendChild(el('span', 'tp-l3', 'no traffic or parking data'));
      if (o.dominated && o.dominatedReason) b.appendChild(el('span', 'tp-l3', o.dominatedReason));
      var ol = el('ol', 'tp-steps');
      ol.id = 'tripSteps' + i;
      ol.hidden = i !== trip.sel;
      o.legs.forEach(function (l) {
        ol.appendChild(tripStep(l, asOf));
      });
      var legSum = 0;
      o.legs.forEach(function (l) {
        legSum += l.minutes;
      });
      if (legSum !== o.minutes)
        ol.appendChild(
          el(
            'li',
            'tp-sub tp-round',
            'The steps are rounded one by one and add up to ' +
              legSum +
              ' min; the trip total of ' +
              o.minutes +
              ' min is rounded once from the exact times.'
          )
        );
      b.setAttribute('aria-controls', ol.id);
      b.addEventListener('click', function () {
        tripSelect(i);
      });
      wrap.appendChild(b);
      wrap.appendChild(ol);
      if (o.dominated) {
        more.appendChild(wrap);
        nMore++;
      } else list.appendChild(wrap);
    });
    box.appendChild(list);
    if (res.hiddenCount > 0 && nMore) {
      var mb = el('button', 'btn tp-more', 'More options (' + res.hiddenCount + ' slower)');
      mb.type = 'button';
      mb.id = 'tripMore';
      mb.setAttribute('aria-expanded', 'false');
      mb.setAttribute('aria-controls', 'tripMoreList');
      mb.addEventListener('click', function () {
        var open = mb.getAttribute('aria-expanded') !== 'true';
        mb.setAttribute('aria-expanded', open ? 'true' : 'false');
        more.hidden = !open;
      });
      box.appendChild(mb);
      box.appendChild(more);
    }
    var feed = res.asOf && res.asOf.network && res.asOf.network.feed;
    if (feed && feed.start)
      box.appendChild(el('p', 'tp-mute', 'Bus schedule data as of ' + tripDateText(feed.start))).id =
        'tripSched';
    h.focus();
    var n = res.options.length;
    $('#tripLive').textContent =
      n +
      ' trip option' +
      (n === 1 ? '' : 's') +
      (res.bestMinutes != null ? ', fastest ' + res.bestMinutes + ' minutes' : '');
    if (NARROW.matches && !trip.autoShown) {
      trip.autoShown = true;
      tripShowMap();
    }
  }
  function tripSelect(i) {
    if (!trip.res || i === trip.sel) return;
    trip.sel = i;
    document.querySelectorAll('#tripResults .tp-card').forEach(function (b) {
      var on = Number(b.dataset.i) === i;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      $('#' + b.getAttribute('aria-controls')).hidden = !on;
    });
    tripDraw();
  }
  /* Brings the plan back into view: on a phone the map is scrolled to the top of the screen, and the map returns to the
   selected option however far it was panned. */
  function tripShowMap() {
    try {
      mapEl.scrollIntoView({
        block: PHONE.matches ? 'start' : 'nearest',
        behavior: TRIP_REDUCED() ? 'auto' : 'smooth'
      });
    } catch (e) {
      /* scrollIntoView options are not supported everywhere; skipping the scroll is fine */
    }
    tripFit();
  }
  /* ----- Map drawing ----- */
  function tripMarker(ll, cls, title, sub) {
    var box = el('div', 'tp-mk ' + cls),
      t = el('span', 'tp-txt');
    t.appendChild(el('span', 'tp-nm', title));
    if (sub) t.appendChild(el('span', 'tp-ct', sub));
    box.appendChild(t);
    box.appendChild(el('span', 'tp-dot'));
    return L.marker(ll, {
      icon: L.divIcon({ className: 'tp-pin', html: box, iconSize: [0, 0], iconAnchor: [0, 0] }),
      interactive: false,
      keyboard: false,
      zIndexOffset: 400
    }).addTo(tripLayer);
  }
  function tripDraw() {
    tripLayer.clearLayers();
    var o = trip.res && trip.res.options[trip.sel];
    if (!o) return;
    var all = [];
    o.legs.forEach(function (l) {
      if (l.path && l.path.length > 1) {
        L.polyline(l.path, { className: 'tp-line tp-' + l.mode, interactive: false }).addTo(tripLayer);
        l.path.forEach(function (p) {
          all.push(p);
        });
      }
    });
    var first = o.legs[0],
      last = o.legs[o.legs.length - 1];
    tripMarker([first.from.lat, first.from.lng], 'tp-start tp-below', 'Start');
    tripMarker([last.to.lat, last.to.lng], 'tp-end tp-below', 'End');
    o.legs.forEach(function (l) {
      if (l.mode === 'bike') {
        var st = l.stations;
        tripMarker(
          [l.from.lat, l.from.lng],
          'tp-stn',
          l.from.name || 'Indego',
          st ? st.from.bikes + ' bike' + (st.from.bikes === 1 ? '' : 's') : ''
        );
        tripMarker(
          [l.to.lat, l.to.lng],
          'tp-stn',
          l.to.name || 'Indego',
          st ? st.to.docks + ' dock' + (st.to.docks === 1 ? '' : 's') : ''
        );
      } else if (l.mode === 'bus') {
        tripMarker([l.from.lat, l.from.lng], 'tp-stop', 'Board ' + l.route, '');
        tripMarker([l.to.lat, l.to.lng], 'tp-stop', 'Exit ' + l.route, '');
      }
    });
    trip.fit = all.length ? L.latLngBounds(all) : null;
    if (trip.fit) {
      if (!trip.view) trip.view = { center: map.getCenter(), zoom: map.getZoom() };
      tripFit();
    }
  }
  function tripFit() {
    if (trip.fit)
      map.fitBounds(trip.fit, {
        paddingTopLeft: [34, 58],
        paddingBottomRight: [34, 44],
        animate: !TRIP_REDUCED()
      });
  }
  S.trip.tripRenderPlaces = tripRenderPlaces;
})();
