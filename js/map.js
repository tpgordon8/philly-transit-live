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
  var M_PER_MI = S.util.M_PER_MI,
    MODE_NAME = S.util.MODE_NAME,
    SEATS = S.util.SEATS,
    cardinal = S.util.cardinal,
    el = S.util.el,
    esc = S.util.esc,
    isStarred = S.util.isStarred,
    lateInfo = S.util.lateInfo,
    starKey = S.util.starKey,
    state = S.util.state;
  /* ----- Map ----- */
  var NOGLIDE_MS = 700; /* markers jump instead of gliding while the map zooms or resizes, and this long after */
  var GLIDE_SOON_MS = 160; /* gliding resumes this long after a zoom ends */
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
    }, NOGLIDE_MS);
  }
  function glideSoon() {
    clearTimeout(glideTimer);
    glideTimer = setTimeout(function () {
      mapEl.classList.remove('noglide');
    }, GLIDE_SOON_MS);
  }
  map.on('zoomstart viewreset resize', noGlide);
  map.on('zoomend', glideSoon);
  var radiusCircle = null,
    centerPin = null,
    homePin = null;
  function drawCenter() {
    var ll = [state.center.lat, state.center.lng],
      m = state.radius * M_PER_MI;
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
  /* Top-down vehicle drawings in a square 40x40 box, all pointing UP (the front is at the top). The box is
   rotated as a whole by CSS (.f-N .f-E .f-S .f-W), so every shape turns cleanly about the marker centre. */
  var SHAPES = {
    bus:
      '<rect class="bd" x="10" y="2" width="20" height="36" rx="5"/>' +
      '<rect class="wn" x="12" y="4.2" width="16" height="3.8" rx="1.4"/>' +
      '<rect class="rf" x="12" y="10" width="16" height="22" rx="2"/><rect class="rf" x="15" y="13" width="10" height="5" rx="1"/><rect class="rf" x="15" y="21" width="10" height="5" rx="1"/>' +
      '<rect class="wn" x="12.6" y="34" width="14.8" height="2" rx=".8"/>' +
      '<rect class="wh" x="8.4" y="8" width="1.8" height="5.5" rx=".8"/><rect class="wh" x="29.8" y="8" width="1.8" height="5.5" rx=".8"/>' +
      '<rect class="wh" x="8.4" y="26.5" width="1.8" height="5.5" rx=".8"/><rect class="wh" x="29.8" y="26.5" width="1.8" height="5.5" rx=".8"/>' +
      '<circle class="hl" cx="13.6" cy="2.9" r="1.2"/><circle class="hl" cx="26.4" cy="2.9" r="1.2"/>',
    trolley:
      '<path class="pole" d="M18 26L14 39M22 26L26 39"/>' +
      '<rect class="bd" x="10" y="2" width="20" height="30" rx="5"/>' +
      '<rect class="wn" x="12" y="4.2" width="16" height="3.8" rx="1.4"/>' +
      '<rect class="rf" x="12" y="10" width="16" height="17" rx="2"/><rect class="rf" x="15" y="12.5" width="10" height="4.5" rx="1"/>' +
      '<rect class="wn" x="12.6" y="29" width="14.8" height="1.8" rx=".8"/>' +
      '<rect class="wh" x="8.4" y="8" width="1.8" height="5" rx=".8"/><rect class="wh" x="29.8" y="8" width="1.8" height="5" rx=".8"/>' +
      '<rect class="wh" x="8.4" y="21" width="1.8" height="5" rx=".8"/><rect class="wh" x="29.8" y="21" width="1.8" height="5" rx=".8"/>' +
      '<circle class="hl" cx="13.6" cy="2.9" r="1.2"/><circle class="hl" cx="26.4" cy="2.9" r="1.2"/>',
    subway:
      '<rect class="bd" x="11" y="1" width="18" height="38" rx="3.5"/>' +
      '<rect class="wn" x="12.6" y="2.8" width="14.8" height="3.4" rx="1"/>' +
      '<rect class="rf" x="13" y="8" width="14" height="24" rx="1.5"/>' +
      '<path class="ln" d="M11 14H29M11 20H29M11 26H29M11 32H29"/>' +
      '<rect class="wn" x="12.6" y="34" width="14.8" height="2.6" rx="1"/>' +
      '<rect class="wh" x="9.4" y="6" width="1.6" height="6" rx=".7"/><rect class="wh" x="29" y="6" width="1.6" height="6" rx=".7"/>' +
      '<rect class="wh" x="9.4" y="28" width="1.6" height="6" rx=".7"/><rect class="wh" x="29" y="28" width="1.6" height="6" rx=".7"/>' +
      '<circle class="hl" cx="14.4" cy="2" r="1.1"/><circle class="hl" cx="25.6" cy="2" r="1.1"/>',
    train:
      '<path class="bd" d="M11.5 41V9Q11.5 -1 20 -1Q28.5 -1 28.5 9V41Z"/>' +
      '<path class="wn" d="M13 9Q13 2.2 20 2.2Q27 2.2 27 9Z"/>' +
      '<rect class="rf" x="13" y="11.5" width="14" height="25" rx="1.5"/>' +
      '<path class="ln" d="M20 11.5V36.5M11.5 18H28.5M11.5 24H28.5M11.5 30H28.5"/>' +
      '<rect class="wn" x="12.6" y="38" width="14.8" height="1.8" rx=".8"/>' +
      '<rect class="wh" x="9.8" y="7" width="1.7" height="6" rx=".7"/><rect class="wh" x="28.5" y="7" width="1.7" height="6" rx=".7"/>' +
      '<rect class="wh" x="9.8" y="29" width="1.7" height="6" rx=".7"/><rect class="wh" x="28.5" y="29" width="1.7" height="6" rx=".7"/>' +
      '<circle class="hl" cx="20" cy="0.8" r="1.2"/>'
  };
  var FACES = ['N', 'E', 'S', 'W']; /* up, right, down, left: 0, 90, 180, 270 degrees */
  function snapFacing(h) {
    return h == null || !isFinite(h) ? 'N' : FACES[Math.round((((h % 360) + 360) % 360) / 90) % 4];
  }
  /* Which way the icon points. A bus or trolley with a route direction faces it (a detour or GPS jitter never turns it).
   Loop, no direction, and trains face the actual heading snapped to N/E/S/W; with no heading either, north. */
  function facingOf(v) {
    return v.dir || snapFacing(v.heading);
  }
  /* The letter in the badge: the route direction, or for trains (no direction in the feed) the heading's 8-point letter. */
  function badgeLetter(v) {
    return v.kind === 'train' ? cardinal(v.heading) || '' : v.dir || '';
  }
  function shapeSVG(kind, face) {
    return (
      '<svg class="vb f-' +
      face +
      '" width="40" height="40" viewBox="0 0 40 40" aria-hidden="true">' +
      (SHAPES[kind] || SHAPES.bus) +
      '</svg>'
    );
  }
  function vehInner(v) {
    var c = badgeLetter(v);
    return (
      shapeSVG(v.kind, facingOf(v)) +
      '<span class="rt' +
      (String(v.badge).length > 3 ? ' long' : '') +
      '">' +
      esc(v.badge) +
      '</span><span class="dr' +
      (c ? '' : ' none') +
      '">' +
      (c || '?') +
      '</span>'
    );
  }
  /* What the marker element shows. Heading jitter that changes neither the badge letter nor the facing leaves it alone. */
  function vehSig(v) {
    return v.kind + '|' + v.badge + '|' + badgeLetter(v) + '|' + facingOf(v);
  }
  var DIR_WORD = { N: 'northbound', E: 'eastbound', S: 'southbound', W: 'westbound' };
  /* Accessible name for a marker, e.g. "Route 57 bus, northbound, 2 min late" (no direction words for a loop or an
   unknown direction; Regional Rail trains have no route direction, so they say "heading NE"). lateInfo() turns 999 into words. */
  function vehLabel(v) {
    var nm =
      v.kind === 'train'
        ? 'Regional Rail train ' + v.badge + (v.route ? ' ' + v.route : '')
        : 'Route ' + v.badge + ' ' + MODE_NAME[v.kind].toLowerCase();
    var c = badgeLetter(v);
    var dirTxt = v.kind === 'train' ? (c ? ' heading ' + c : '') : c ? ', ' + DIR_WORD[c] : '';
    return nm + dirTxt + ', ' + lateInfo(v.late).txt.toLowerCase();
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
            iconSize: [44, 44],
            iconAnchor: [22, 22]
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
        var node = m.getElement();
        if (node && node.dataset.sig !== vehSig(v)) {
          node.className = node.className.replace(/\bk-(bus|trolley|subway|train)\b/g, '') + ' k-' + v.kind;
          node.innerHTML = vehInner(v);
          node.dataset.sig = vehSig(v);
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
  var NARROW = window.matchMedia('(max-width:820px), (max-height:500px)');
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
  /* Card line for the direction. The route's direction is the main fact; the live compass heading is secondary detail,
   shown only when it differs from the route (a detour) or when there is no route direction to state. */
  function directionNode(v) {
    var node = el('span'),
      c = cardinal(v.heading),
      deg = c ? c + ' (' + Math.round(v.heading) + '°)' : '';
    function sub(t) {
      node.appendChild(el('span', 'dsub', t));
    }
    if (v.kind === 'train') {
      node.appendChild(document.createTextNode(c ? 'Heading ' + deg : 'Heading unavailable'));
      sub('Regional Rail reports no route direction, so the badge shows the train’s heading.');
    } else if (v.dir) {
      node.appendChild(document.createTextNode(v.direction));
      if (c && snapFacing(v.heading) !== v.dir) sub('Currently driving ' + deg);
    } else {
      node.appendChild(document.createTextNode(v.direction || 'Direction not reported'));
      sub(c ? 'Currently driving ' + deg : 'Heading unavailable');
    }
    return node;
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
    var dl = el('dl');
    addRow(dl, 'Direction', directionNode(v));
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
  S.map.vehSig = vehSig;
  S.map.vehLabel = vehLabel;
  S.map.vehInner = vehInner;
  S.map.select = select;
  S.map.clearSelection = clearSelection;
  S.map.renderDetail = renderDetail;
  S.map.radiusCircleBounds = function () {
    return radiusCircle.getBounds();
  };
})();
