/* js/map.js: the Leaflet map, vehicle markers, selection and the vehicle detail card. */
(function () {
  'use strict';
  var S = window.SEPTA;
  function closeStop() {
    return S.stops.closeStop.apply(null, arguments);
  }
  function toggleStar() {
    return S.panel.toggleStar.apply(null, arguments);
  }
  function starName() {
    return S.panel.starName.apply(null, arguments);
  }
  function openStop() {
    return S.stops.openStop.apply(null, arguments);
  }
  if (S.halt) return;
  var $ = S.util.$;
  var MODE_NAME = S.util.MODE_NAME,
    SEATS = S.util.SEATS,
    cardinal = S.util.cardinal,
    el = S.util.el,
    esc = S.util.esc,
    isStarred = S.util.isStarred,
    lateInfo = S.util.lateInfo,
    starKey = S.util.starKey,
    state = S.util.state;
  /* ----- Map ----- */
  var map = L.map('map', {
    zoomControl: false,
    markerZoomAnimation: false,
    attributionControl: true
  }).setView([state.center.lat, state.center.lng], 14);
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  map.attributionControl.setPrefix(false);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
  }).addTo(map);
  var mapEl = map.getContainer(),
    glideTimer;
  function noGlide() {
    mapEl.classList.add('noglide');
    clearTimeout(glideTimer);
    glideTimer = setTimeout(function () {
      mapEl.classList.remove('noglide');
    }, 700);
  }
  function glideSoon() {
    clearTimeout(glideTimer);
    glideTimer = setTimeout(function () {
      mapEl.classList.remove('noglide');
    }, 160);
  }
  map.on('zoomstart viewreset resize', noGlide);
  map.on('zoomend', glideSoon);
  var radiusCircle = null,
    centerPin = null,
    homePin = null;
  function drawCenter() {
    var ll = [state.center.lat, state.center.lng],
      m = state.radius * 1609.344;
    if (!radiusCircle) {
      radiusCircle = L.circle(ll, { radius: m, className: 'rad', interactive: false }).addTo(map);
    } else {
      radiusCircle.setLatLng(ll);
      radiusCircle.setRadius(m);
    }
    if (!centerPin) {
      centerPin = L.marker(ll, {
        icon: L.divIcon({
          className: 'pin',
          html: '<span class="me"></span>',
          iconSize: [18, 18],
          iconAnchor: [9, 9]
        }),
        interactive: false,
        keyboard: false,
        zIndexOffset: -500
      }).addTo(map);
    } else centerPin.setLatLng(ll);
  }
  function drawHome() {
    var h = state.places.home;
    if (homePin) {
      homePin.remove();
      homePin = null;
    }
    if (h) {
      homePin = L.marker([h.lat, h.lng], {
        icon: L.divIcon({
          className: 'pin',
          html: '<span class="hm">H</span>',
          iconSize: [26, 26],
          iconAnchor: [13, 13]
        }),
        title: 'Home: ' + h.name,
        keyboard: false,
        zIndexOffset: -400
      }).addTo(map);
    }
  }
  function fitRadius() {
    map.fitBounds(radiusCircle.getBounds(), { padding: [24, 24], animate: true });
  }
  /* ----- Markers ----- */
  var markers = new Map();
  function shapeSVG(kind) {
    if (kind === 'train' || kind === 'subway') {
      return (
        '<svg class="vb" width="64" height="40" viewBox="0 0 64 40" aria-hidden="true">' +
        '<line class="ln" x1="2" y1="37" x2="62" y2="37"/>' +
        '<path class="bd" d="M10 8H44Q56 8 60 22V31H6V12Q6 8 10 8Z"/>' +
        '<rect class="wn" x="10" y="11" width="7" height="5" rx="1"/><rect class="wn" x="20" y="11" width="7" height="5" rx="1"/><rect class="wn" x="30" y="11" width="7" height="5" rx="1"/><rect class="wn" x="40" y="11" width="7" height="5" rx="1"/>' +
        '<circle class="hl" cx="57" cy="25" r="2"/>' +
        '<circle class="wh" cx="15" cy="33" r="3"/><circle class="wh" cx="26" cy="33" r="3"/><circle class="wh" cx="43" cy="33" r="3"/><circle class="wh" cx="54" cy="33" r="3"/></svg>'
      );
    }
    return (
      '<svg class="vb" width="64" height="40" viewBox="0 0 64 40" aria-hidden="true">' +
      (kind === 'trolley' ? '<path class="pole" d="M22 8L40 0"/>' : '') +
      '<rect class="bd" x="8" y="8" width="48" height="24" rx="7"/>' +
      '<rect class="wn" x="12" y="10.5" width="8" height="4" rx="1"/><rect class="wn" x="23" y="10.5" width="8" height="4" rx="1"/><rect class="wn" x="34" y="10.5" width="8" height="4" rx="1"/><rect class="wn" x="45" y="10.5" width="8" height="4" rx="1"/>' +
      '<rect class="hl" x="54" y="24" width="3" height="4" rx="1"/>' +
      '<circle class="wh" cx="19" cy="33" r="3.6"/><circle class="wh" cx="45" cy="33" r="3.6"/></svg>'
    );
  }
  function vehInner(v) {
    var c = cardinal(v.heading);
    return (
      shapeSVG(v.kind) +
      '<span class="rt">' +
      esc(v.badge) +
      '</span><span class="dr' +
      (c ? '' : ' none') +
      '">' +
      (c || '?') +
      '</span>'
    );
  }
  function vehSig(v) {
    return v.kind + '|' + v.badge + '|' + (cardinal(v.heading) || '');
  }
  /* Accessible name for a marker, e.g. "Route 12 bus heading S, 2 min late". lateInfo() already turns 999 into words. */
  function vehLabel(v) {
    var c = cardinal(v.heading);
    var nm =
      v.kind === 'train'
        ? 'Regional Rail train ' + v.badge + (v.route ? ' ' + v.route : '')
        : 'Route ' + v.badge + ' ' + MODE_NAME[v.kind].toLowerCase();
    return nm + (c ? ' heading ' + c : '') + ', ' + lateInfo(v.late).txt.toLowerCase();
  }
  function vehTitle(v) {
    return v.kind === 'train'
      ? 'Train ' + v.badge + ' · ' + v.route
      : 'Route ' + v.badge + ' ' + MODE_NAME[v.kind].toLowerCase();
  }
  function syncMarkers(list) {
    var keep = new Set();
    list.forEach(function (v) {
      keep.add(v.key);
      var m = markers.get(v.key);
      if (!m) {
        m = L.marker([v.lat, v.lng], {
          icon: L.divIcon({
            className: 'veh-wrap k-' + v.kind,
            html: vehInner(v),
            iconSize: [80, 44],
            iconAnchor: [40, 22]
          }),
          title: vehTitle(v),
          keyboard: true,
          riseOnHover: true
        });
        m.on('click', function () {
          select(v.key);
        });
        m.addTo(map);
        markers.set(v.key, m);
        var e0 = m.getElement();
        if (e0) {
          e0.dataset.sig = vehSig(v);
          e0.setAttribute('role', 'button');
          /* Leaflet markers take focus but ignore Enter and Space; selecting is what a click does. */
          e0.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
              e.preventDefault();
              e.stopPropagation();
              select(v.key, { focus: true });
            }
          });
        }
      } else {
        var ll = m.getLatLng();
        /* setLatLng moves the existing element, so the CSS transition glides it. Zoom and pan are untouched. */
        if (ll.lat !== v.lat || ll.lng !== v.lng) m.setLatLng([v.lat, v.lng]);
        var el = m.getElement();
        if (el && el.dataset.sig !== vehSig(v)) {
          el.className = el.className.replace(/\bk-(bus|trolley|subway|train)\b/g, '') + ' k-' + v.kind;
          el.innerHTML = vehInner(v);
          el.dataset.sig = vehSig(v);
        }
      }
      var el2 = m.getElement();
      if (el2) {
        var lbl = vehLabel(v);
        if (el2.getAttribute('aria-label') !== lbl) el2.setAttribute('aria-label', lbl);
        el2.classList.toggle('stale', !!v.stale);
        el2.classList.toggle('sel', state.selected === v.key);
      }
      m.setZIndexOffset(state.selected === v.key ? 1000 : 0);
    });
    markers.forEach(function (m, k) {
      if (!keep.has(k)) {
        m.remove();
        markers.delete(k);
      }
    });
  }
  function clearSelection() {
    state.selected = null;
    markers.forEach(function (m) {
      var e = m.getElement();
      if (e) e.classList.remove('sel');
    });
    var lv = $('#detailLive');
    if (lv && lv.textContent) lv.textContent = '';
    renderDetail();
  }
  /* ----- Detail card ----- */
  function findVehicle(k) {
    var l = state.src.bus.list.concat(state.src.train.list);
    for (var i = 0; i < l.length; i++) if (l[i].key === k) return l[i];
    return null;
  }
  var NARROW = window.matchMedia('(max-width:820px)');
  function select(k, opts) {
    state.selected = k;
    markers.forEach(function (m, key) {
      var e = m.getElement();
      if (e) e.classList.toggle('sel', key === k);
      m.setZIndexOffset(key === k ? 1000 : 0);
    });
    renderDetail();
    var v = findVehicle(k);
    /* The card is not a live region (it is rebuilt on every refresh). Opening it is announced once, here. */
    if (v) $('#detailLive').textContent = vehLabel(v) + '. Vehicle details opened.';
    if (opts && opts.focus) {
      var h = $('#detailHead');
      if (h) h.focus();
    }
    if (NARROW.matches) panAboveCard(k);
  }
  /* On a phone the vehicle card covers most of the short map. Pan (once, on selection only) so the selected marker
   sits in the strip between the top of the map (or the banner) and the top of the card. Zoom is untouched. */
  function panAboveCard(k) {
    var m = markers.get(k),
      card = $('#detail');
    if (!m || card.hidden) return;
    var mr = mapEl.getBoundingClientRect(),
      cr = card.getBoundingClientRect(),
      ban = $('#banner');
    var top = 4,
      bottom = cr.top - mr.top - 4,
      half = 22;
    if (!ban.hidden) top = Math.max(top, ban.getBoundingClientRect().bottom - mr.top + 4);
    var lo = top + half,
      hi = bottom - half;
    if (hi < lo) hi = lo = (top + bottom) / 2; /* strip smaller than a marker: centre it in what is left */
    var p = map.latLngToContainerPoint(m.getLatLng());
    var cy = p.y < lo || p.y > hi ? (lo + hi) / 2 : p.y;
    var cx = Math.min(Math.max(p.x, 44), mr.width - 44);
    var dx = Math.round(p.x - cx),
      dy = Math.round(p.y - cy);
    if (dx || dy)
      map.panBy([dx, dy], { animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches });
  }
  function addRow(dl, label, node) {
    var dt = el('dt', null, label),
      dd = el('dd');
    if (typeof node === 'string') dd.textContent = node;
    else dd.appendChild(node);
    dl.appendChild(dt);
    dl.appendChild(dd);
  }
  /* The card is rebuilt on every refresh; keep keyboard focus on the same control (matched by id) across the rebuild. */
  function renderDetail() {
    var box = $('#detail'),
      ae = document.activeElement,
      fid = ae && ae !== document.body && box.contains(ae) ? ae.id : '';
    buildDetail();
    if (fid) {
      var n = box.querySelector('#' + fid);
      if (n && n !== document.activeElement) n.focus({ preventScroll: true });
    }
  }
  function buildDetail() {
    var box = $('#detail');
    if (!state.selected) {
      box.hidden = true;
      return;
    }
    var v = findVehicle(state.selected);
    box.hidden = false;
    box.replaceChildren();
    var head = el('div', 'dh');
    var close = el('button', 'btn small ghost', 'Close');
    close.type = 'button';
    close.id = 'detailClose';
    close.setAttribute('aria-label', 'Close vehicle details');
    close.addEventListener('click', closeDetailFocus);
    if (!v) {
      var t0 = el('div', 'dt'),
        h0 = el('b', null, 'Vehicle not reporting');
      h0.id = 'detailHead';
      h0.tabIndex = -1;
      t0.appendChild(h0);
      t0.appendChild(el('span', null, 'It has no recent GPS report.'));
      head.appendChild(t0);
      head.appendChild(close);
      box.appendChild(head);
      box.appendChild(
        el('div', 'gone', 'This vehicle stopped sending a live position, so it was removed from the map.')
      );
      return;
    }
    var badge = el('span', 'rbadge k-' + v.kind, v.badge);
    var dt = el('div', 'dt');
    var hd = el('b', null, v.kind === 'train' ? v.route || 'Regional Rail' : 'Route ' + v.route);
    hd.id = 'detailHead';
    hd.tabIndex = -1;
    dt.appendChild(hd);
    dt.appendChild(
      el(
        'span',
        null,
        v.kind === 'train'
          ? 'Regional Rail · Train ' + v.badge
          : MODE_NAME[v.kind] + (v.vid ? ' · Vehicle ' + v.vid : '')
      )
    );
    var sk = starKey(v),
      starred = isStarred(sk),
      rn = starName(sk);
    var star = el('button', 'btn small', starred ? 'Starred' : 'Star route');
    star.type = 'button';
    star.id = 'starBtn';
    star.setAttribute('aria-pressed', starred ? 'true' : 'false');
    star.setAttribute('aria-label', (starred ? 'Unstar route ' : 'Star route ') + rn);
    star.addEventListener('click', function () {
      toggleStar(sk);
      var b = $('#starBtn');
      if (b) b.focus();
    });
    head.appendChild(badge);
    head.appendChild(dt);
    head.appendChild(star);
    head.appendChild(close);
    box.appendChild(head);
    var dl = el('dl'),
      c = cardinal(v.heading);
    var dirTxt =
      (v.direction ? v.direction : 'Direction not reported') +
      (c ? ' · heading ' + c + ' (' + Math.round(v.heading) + '°)' : ' · heading unavailable');
    addRow(dl, 'Direction', dirTxt);
    addRow(dl, 'Destination', v.dest || 'Not reported');
    if (v.kind === 'train' && v.cur) addRow(dl, 'Last station', v.cur);
    var nextNode = v.next || 'Not reported';
    if ((v.kind === 'bus' || v.kind === 'trolley') && v.nextId && /^[0-9]{1,8}$/.test(v.nextId)) {
      nextNode = el('span');
      nextNode.appendChild(document.createTextNode((v.next || 'Not reported') + ' '));
      var vs = el('button', 'btn small', 'View stop');
      vs.type = 'button';
      vs.id = 'viewStop';
      vs.addEventListener('click', function () {
        /* On a phone the stop card is hidden while the vehicle card is open, so close the vehicle card to show it. */
        if (NARROW.matches) clearSelection();
        openStop(v.route, v.nextId, { focus: true, opener: vs });
      });
      nextNode.appendChild(vs);
    }
    addRow(dl, 'Next stop', nextNode);
    var li = lateInfo(v.late),
      pill = el('span', 'pill ' + li.cls, li.txt);
    addRow(dl, 'Schedule', pill);
    if (v.kind === 'train') {
      if (v.service) addRow(dl, 'Service', v.service.charAt(0) + v.service.slice(1).toLowerCase());
      if (v.track) addRow(dl, 'Track', v.track);
    } else if (v.seats) {
      addRow(dl, 'Crowding', SEATS[v.seats] || v.seats.replace(/_/g, ' ').toLowerCase());
    }
    if (v.kind !== 'train') {
      var live = state.src.bus.stale
        ? 'Last report is stale'
        : 'GPS fix about ' +
          Math.max(0, Math.round(v.age + (Date.now() - state.src.bus.ok) / 1000)) +
          ' s old';
      addRow(dl, 'Position', live);
    } else {
      addRow(dl, 'Position', 'Live from SEPTA TrainView (no timestamp provided)');
    }
    box.appendChild(dl);
  }
  /* Closing from the keyboard returns focus to the marker, so it does not fall back to the top of the page. */
  function closeDetailFocus() {
    var k = state.selected,
      had = $('#detail').contains(document.activeElement);
    clearSelection();
    if (had) {
      var m = markers.get(k),
        e = m && m.getElement();
      if (e) e.focus({ preventScroll: true });
    }
  }
  map.on('click', function () {
    if (state.selected) clearSelection();
  });
  /* One Escape closes one thing: the stop card when focus is in it, else the vehicle card, else (focus on the page or map) the stop card. */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    var a = document.activeElement;
    if (state.stop && $('#stopCard').contains(a)) {
      closeStop();
      return;
    }
    if (state.selected) {
      closeDetailFocus();
      return;
    }
    if (state.stop && (a === document.body || mapEl.contains(a))) closeStop();
  });
  S.map.map = map;
  S.map.mapEl = mapEl;
  S.map.NARROW = NARROW;
  S.map.drawCenter = drawCenter;
  S.map.drawHome = drawHome;
  S.map.fitRadius = fitRadius;
  S.map.syncMarkers = syncMarkers;
  S.map.markers = markers;
  S.map.select = select;
  S.map.clearSelection = clearSelection;
  S.map.renderDetail = renderDetail;
  S.map.radiusCircleBounds = function () {
    return radiusCircle.getBounds();
  };
})();
