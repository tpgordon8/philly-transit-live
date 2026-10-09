/* js/feed.js: vehicle feed: ghost filter and normalisers, fetch through the Worker, idle pause, refresh loop and the collect/apply render pipeline. */
(function () {
  'use strict';
  var S = window.SEPTA;
  function renderDetail() {
    return S.map.renderDetail.apply(null, arguments);
  }
  function renderMyRoutes() {
    return S.panel.renderMyRoutes.apply(null, arguments);
  }
  function renderStatus() {
    return S.panel.renderStatus.apply(null, arguments);
  }
  function syncMarkers() {
    return S.map.syncMarkers.apply(null, arguments);
  }
  function renderStopBoard() {
    return S.stops.renderStopBoard.apply(null, arguments);
  }
  function updateBoardAge() {
    return S.stops.updateBoardAge.apply(null, arguments);
  }
  function updateSpeedHist() {
    return S.stops.updateSpeedHist.apply(null, arguments);
  }
  function evalRules() {
    return S.alerts.evalRules.apply(null, arguments);
  }
  function hasActiveRule() {
    return S.alerts.hasActiveRule.apply(null, arguments);
  }
  function loadAlerts() {
    return S.alerts.loadAlerts.apply(null, arguments);
  }
  function renderAlerts() {
    return S.alerts.renderAlerts.apply(null, arguments);
  }
  var SCHEDULE_ONLY_LATE = 998; /* SEPTA's late value for a trip with no live vehicle behind it */
  var GHOST_MAX_S = S.util.GHOST_MAX_S,
    headingVal = S.util.headingVal,
    kindOf = S.util.kindOf,
    lateVal = S.util.lateVal,
    num = S.util.num;
  /* The route's overall direction as a compass letter: Northbound -> N and so on. Loop, empty or anything else -> ''. */
  var DIR_LETTER = { northbound: 'N', eastbound: 'E', southbound: 'S', westbound: 'W' };
  function routeDirLetter(d) {
    var key = String(d == null ? '' : d)
      .trim()
      .toLowerCase();
    return DIR_LETTER[key] || '';
  }
  /* Anti-ghost rule: a bus counts only with a nonzero GPS timestamp that is close to the newest one in the feed.
   Timestamp 0 means schedule-only. Comparing against the feed's own newest timestamp keeps this correct
   even when the viewer's device clock is off. */
  function normBuses(json) {
    /* A 200 without the expected array is a malformed answer, not an empty feed: throw so the caller takes the stale/backoff path. */
    if (!json || !Array.isArray(json.bus)) throw new Error('bad bus feed');
    var list = json.bus;
    var cand = [],
      newest = 0,
      i,
      b,
      ts;
    /* First pass: every record that passes the non-freshness rules. `newest` is taken only over these, so one bogus
     record (empty ID, "None", bad coordinates, late 998) with a far-future timestamp cannot empty the map. */
    for (i = 0; i < list.length; i++) {
      b = list[i];
      if (!b || typeof b !== 'object') continue;
      ts = Number(b.timestamp);
      var lat = num(b.lat),
        lng = num(b.lng);
      if (!(ts > 0) || lat == null || lng == null || lat === 0 || lng === 0) continue;
      /* Schedule-only trips have no vehicle: VehicleID is "None" or empty, and SEPTA stamps the empty ones with the
       feed's own timestamp, so a freshness test alone lets them through. A real bus always has an ID and label. */
      var vid = String(b.VehicleID == null ? '' : b.VehicleID).trim(),
        lbl = String(b.label == null ? '' : b.label).trim();
      if (!vid || vid === 'None' || !lbl || lbl === 'None') continue;
      /* late:998 marks a schedule-only trip (no live vehicle behind it); 999 only means no delay data and is kept. */
      if (Number(b.late) === SCHEDULE_ONLY_LATE) continue;
      if (ts > newest) newest = ts;
      cand.push({ b: b, ts: ts, lat: lat, lng: lng, vid: vid });
    }
    var out = [];
    for (i = 0; i < cand.length; i++) {
      var c = cand[i];
      b = c.b;
      var age = newest - c.ts;
      if (age > GHOST_MAX_S) continue;
      var route = String(b.route_id);
      out.push({
        key: 'b' + c.vid,
        kind: kindOf(route),
        route: route,
        badge: route,
        lat: c.lat,
        lng: c.lng,
        ts: c.ts,
        heading: headingVal(b.heading),
        direction: b.Direction || '',
        dir: routeDirLetter(b.Direction),
        dest: b.destination || '',
        next: b.next_stop_name || '',
        nextId: b.next_stop_id == null ? '' : String(b.next_stop_id),
        late: lateVal(b.late),
        seats: b.estimated_seat_availability || '',
        vid: c.vid,
        age: age
      });
    }
    return out;
  }
  function normTrains(json) {
    if (!Array.isArray(json)) throw new Error('bad train feed');
    var list = json,
      out = [];
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      if (!t || typeof t !== 'object') continue;
      var lat = num(t.lat),
        lng = num(t.lon);
      if (lat == null || lng == null || lat === 0 || lng === 0) continue;
      out.push({
        key: 't' + t.trainno,
        kind: 'train',
        route: String(t.line || ''),
        badge: String(t.trainno),
        lat: lat,
        lng: lng,
        heading: headingVal(t.heading),
        direction: '',
        dir: '',
        dest: t.dest || '',
        next: t.nextstop || '',
        cur: t.currentstop || '',
        late: lateVal(t.late),
        track: t.TRACK || '',
        service: t.service || '',
        source: t.SOURCE || '',
        vid: String(t.trainno),
        age: null
      });
    }
    return out;
  }
  function alertKey(a) {
    var mode = String(a.mode || '');
    if (mode === 'Bus' || mode === 'Trolley') return String(a.route);
    if (mode === 'generic') return '*';
    return String(a.route_name || '').toLowerCase();
  }
  function vehicleAlertKey(v) {
    return v.kind === 'train' ? v.route.toLowerCase() : v.route;
  }
  S.feed.normBuses = normBuses;
  S.feed.normTrains = normTrains;
  S.feed.alertKey = alertKey;
  S.feed.vehicleAlertKey = vehicleAlertKey;
  if (S.halt) return;
  var $ = S.util.$,
    DROP_AFTER_MS = S.util.DROP_AFTER_MS,
    REFRESH_MS = S.util.REFRESH_MS,
    widenedRadius = S.util.widenedRadius,
    distMi = S.util.distMi,
    esc = S.util.esc,
    isStarred = S.util.isStarred;
  var routeFilterOn = S.util.routeFilterOn,
    starKey = S.util.starKey,
    state = S.util.state;
  /* ----- Network: SEPTA's API sends no CORS headers, so every call goes through our own Cloudflare Worker.
   The Worker forwards an allowlist of SEPTA feeds and a few validated query endpoints, and adds CORS; the list changes
   with the Worker version, so see ARCHITECTURE.md section 2 for the current endpoints. Retry once on failure. ----- */
  var FETCH_TIMEOUT_MS = 15000; /* one request to the Worker */
  var FETCH_RETRY_MS = 1500; /* pause before the single retry */
  var WORKER = 'https://septa-proxy.tpgordon8.workers.dev';
  /* ----- Idle pause (ARCHITECTURE.md section 2): after an hour without a real user interaction the page makes no
   requests at all. Only pointerdown, keydown, touchstart, wheel, focus and becoming visible count; timers and fetches do not. ----- */
  var IDLE_MS = 60 * 60 * 1000,
    lastUse = Date.now();
  function idleNow() {
    return Date.now() - lastUse >= IDLE_MS;
  }
  function pauseNow() {
    if (state.paused) return;
    state.paused = true;
    $('#idleMsg').textContent =
      'Paused to save requests after an hour without use. Tap anywhere or press Resume to continue.' +
      (hasActiveRule() ? ' Leave-now alerts are paused as well.' : '');
    $('#idleBar').hidden = false;
    renderStatus();
    /* Data older than 120 s is dropped by collect(); redraw once it has aged out so the map empties honestly. */
    setTimeout(function () {
      if (state.paused) apply();
    }, DROP_AFTER_MS + 1000);
  }
  function markUse() {
    lastUse = Date.now();
    if (!state.paused) return;
    state.paused = false;
    $('#idleBar').hidden = true;
    nextTry.bus = 0;
    nextTry.train = 0;
    renderStatus();
    refresh(true);
    loadAlerts();
  }
  ['pointerdown', 'keydown', 'touchstart', 'wheel'].forEach(function (t) {
    document.addEventListener(
      t,
      function (e) {
        if (e.isTrusted) markUse();
      },
      { capture: true, passive: true }
    );
  });
  window.addEventListener('focus', markUse);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) markUse();
  });
  $('#resumeBtn').addEventListener('click', markUse);
  function fetchOnce(name) {
    if (idleNow()) return Promise.reject(new Error('idle'));
    var ctl = new AbortController(),
      t = setTimeout(function () {
        ctl.abort();
      }, FETCH_TIMEOUT_MS);
    return fetch(WORKER + '/' + name, { signal: ctl.signal, cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .finally(function () {
        clearTimeout(t);
      });
  }
  function septa(path) {
    /* 'TransitView/index.php' -> 'TransitView'; a path with a query ('Stops?route=21') is passed through whole. */
    var name = path.indexOf('?') >= 0 ? path : path.split('/')[0];
    return fetchOnce(name).catch(function () {
      return new Promise(function (res) {
        setTimeout(res, FETCH_RETRY_MS);
      }).then(function () {
        return fetchOnce(name);
      });
    });
  }
  /* ----- Applying data to the view ----- */
  function collect() {
    var now = Date.now(),
      all = [];
    ['bus', 'train'].forEach(function (s) {
      var src = state.src[s];
      if (!src.ok || now - src.ok > DROP_AFTER_MS || skipped[s]) return;
      src.list.forEach(function (v) {
        all.push(Object.assign({}, v, { stale: src.stale }));
      });
    });
    return all;
  }
  function apply() {
    var all = collect(),
      counts = { bus: 0, trolley: 0, subway: 0, train: 0 },
      vis = [],
      inRadius = 0,
      rf = routeFilterOn();
    all.forEach(function (v) {
      if (distMi(state.center, v) > state.radius) return;
      inRadius++;
      if (rf && !isStarred(starKey(v))) return;
      counts[v.kind]++;
      if (state.filters[v.kind]) vis.push(v);
    });
    state.visible = vis;
    syncMarkers(vis);
    /* A source that is not being fetched has no trustworthy count: show nothing rather than a wrong number. */
    var w = wantedSources();
    document.querySelectorAll('[data-n]').forEach(function (n) {
      var k = n.dataset.n,
        sk = k === 'train' ? 'train' : 'bus';
      n.textContent = !w[sk] || skipped[sk] ? '' : counts[k];
    });
    renderEmpty(all.length, vis.length, counts, rf && inRadius > 0);
    renderMyRoutes();
    renderDetail();
    renderAlerts();
    renderStatus();
    renderStopBoard();
    evalRules();
    var w2 = wantedSources();
    if (!inflight && ((w2.bus && skipped.bus) || (w2.train && skipped.train))) refresh(true);
  }
  function renderEmpty(totalLoaded, visCount, counts, routeHides) {
    var box = $('#empty'),
      anyOk = state.src.bus.ok || state.src.train.ok;
    if (state.paused) {
      box.hidden = true;
      return;
    }
    var totalNear = counts.bus + counts.trolley + counts.subway + counts.train;
    if (!anyOk || visCount > 0) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    if (routeHides && totalNear === 0) {
      box.innerHTML =
        '<h3>Quiet around here</h3><p>None of your starred routes are running nearby right now.</p><button class="btn primary" type="button" id="emptyAct" data-act="routes">Show all routes</button>';
      return;
    }
    var r = state.radius,
      canWiden = r < 5;
    var msg =
      totalNear > 0
        ? 'Everything nearby is hidden by your mode filters.'
        : 'No SEPTA vehicles have a fresh GPS report within ' + r + ' mi of here right now.';
    box.innerHTML =
      '<h3>Quiet around here</h3><p>' +
      esc(msg) +
      '</p>' +
      (totalNear > 0
        ? '<button class="btn primary" type="button" id="emptyAct" data-act="modes">Show all modes</button>'
        : canWiden
          ? '<button class="btn primary" type="button" id="emptyAct" data-act="widen">Widen to ' +
            widenedRadius(r) +
            ' mi</button>'
          : '<p style="margin:0">Try searching a different address.</p>');
  }
  /* ----- Refresh loop ----- */
  /* Request budget (see ARCHITECTURE.md section 2). A source is fetched only when something on screen needs it:
   TrainView while the Regional Rail chip is on; TransitView while any of Bus/Trolley/Subway is on, or an enabled
   leave-now rule exists, or a stop is open. A failing source backs off 15 s x 2^N (cap 120 s) by skipping ticks. */
  var inflight = false,
    lastStart = 0,
    skipped = { bus: false, train: false },
    fails = { bus: 0, train: 0 },
    nextTry = { bus: 0, train: 0 };
  /* No input for QUIET_MS in a visible tab: refresh every SLOW_REFRESH_MS instead of every REFRESH_MS (ARCHITECTURE.md section 5). */
  var QUIET_MS = 10 * 60 * 1000,
    SLOW_REFRESH_MS = 30000;
  var BACKOFF_BASE_MS = 15000,
    BACKOFF_MAX_MS = 120000,
    HIDDEN_MS = 60000;
  function wantedSources() {
    var f = state.filters;
    return { bus: !!(f.bus || f.trolley || f.subway || hasActiveRule() || state.stop), train: !!f.train };
  }
  function refresh(force) {
    if (idleNow()) {
      pauseNow();
      return Promise.resolve();
    }
    if (inflight) return Promise.resolve();
    inflight = true;
    var now = Date.now(),
      w = wantedSources(),
      was = { bus: skipped.bus, train: skipped.train };
    lastStart = now;
    skipped.bus = !w.bus;
    skipped.train = !w.train;
    function run(k, path, parse) {
      if (!w[k]) return Promise.resolve();
      if (now < nextTry[k] - 500 && !(force && was[k])) return Promise.resolve();
      return septa(path)
        .then(function (j) {
          var s = state.src[k];
          s.list = parse(j);
          if (k === 'bus') updateSpeedHist(s.list);
          s.ok = Date.now();
          s.stale = false;
          s.err = false;
          fails[k] = 0;
          nextTry[k] = 0;
        })
        .catch(function () {
          var s = state.src[k];
          s.stale = true;
          s.err = true;
          fails[k]++;
          nextTry[k] = now + Math.min(BACKOFF_BASE_MS * Math.pow(2, fails[k]), BACKOFF_MAX_MS);
        });
    }
    var p1 = run('bus', 'TransitView/index.php', normBuses),
      p2 = run('train', 'TrainView/index.php', normTrains);
    return Promise.all([p1, p2]).then(
      function () {
        state.fetchedAt = Date.now();
        inflight = false;
        apply();
      },
      function () {
        inflight = false;
      }
    );
  }
  /* A hidden tab normally skips refresh (protects the free-tier request budget). With an enabled leave-now alert it
   keeps refreshing, but only once a minute (HIDDEN_MS) instead of every 15 s. */
  setInterval(function () {
    if (idleNow()) {
      pauseNow();
      return;
    }
    if (!document.hidden) {
      if (Date.now() - lastUse >= QUIET_MS && Date.now() - lastStart < SLOW_REFRESH_MS - REFRESH_MS / 2)
        return;
      refresh();
      return;
    }
    if (hasActiveRule() && Date.now() - lastStart >= HIDDEN_MS - REFRESH_MS / 2) refresh();
  }, REFRESH_MS);
  setInterval(function () {
    if (state.fetchedAt) {
      renderStatus();
      updateBoardAge();
    }
  }, 1000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && Date.now() - state.fetchedAt > REFRESH_MS) refresh();
  });
  S.feed.idleNow = idleNow;
  S.feed.pauseNow = pauseNow;
  S.feed.septa = septa;
  S.feed.collect = collect;
  S.feed.apply = apply;
  S.feed.skipped = skipped;
  S.feed.wantedSources = wantedSources;
  S.feed.refresh = refresh;
})();
