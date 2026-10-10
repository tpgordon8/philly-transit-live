/* js/board.js: My stops board logic: pinned stops (septa.board.v1), walk times, captured arrival estimates and "leave in" states. No DOM. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var DROP_AFTER_MS = S.util.DROP_AFTER_MS,
    distM = S.util.distM,
    shortText = S.util.shortText,
    state = S.util.state,
    store = S.util.store;
  var STOP_ID_RE = S.stops.STOP_ID_RE,
    STOP_RT_RE = S.stops.STOP_RT_RE;
  var KEY = 'septa.board.v1',
    MAX_PINS = 8,
    MAX_LABEL = 30,
    MAX_STOP_NAME = 60,
    BUFFER_DEFAULT = 2,
    BUFFER_MAX = 15,
    BAD_EXTRA_MIN = 4,
    WALK_MAX = 60,
    NO_PLACE_WALK = 5,
    SOON_MIN = 3,
    DETOUR = 1.3,
    WALK_MPS = 1.25,
    ID_RE = /^[A-Za-z0-9_-]{1,40}$/;
  function isInt(n, lo, hi) {
    return typeof n === 'number' && Number.isInteger(n) && n >= lo && n <= hi;
  }
  function isFin(n) {
    return typeof n === 'number' && isFinite(n);
  }
  function pinKey(route, stopId, placeId) {
    return route + '|' + stopId + '|' + (placeId == null ? '' : placeId);
  }
  /* A stored pin, or null. A present but invalid walkMin drops the pin (like a bad leave-now rule); a missing one means automatic. */
  function cleanPin(p) {
    if (!p || typeof p !== 'object' || Array.isArray(p)) return null;
    if (typeof p.id !== 'string' || !ID_RE.test(p.id)) return null;
    if (typeof p.route !== 'string' || !STOP_RT_RE.test(p.route)) return null;
    if (typeof p.stopId !== 'string' || !STOP_ID_RE.test(p.stopId)) return null;
    if (!isFin(p.lat) || !isFin(p.lng)) return null;
    if (p.walkMin != null && !isInt(p.walkMin, 1, WALK_MAX)) return null;
    var placeId = typeof p.placeId === 'string' && p.placeId && p.placeId.length <= 64 ? p.placeId : null,
      name = shortText(
        typeof p.stopName === 'string' && p.stopName ? p.stopName : 'Stop ' + p.stopId,
        MAX_STOP_NAME
      );
    return {
      id: p.id,
      label: shortText(typeof p.label === 'string' && p.label ? p.label : name, MAX_LABEL),
      placeId: placeId,
      route: p.route,
      stopId: p.stopId,
      stopName: name,
      lat: p.lat,
      lng: p.lng,
      walkMin: p.walkMin == null ? null : p.walkMin
    };
  }
  function cleanBoard(raw) {
    var o = S.util.isObj(raw) ? raw : {},
      pins = [],
      ids = {},
      dups = {};
    (Array.isArray(o.pins) ? o.pins : []).forEach(function (r) {
      var p = pins.length < MAX_PINS ? cleanPin(r) : null;
      if (!p || ids[p.id] || dups[pinKey(p.route, p.stopId, p.placeId)]) return;
      ids[p.id] = dups[pinKey(p.route, p.stopId, p.placeId)] = 1;
      pins.push(p);
    });
    return {
      pins: pins,
      bufferMin: isInt(o.bufferMin, 0, BUFFER_MAX) ? o.bufferMin : BUFFER_DEFAULT,
      bad: o.bad === true
    };
  }
  var board = S.util.loadChecked(KEY, cleanBoard, function (r, c) {
    return (
      !S.util.isObj(r) ||
      !Array.isArray(r.pins) ||
      r.pins.length !== c.pins.length ||
      (r.bufferMin != null && r.bufferMin !== c.bufferMin) ||
      (r.bad != null && typeof r.bad !== 'boolean')
    );
  });
  var listeners = [],
    captured = {}; /* pin id -> [{key, etaMin, rough, at}], soonest first */
  function emit() {
    listeners.slice().forEach(function (fn) {
      try {
        fn();
      } catch (e) {
        /* a listener must not break the feed or another listener */
      }
    });
  }
  function save() {
    var ok = store.set(KEY, board);
    emit();
    return ok;
  }
  function onChange(fn) {
    if (typeof fn === 'function') listeners.push(fn);
  }
  function pins() {
    return board.pins.map(function (p) {
      return Object.assign({}, p);
    });
  }
  function settings() {
    return { bufferMin: board.bufferMin, bad: board.bad };
  }
  function setSettings(patch) {
    if (!patch || typeof patch !== 'object') return false;
    if ('bufferMin' in patch && !isInt(patch.bufferMin, 0, BUFFER_MAX)) return false;
    if ('bad' in patch && typeof patch.bad !== 'boolean') return false;
    if ('bufferMin' in patch) board.bufferMin = patch.bufferMin;
    if ('bad' in patch) board.bad = patch.bad;
    save();
    return true;
  }
  /* ----- Places and walking time ----- */
  function placeById(id) {
    var pl = state.places,
      i;
    if (id === 'home') return pl.home || null;
    for (i = 0; id && i < pl.list.length; i++) if (pl.list[i].id === id) return pl.list[i];
    return null;
  }
  function placeFor(pin) {
    var p = pin && placeById(pin.placeId);
    return p ? { name: p.name, lat: p.lat, lng: p.lng } : null;
  }
  /* The set walking time, else straight line x 1.3 at 1.25 m/s (at least 1 min), else 5 min when there is no place. */
  function walkMin(pin) {
    if (pin.walkMin != null) return pin.walkMin;
    var pl = placeFor(pin);
    if (!pl) return NO_PLACE_WALK;
    return Math.max(1, Math.ceil((distM(pl, pin) * DETOUR) / WALK_MPS / 60));
  }
  /* ----- Pins ----- */
  function hasPin(route, stopId, placeId) {
    var k = pinKey(route, stopId, placeId);
    return board.pins.some(function (p) {
      return pinKey(p.route, p.stopId, p.placeId) === k;
    });
  }
  function newId() {
    return 'b' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }
  function addPin(o) {
    o = o || {};
    var placeId = o.placeId == null ? null : o.placeId,
      stopId = o.stopId == null ? '' : String(o.stopId),
      route = o.route == null ? '' : String(o.route);
    if (
      !STOP_RT_RE.test(route) ||
      !STOP_ID_RE.test(stopId) ||
      !isFin(o.lat) ||
      !isFin(o.lng) ||
      (placeId !== null && (typeof placeId !== 'string' || !placeById(placeId))) ||
      (o.walkMin != null && !isInt(o.walkMin, 1, WALK_MAX))
    )
      return { ok: false, reason: 'invalid' };
    if (hasPin(route, stopId, placeId)) return { ok: false, reason: 'duplicate' };
    if (board.pins.length >= MAX_PINS) return { ok: false, reason: 'full' };
    var pin = cleanPin({
      id: newId(),
      label: o.label,
      placeId: placeId,
      route: route,
      stopId: stopId,
      stopName: o.stopName,
      lat: o.lat,
      lng: o.lng,
      walkMin: o.walkMin
    });
    board.pins.push(pin);
    var saved = save();
    return { ok: true, pin: Object.assign({}, pin), saved: saved };
  }
  function removePin(id) {
    for (var i = 0; i < board.pins.length; i++)
      if (board.pins[i].id === id) {
        board.pins.splice(i, 1);
        delete captured[id];
        save();
        return true;
      }
    return false;
  }
  function updatePin(id, patch) {
    var pin = null;
    board.pins.forEach(function (p) {
      if (p.id === id) pin = p;
    });
    if (!pin || !patch || typeof patch !== 'object') return false;
    if ('walkMin' in patch && patch.walkMin != null && !isInt(patch.walkMin, 1, WALK_MAX)) return false;
    if ('label' in patch && typeof patch.label !== 'string') return false;
    if ('placeId' in patch) {
      var pid = patch.placeId == null ? null : patch.placeId;
      if (pid !== null && (typeof pid !== 'string' || !placeById(pid))) return false;
      if (pid !== pin.placeId && hasPin(pin.route, pin.stopId, pid)) return false;
    }
    if ('walkMin' in patch) pin.walkMin = patch.walkMin == null ? null : patch.walkMin;
    if ('label' in patch) pin.label = shortText(patch.label, MAX_LABEL) || shortText(pin.stopName, MAX_LABEL);
    if ('placeId' in patch) pin.placeId = patch.placeId == null ? null : patch.placeId;
    save();
    return true;
  }
  /* The choices the stop card offers: Home and each saved place, then "No place". Only "No place" when nothing is saved. */
  function pinOptions() {
    var out = [];
    if (state.places.home) out.push({ placeId: 'home', name: 'Home' });
    state.places.list.forEach(function (p) {
      out.push({ placeId: p.id, name: p.name });
    });
    out.push({ placeId: null, name: 'No place' });
    return out;
  }
  function pinMessage(r) {
    if (r.ok) return r.saved ? 'Pinned to board.' : "Pinned to board. It can't be saved on this device.";
    return r.reason === 'full'
      ? 'Board is full (' + MAX_PINS + ' pins).'
      : r.reason === 'duplicate'
        ? 'Already on the board.'
        : "Couldn't pin this stop.";
  }
  /* Pin the stop on the open stop card (state.stop) to `placeId` (null or omitted: no place). Returns addPin's result plus msg. */
  function pinFromStop(placeId, extra) {
    var st = state.stop,
      r;
    if (!st) r = { ok: false, reason: 'invalid' };
    else
      r = addPin(
        Object.assign({}, extra, {
          route: st.route,
          stopId: st.id,
          stopName: st.name,
          lat: st.lat,
          lng: st.lng,
          placeId: placeId
        })
      );
    r.msg = pinMessage(r);
    return r;
  }
  /* ----- Captured arrivals. Called after each feed apply. The estimate is stamped with the time of the positions it came from
   (state.src.bus.ok), so a stale list re-captured later does not restart the countdown. ----- */
  function refresh() {
    var b = state.src.bus,
      all = S.feed.collect(),
      next = {};
    board.pins.forEach(function (p) {
      var stop = { id: p.stopId, name: p.stopName, lat: p.lat, lng: p.lng, route: p.route },
        rows = S.stops.boardRows(stop, all),
        list = [];
      rows.a.concat(rows.b).forEach(function (r) {
        if (r.eta.min != null) list.push({ key: r.v.key, etaMin: r.eta.min, rough: !!r.eta.rough, at: b.ok });
      });
      list.sort(function (x, y) {
        return x.etaMin - y.etaMin;
      });
      next[p.id] = list.slice(0, 2);
    });
    captured = next;
    emit();
  }
  function leaveState(inMin) {
    return inMin > SOON_MIN ? 'later' : inMin > 0 ? 'soon' : 'now';
  }
  function rows(nowMs) {
    nowMs = isFin(nowMs) ? nowMs : Date.now();
    var b = state.src.bus,
      down = !b.ok || nowMs - b.ok > DROP_AFTER_MS,
      extra = board.bufferMin + (board.bad ? BAD_EXTRA_MIN : 0);
    return board.pins.map(function (pin) {
      var walk = walkMin(pin),
        pl = placeFor(pin),
        arrivals = [];
      if (!down)
        (captured[pin.id] || []).forEach(function (c) {
          var left = c.etaMin - Math.max(0, nowMs - c.at) / 60000;
          if (left >= 0) arrivals.push({ key: c.key, etaMin: left, rough: c.rough });
        });
      var leave = null,
        pick = null;
      arrivals.forEach(function (a) {
        if (!pick && a.etaMin >= walk) pick = a;
      });
      if (pick) {
        var inMin = Math.ceil(pick.etaMin - walk - extra);
        leave = {
          inMin: Math.max(0, inMin),
          state: leaveState(pick.etaMin - walk - extra),
          forKey: pick.key
        };
      } else if (arrivals.length) leave = { inMin: 0, state: 'missed', forKey: arrivals[0].key };
      return {
        pin: Object.assign({}, pin),
        placeName: pl ? pl.name : null,
        walkMin: walk,
        source: down ? 'down' : b.stale ? 'stale' : 'live',
        arrivals: arrivals,
        leave: leave
      };
    });
  }
  onChange(function () {
    if (S.stops.updatePinRow)
      S.stops.updatePinRow(); /* keeps the stop card's button in step when pins change elsewhere */
  });
  S.board.KEY = KEY;
  S.board.MAX_PINS = MAX_PINS;
  S.board.BAD_EXTRA_MIN = BAD_EXTRA_MIN;
  S.board.pins = pins;
  S.board.addPin = addPin;
  S.board.removePin = removePin;
  S.board.updatePin = updatePin;
  S.board.hasPin = hasPin;
  S.board.pinOptions = pinOptions;
  S.board.settings = settings;
  S.board.setSettings = setSettings;
  S.board.placeFor = placeFor;
  S.board.walkMin = walkMin;
  S.board.rows = rows;
  S.board.refresh = refresh;
  S.board.pinFromStop = pinFromStop;
  S.board.onChange = onChange;
})();
