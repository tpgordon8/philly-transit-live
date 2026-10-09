/* js/util.js: constants, formatting and geometry helpers, DOM shortcuts, localStorage store, saved preferences, places, starred routes and the shared state object. */
(function () {
  'use strict';
  var S = window.SEPTA;
  /* ---------- Pure logic (no DOM) ---------- */
  var REFRESH_MS = 15000,
    GHOST_MAX_S = 150,
    DROP_AFTER_MS = 120000;
  var M_PER_MI = 1609.344; /* metres in a statute mile */
  /* The radius slider's range (index.html) and what the empty-state "Widen" button adds. */
  var MIN_RADIUS_MI = 0.25;
  var MAX_RADIUS_MI = 5;
  var WIDEN_STEP_MI = 1.5;
  function widenedRadius(r) {
    return Math.min(MAX_RADIUS_MI, r + WIDEN_STEP_MI);
  }
  var MAX_PLACES = 50; /* saved places kept */
  var MAX_STAR_KEY_LEN = 64; /* longest starred-route key kept */
  var TROLLEY = new Set([
    '10',
    '101',
    '102',
    '11',
    '13',
    '15',
    '34',
    '36',
    'T1',
    'T2',
    'T3',
    'T4',
    'T5',
    'G1',
    'D1',
    'D2'
  ]);
  var SUBWAY = new Set(['B1', 'B2', 'B3', 'L1', 'M1']);
  function kindOf(route) {
    return SUBWAY.has(route) ? 'subway' : TROLLEY.has(route) ? 'trolley' : 'bus';
  }
  var CARD = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  var CARD_LONG = {
    N: 'north',
    NE: 'northeast',
    E: 'east',
    SE: 'southeast',
    S: 'south',
    SW: 'southwest',
    W: 'west',
    NW: 'northwest'
  };
  var SEATS = {
    EMPTY: 'Plenty of room',
    MANY_SEATS_AVAILABLE: 'Many seats open',
    FEW_SEATS_AVAILABLE: 'Few seats open',
    STANDING_ROOM_ONLY: 'Standing room only',
    CRUSHED_STANDING_ROOM_ONLY: 'Very crowded',
    FULL: 'Full',
    NOT_ACCEPTING_PASSENGERS: 'Not accepting passengers'
  };
  var MODE_NAME = { bus: 'Bus', trolley: 'Trolley', subway: 'Subway', train: 'Regional Rail' };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function cardinal(h) {
    return h == null || !isFinite(h) ? null : CARD[Math.round((((h % 360) + 360) % 360) / 45) % 8];
  }
  function toRad(d) {
    return (d * Math.PI) / 180;
  }
  function distMi(a, b) {
    var R = 3958.8,
      dLat = toRad(b.lat - a.lat),
      dLng = toRad(b.lng - a.lng);
    var x =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
  }
  function bearing(a, b) {
    var y = Math.sin(toRad(b.lng - a.lng)) * Math.cos(toRad(b.lat));
    var x =
      Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
      Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(toRad(b.lng - a.lng));
    return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
  }
  function angDiff(a, b) {
    var d = Math.abs(a - b) % 360;
    return d > 180 ? 360 - d : d;
  }
  function fmtMi(m) {
    return m < 0.1 ? '<0.1 mi' : m.toFixed(1) + ' mi';
  }
  /* SEPTA uses late:999 for "no delay data". It is never a real delay. */
  var LATE_NO_DATA_MIN = 900; /* a late value this large is a marker (998, 999), never a delay */
  function lateVal(v) {
    var n = Number(v);
    return v == null || v === '' || !isFinite(n) || n >= LATE_NO_DATA_MIN ? null : n;
  }
  function lateInfo(n) {
    if (n == null) return { txt: 'Delay data unavailable', cls: 'unk' };
    if (n === 0) return { txt: 'On time', cls: 'good' };
    if (n < 0) return { txt: Math.abs(n) + ' min early', cls: 'info' };
    return { txt: n + ' min late', cls: n <= 2 ? 'good' : n < 10 ? 'warn' : 'bad' };
  }
  function num(x) {
    var n = parseFloat(x);
    return isFinite(n) ? n : null;
  }
  function headingVal(h) {
    if (h == null || h === '') return null;
    var n = Number(h);
    return isFinite(n) ? n : null;
  }
  function parseSeptaDate(s) {
    var m = /(\d+)\/(\d+)\/(\d+)\s+(\d+):(\d+)\s*(AM|PM)/i.exec(s || '');
    if (!m) return null;
    var h = (Number(m[4]) % 12) + (/PM/i.test(m[6]) ? 12 : 0);
    return new Date(Number(m[3]), Number(m[1]) - 1, Number(m[2]), h, Number(m[5]));
  }
  function shortText(s, n) {
    s = String(s || '')
      .replace(/\s+/g, ' ')
      .trim();
    return s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : s;
  }
  function distM(a, b) {
    return distMi(a, b) * M_PER_MI;
  }
  /* Stored and fetched values are untrusted: a usable number is a finite number. */
  function isNum(x) {
    return typeof x === 'number' && isFinite(x);
  }
  /* ---------- App ---------- */
  function $(s) {
    return document.querySelector(s);
  }
  var store = {
    get: function (k, d) {
      try {
        var v = localStorage.getItem(k);
        return v ? JSON.parse(v) : d;
      } catch (e) {
        return d;
      }
    },
    set: function (k, v) {
      try {
        localStorage.setItem(k, JSON.stringify(v));
        return true;
      } catch (e) {
        return false;
      }
    }
  };
  /* The banner is role=alert and renderStatus runs every second, so only touch the DOM when something changed. */
  function showBanner(kind, html) {
    var b = $('#banner');
    kind = kind || '';
    if (b.className !== kind) b.className = kind;
    if (b.dataset.html !== html) {
      b.innerHTML = html;
      b.dataset.html = html;
    }
    if (b.hidden) b.hidden = false;
  }
  function hideBanner() {
    var b = $('#banner');
    if (!b.hidden) {
      b.hidden = true;
      delete b.dataset.html;
    }
  }
  S.util.REFRESH_MS = REFRESH_MS;
  S.util.GHOST_MAX_S = GHOST_MAX_S;
  S.util.DROP_AFTER_MS = DROP_AFTER_MS;
  S.util.M_PER_MI = M_PER_MI;
  S.util.widenedRadius = widenedRadius;
  S.util.kindOf = kindOf;
  S.util.CARD = CARD;
  S.util.CARD_LONG = CARD_LONG;
  S.util.SEATS = SEATS;
  S.util.MODE_NAME = MODE_NAME;
  S.util.esc = esc;
  S.util.cardinal = cardinal;
  S.util.toRad = toRad;
  S.util.distMi = distMi;
  S.util.bearing = bearing;
  S.util.angDiff = angDiff;
  S.util.fmtMi = fmtMi;
  S.util.lateVal = lateVal;
  S.util.lateInfo = lateInfo;
  S.util.num = num;
  S.util.headingVal = headingVal;
  S.util.parseSeptaDate = parseSeptaDate;
  S.util.shortText = shortText;
  S.util.distM = distM;
  S.util.$ = $;
  S.util.store = store;
  S.util.showBanner = showBanner;
  S.util.hideBanner = hideBanner;
  S.util.isNum = isNum;
  S.halt = typeof L === 'undefined';
  if (typeof L === 'undefined') {
    showBanner('', "<b>Map library didn't load.</b> Check your connection and reload.");
    return;
  }
  var PHILLY = { lat: 39.9526, lng: -75.1652, label: 'Center City (default view)' };
  /* Stored values are untrusted: anything malformed is ignored silently (and never rewritten on load). */
  var DEFAULT_FILTERS = { bus: true, trolley: false, subway: false, train: false },
    DEFAULT_RADIUS = 0.5;
  function cleanPrefs(p) {
    var o = p && typeof p === 'object' && !Array.isArray(p) ? p : {},
      c = o.center,
      f = o.filters,
      filters = {},
      k;
    for (k in DEFAULT_FILTERS)
      filters[k] = f && typeof f === 'object' && typeof f[k] === 'boolean' ? f[k] : DEFAULT_FILTERS[k];
    return {
      center:
        c &&
        typeof c === 'object' &&
        isNum(c.lat) &&
        isNum(c.lng) &&
        Math.abs(c.lat) <= 90 &&
        Math.abs(c.lng) <= 180
          ? { lat: c.lat, lng: c.lng, label: typeof c.label === 'string' ? c.label : '' }
          : PHILLY,
      radius:
        isNum(o.radius) && o.radius >= MIN_RADIUS_MI && o.radius <= MAX_RADIUS_MI ? o.radius : DEFAULT_RADIUS,
      filters: filters
    };
  }
  function cleanPlace(p, withId) {
    if (!p || typeof p !== 'object' || typeof p.name !== 'string' || !isNum(p.lat) || !isNum(p.lng))
      return null;
    if (withId && typeof p.id !== 'string') return null;
    var o = { name: p.name.slice(0, 40), lat: p.lat, lng: p.lng };
    if (withId) o.id = p.id;
    return o;
  }
  function cleanPlaces(r) {
    var o = r && typeof r === 'object' && !Array.isArray(r) ? r : {},
      list = [];
    if (Array.isArray(o.list))
      o.list.forEach(function (x) {
        if (list.length >= MAX_PLACES) return;
        var c = cleanPlace(x, true);
        if (c) list.push({ id: c.id, name: c.name, lat: c.lat, lng: c.lng });
      });
    return { home: cleanPlace(o.home, false), list: list };
  }
  var prefs = cleanPrefs(store.get('septa.prefs.v1', null));
  /* One-time migration (key septa.defaults.v2): browsers that saved the old defaults (all modes, 1.5 mi) get the new ones
   (buses only, 0.5 mi) once; center and any other saved fields are kept. Once the key exists saved choices are never touched. */
  (function () {
    var present;
    try {
      present = localStorage.getItem('septa.defaults.v2') !== null;
    } catch (e) {
      return;
    }
    if (present) return;
    var raw = store.get('septa.prefs.v1', null),
      o = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {},
      k;
    prefs.radius = DEFAULT_RADIUS;
    prefs.filters = {};
    for (k in DEFAULT_FILTERS) prefs.filters[k] = DEFAULT_FILTERS[k];
    o.center = prefs.center;
    o.radius = prefs.radius;
    o.filters = prefs.filters;
    store.set('septa.prefs.v1', o);
    store.set('septa.defaults.v2', '1');
  })();
  var placesStore = cleanPlaces(store.get('septa.places.v1', null));
  function cleanRoutes(r) {
    var stars = [],
      seen = {};
    if (r && typeof r === 'object' && Array.isArray(r.stars))
      r.stars.forEach(function (k) {
        if (typeof k === 'string' && k && k.length <= MAX_STAR_KEY_LEN && !seen[k]) {
          seen[k] = 1;
          stars.push(k);
        }
      });
    return { stars: stars, onlyMine: !(r && typeof r === 'object') || r.onlyMine !== false };
  }
  var routesStore = cleanRoutes(store.get('septa.routes.v1', null));
  function saveRoutes() {
    store.set('septa.routes.v1', routesStore);
  }
  function starKey(v) {
    return v.kind === 'train'
      ? 'train:' + v.route
      : v.kind === 'subway'
        ? 'subway:' + v.route
        : String(v.route);
  }
  function isStarred(k) {
    return routesStore.stars.indexOf(k) >= 0;
  }
  function routeFilterOn() {
    return routesStore.onlyMine && routesStore.stars.length > 0;
  }
  var state = {
    center: prefs.center,
    radius: prefs.radius,
    filters: prefs.filters,
    src: {
      bus: { list: [], ok: 0, stale: false, err: false },
      train: { list: [], ok: 0, stale: false, err: false }
    },
    paused: false,
    visible: [],
    selected: null,
    places: placesStore,
    alerts: { items: [], ok: 0, err: false, scope: 'near' },
    fetchedAt: 0
  };
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  S.util.PHILLY = PHILLY;
  S.util.routesStore = routesStore;
  S.util.saveRoutes = saveRoutes;
  S.util.starKey = starKey;
  S.util.isStarred = isStarred;
  S.util.routeFilterOn = routeFilterOn;
  S.util.state = state;
  S.util.el = el;
})();
