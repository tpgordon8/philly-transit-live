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
    MAX_BUFFER_MIN = 15,
    BAD_EXTRA_MIN = 4,
    MAX_WALK_MIN = 60,
    NO_PLACE_WALK = 5,
    SOON_MIN = 3,
    FAR_MIN = 45 /* an arrival further away than this is too uncertain to plan a departure from */,
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
    if (p.walkMin != null && !isInt(p.walkMin, 1, MAX_WALK_MIN)) return null;
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
      bufferMin: isInt(o.bufferMin, 0, MAX_BUFFER_MIN) ? o.bufferMin : BUFFER_DEFAULT,
      bad: o.bad === true
    };
  }
  /* True when validation changed a kept pin: a label or stop name cut, or a place id that was not usable turned into null. */
  function altered(r, c) {
    return c.pins.some(function (p) {
      var o = r.pins.find(function (x) {
        return S.util.isObj(x) && x.id === p.id;
      });
      return (
        !!o &&
        ((typeof o.label === 'string' && o.label !== '' && o.label !== p.label) ||
          (typeof o.stopName === 'string' && o.stopName !== '' && o.stopName !== p.stopName) ||
          (o.placeId != null && o.placeId !== p.placeId))
      );
    });
  }
  var board = S.util.loadChecked(KEY, cleanBoard, function (r, c) {
    return (
      !S.util.isObj(r) ||
      !Array.isArray(r.pins) ||
      r.pins.length !== c.pins.length ||
      altered(r, c) ||
      (r.bufferMin != null && r.bufferMin !== c.bufferMin) ||
      (r.bad != null && typeof r.bad !== 'boolean')
    );
  });
  var listeners = [],
    captured =
      {}; /* pin id -> {list: [{key, etaMin, rough, at}] soonest first, pending: count of approaching buses with no measured time} */
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
    if ('bufferMin' in patch && !isInt(patch.bufferMin, 0, MAX_BUFFER_MIN)) return false;
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
  /* The set walking time, else straight line x 1.3 at 1.25 m/s (1 to 60 min), else 5 min when there is no place. */
  function walkMin(pin) {
    if (pin.walkMin != null) return pin.walkMin;
    var pl = placeFor(pin);
    if (!pl) return NO_PLACE_WALK;
    return Math.min(MAX_WALK_MIN, Math.max(1, Math.ceil((distM(pl, pin) * DETOUR) / WALK_MPS / 60)));
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
      (o.walkMin != null && !isInt(o.walkMin, 1, MAX_WALK_MIN))
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
  /* patch: {walkMin} (1-60 or null for automatic) and/or {placeId}. Answers {ok:true} or {ok:false, reason:'invalid'|'unknown'}. */
  function updatePin(id, patch) {
    var pin = null;
    board.pins.forEach(function (p) {
      if (p.id === id) pin = p;
    });
    if (!pin) return { ok: false, reason: 'unknown' };
    var bad = { ok: false, reason: 'invalid' };
    if (!patch || typeof patch !== 'object') return bad;
    if ('walkMin' in patch && patch.walkMin != null && !isInt(patch.walkMin, 1, MAX_WALK_MIN)) return bad;
    if ('placeId' in patch) {
      var pid = patch.placeId == null ? null : patch.placeId;
      if (pid !== null && (typeof pid !== 'string' || !placeById(pid))) return bad;
      if (pid !== pin.placeId && hasPin(pin.route, pin.stopId, pid)) return bad;
    }
    if ('walkMin' in patch) pin.walkMin = patch.walkMin == null ? null : patch.walkMin;
    if ('placeId' in patch) pin.placeId = patch.placeId == null ? null : patch.placeId;
    save();
    return { ok: true };
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
  /* ----- Captured arrivals. Called after each feed apply. Each estimate is dated by its bus's OWN report: the feed fetch time minus
   how far that bus's GPS time is behind the newest report in this refresh (the feed's clock, so the device clock does not matter).
   A bus whose position is simply served again therefore keeps counting down instead of restarting at the fetch time. ----- */
  function refresh() {
    var b = state.src.bus,
      all = S.feed.collect(),
      newest = 0,
      next = {};
    all.forEach(function (v) {
      if (isFin(v.ts) && v.ts > newest) newest = v.ts;
    });
    board.pins.forEach(function (p) {
      var stop = { id: p.stopId, name: p.stopName, lat: p.lat, lng: p.lng, route: p.route },
        rows = S.stops.boardRows(stop, all),
        list = [],
        pending = 0;
      rows.a.concat(rows.b).forEach(function (r) {
        if (r.eta.min == null) {
          pending++;
          return;
        }
        var lag = isFin(r.v.ts) && newest ? Math.max(0, newest - r.v.ts) * 1000 : 0;
        list.push({ key: r.v.key, etaMin: r.eta.min, rough: !!r.eta.rough, at: b.ok - lag });
      });
      list.sort(function (x, y) {
        return x.etaMin - y.etaMin;
      });
      next[p.id] = { list: list.slice(0, 2), pending: pending };
    });
    captured = next;
    emit();
  }
  /* Decided on the exact value, shown rounded down (never promises more time than there is): later > 3, soon 1 to 3, else now. */
  function leaveState(leaveIn) {
    return leaveIn > SOON_MIN ? 'later' : leaveIn >= 1 ? 'soon' : 'now';
  }
  function rows(nowMs) {
    nowMs = isFin(nowMs) ? nowMs : Date.now();
    var b = state.src.bus,
      down = !b.ok || nowMs - b.ok > DROP_AFTER_MS,
      extra = board.bufferMin + (board.bad ? BAD_EXTRA_MIN : 0);
    return board.pins.map(function (pin) {
      var walk = walkMin(pin),
        pl = placeFor(pin),
        cap = captured[pin.id] || { list: [], pending: 0 },
        arrivals = [];
      if (!down)
        cap.list.forEach(function (c) {
          var left = c.etaMin - Math.max(0, nowMs - c.at) / 60000;
          if (left >= 0) {
            var a = { key: c.key, etaMin: left, rough: c.rough };
            if (left > FAR_MIN) a.far = true;
            arrivals.push(a);
          }
        });
      var leave = null,
        pick = null;
      arrivals.forEach(function (a) {
        if (!pick && a.etaMin >= walk) pick = a;
      });
      if (pick) {
        var leaveIn = pick.etaMin - walk - extra;
        leave = { inMin: Math.max(0, Math.floor(leaveIn)), state: leaveState(leaveIn), forKey: pick.key };
      } else if (arrivals.length) leave = { inMin: 0, state: 'missed', forKey: arrivals[0].key };
      if (
        leave &&
        arrivals.some(function (a) {
          return a.key === leave.forKey && a.far;
        })
      )
        leave = null;
      return {
        pin: Object.assign({}, pin),
        placeName: pl ? pl.name : null,
        walkMin: walk,
        source: down ? 'down' : b.stale ? 'stale' : 'live',
        arrivals: arrivals,
        pending: down ? 0 : cap.pending,
        note: pin.placeId && !pl ? 'place-removed' : '',
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
  S.board.MAX_WALK_MIN = MAX_WALK_MIN;
  S.board.MAX_BUFFER_MIN = MAX_BUFFER_MIN;
  S.board.FAR_MIN = FAR_MIN;
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
